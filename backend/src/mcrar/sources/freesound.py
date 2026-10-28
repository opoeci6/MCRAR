"""Freesound (APIv2) client: music-like sound search, lookup by id and in-memory previews.

Design notes
- Freesound is a source of *music-like sounds only* (music, loops, ambience, soundscapes, at
  least ``duration_min_s`` long), not of sound effects. The audio is the mp3 preview of the
  sound (``previews["preview-hq-mp3"]``), streamed into memory and never written to disk. The
  original files need a Freesound login (OAuth), so ``download_url`` is the sound page.
- The API key is a secret sent only as an ``Authorization: Token <key>`` header, never in a URL,
  and never to the preview CDN. Nothing from httpx is surfaced as is: failures are re-raised as
  ``FreesoundError`` with a redacted, URL-free message, outside of any ``except`` block so no
  exception chain keeps the original around. Cache keys, cache file names and the usage file
  never include the key.
- Freesound limits are about 60 requests/minute and 2,000/day: requests are throttled, 429 is
  retried honouring ``Retry-After`` (capped), and a per-day request counter backs ``usage()``.
- Only JSON API responses are cached on disk (7 days). An empty page is never cached.
- Every Freesound-specific API fact (URLs, field list, licence names, the music-like filter) is
  a module constant below so it is easy to fix once it is checked against a real key.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar
from urllib.parse import quote, quote_plus, urlsplit

import httpx

from mcrar.sources.base import SourceTrack
from mcrar.sources.jamendo import _mapping, _RedactingFilter, _str, _str_list, _to_float

if TYPE_CHECKING:
    from mcrar.config import Settings
    from mcrar.secrets import SecretStore

logger = logging.getLogger(__name__)

SOURCE_NAME = "freesound"
SECRET_NAME = "freesound_api_key"
API_BASE = "https://freesound.org/apiv2/"
SEARCH_URL = API_BASE + "search/"
STREAM_HOST = "freesound.org"  # previews live on cdn.freesound.org; subdomains are accepted
PREVIEW_FIELD = "preview-hq-mp3"
MAX_PAGE_SIZE = 150
MAX_ID_BATCH = 100
MAX_RETRY_AFTER_S = 60.0
USAGE_FILE = "usage.json"
USAGE_WARN_THRESHOLD = 1_500  # Freesound allows about 2,000 requests per day
DEFAULT_CACHE_TTL_S = 7 * 24 * 3600
DEFAULT_MAX_AUDIO_BYTES = 40_000_000
_REDACTED = "***"
_TOKEN_RE = re.compile(r"(Token\s+)[^\s'\"]+", re.IGNORECASE)

# When ``fields`` is given it replaces the API defaults, so every field we read is listed.
FIELDS = (
    "id,url,name,tags,description,license,username,duration,previews,pack,category,"
    "gen_ai_preference,created,num_downloads,avg_rating,type,samplerate,channels"
)
SORTS = (
    "score",
    "duration_desc",
    "duration_asc",
    "created_desc",
    "created_asc",
    "downloads_desc",
    "downloads_asc",
    "rating_desc",
    "rating_asc",
)
# Search key -> Freesound licence name (as used in the ``license`` filter).
LICENSE_NAMES: dict[str, str] = {
    "cc0": "Creative Commons 0",
    "by": "Attribution",
    "by-nc": "Attribution NonCommercial",
    "sampling+": "Sampling+",
}
# Licence names Freesound may report in place of a URL (lowercase) -> a CC URL. The API gives no
# version with a name, so the current one is assumed (the family is what matters).
_LICENSE_NAME_URLS: dict[str, str] = {
    "creative commons 0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "attribution": "https://creativecommons.org/licenses/by/4.0/",
    "attribution noncommercial": "https://creativecommons.org/licenses/by-nc/4.0/",
    "attribution non-commercial": "https://creativecommons.org/licenses/by-nc/4.0/",
    "sampling+": "https://creativecommons.org/licenses/sampling+/1.0/",
}
# "Music-like" content as a tag clause. The Broad Sound Taxonomy ``category`` values are not
# verified yet; revisit this (and use a category filter) after the check with a real API key.
MUSIC_LIKE_FILTER = (
    "tag:(music OR loop OR ambience OR ambient OR soundscape OR atmosphere OR drone "
    "OR melody OR soundtrack OR pad)"
)

_TAG_RE = re.compile(r"[a-z0-9_-]+")
_ID_RE = re.compile(r"[0-9]+")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

T = TypeVar("T")


class FreesoundError(RuntimeError):
    """A Freesound request failed. Messages never contain the API key."""


class FreesoundAuthError(FreesoundError):
    """The API key was rejected (HTTP 401/403 from the API)."""


class FreesoundRateLimitError(FreesoundError):
    """Still rate limited (HTTP 429) after all retries."""


class FreesoundStreamError(FreesoundError):
    """The audio preview could not be fetched (or its URL is not a Freesound one)."""


# --------------------------------------------------------------------------------------
# Mapping JSON -> SourceTrack
# --------------------------------------------------------------------------------------


def normalise_license(value: object) -> str | None:
    """A licence URL as is, a human licence name (``Attribution``) as its CC URL, else raw."""
    text = _str(value)
    if text is None:
        return None
    return _LICENSE_NAME_URLS.get(" ".join(text.lower().split()), text)


def _date(value: object) -> str | None:
    text = _str(value)
    if text is None:
        return None
    day = text[:10]
    return day if _DATE_RE.fullmatch(day) else None


def _str_or_list(value: object) -> list[str]:
    """``category`` and ``gen_ai_preference`` may be a string or a list of strings."""
    if isinstance(value, list):
        return _str_list(value)
    text = _str(value)
    return [text] if text is not None else []


def parse_sound(data: Mapping[str, Any]) -> SourceTrack | None:
    """Map one Freesound sound object to a :class:`SourceTrack`.

    None (with a debug log) when it has no id or no ``preview-hq-mp3`` preview, since there
    would be no audio to analyse.
    """
    source_id = _str(data.get("id"))
    if source_id is None:
        logger.debug("Skipping a Freesound sound without id")
        return None
    stream_url = _str(_mapping(data.get("previews")).get(PREVIEW_FIELD))
    if stream_url is None:
        logger.debug("Skipping Freesound sound %s: no %s preview", source_id, PREVIEW_FIELD)
        return None
    page_url = _str(data.get("url"))
    tags: dict[str, object] = {
        "vartags": _str_list(data.get("tags")),
        "category": _str_or_list(data.get("category")),
        "gen_ai_preference": _str_or_list(data.get("gen_ai_preference")),
    }
    return SourceTrack(
        source=SOURCE_NAME,
        source_id=source_id,
        title=_str(data.get("name")) or "",
        artist=_str(data.get("username")) or "",
        album=None,
        duration_s=_to_float(data.get("duration")),
        release_date=_date(data.get("created")),
        source_url=page_url,
        stream_url=stream_url,
        download_url=page_url,
        audiodownload_allowed=True,
        license_url=normalise_license(data.get("license")),
        commercial_license_url=None,
        image_url=None,
        vocal_instrumental=None,
        tags=tags,
    )


# --------------------------------------------------------------------------------------
# Query building
# --------------------------------------------------------------------------------------


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def _tag_list(tags: str | Sequence[str]) -> list[str]:
    values = [tags] if isinstance(tags, str) else list(tags)
    out: list[str] = []
    for value in values:
        tag = str(value).strip().lower()
        if not _TAG_RE.fullmatch(tag):
            raise ValueError(
                f"Invalid tag {value!r}: only letters, digits, '_' and '-' are allowed"
            )
        out.append(tag)
    return list(dict.fromkeys(out))


def build_filter(
    *,
    tags: str | Sequence[str] = (),
    licenses: Sequence[str] = ("cc0", "by"),
    duration_min_s: float | None = 10.0,
    duration_max_s: float | None = 600.0,
    music_like: bool = True,
) -> str:
    """The Solr ``filter`` string: clauses joined by spaces (AND). ValueError on bad input."""
    clauses: list[str] = []
    if duration_min_s is not None and duration_min_s < 0:
        raise ValueError("duration_min_s must not be negative")
    if (
        duration_min_s is not None
        and duration_max_s is not None
        and duration_max_s < duration_min_s
    ):
        raise ValueError("duration_max_s must not be below duration_min_s")
    if duration_min_s is not None or duration_max_s is not None:
        low = "*" if duration_min_s is None else _number(duration_min_s)
        high = "*" if duration_max_s is None else _number(duration_max_s)
        clauses.append(f"duration:[{low} TO {high}]")
    names: list[str] = []
    for key in licenses:
        name = LICENSE_NAMES.get(str(key).strip().lower())
        if name is None:
            raise ValueError(f"Unknown licence {key!r}; expected one of {sorted(LICENSE_NAMES)}")
        if name not in names:
            names.append(name)
    if names:
        clauses.append("license:(" + " OR ".join(f'"{name}"' for name in names) + ")")
    clauses.extend(f"tag:{tag}" for tag in _tag_list(tags))
    if music_like:
        clauses.append(MUSIC_LIKE_FILTER)
    return " ".join(clauses)


# --------------------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------------------


class _Failure:
    """A transient failure of one attempt (the caller decides whether to retry)."""

    def __init__(
        self, reason: str, *, rate_limited: bool = False, retry_after: float | None = None
    ) -> None:
        self.reason = reason
        self.rate_limited = rate_limited
        self.retry_after = retry_after


@dataclass(frozen=True)
class _Page:
    results: list[Any]
    has_next: bool


def _retry_after(response: httpx.Response) -> float | None:
    """The ``Retry-After`` header in seconds (the HTTP-date form is ignored), else None."""
    try:
        seconds = float(response.headers.get("retry-after", "").strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


class FreesoundClient:
    def __init__(
        self,
        api_key: str,
        *,
        cache_dir: Path | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
        max_attempts: int = 3,
        min_interval_s: float = 1.1,
        cache_ttl_s: float = DEFAULT_CACHE_TTL_S,
        use_cache: bool = True,
        backoff_s: float = 1.0,
        usage_warn_threshold: int = USAGE_WARN_THRESHOLD,
        max_bytes: int = DEFAULT_MAX_AUDIO_BYTES,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("A non-empty Freesound API key is required")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._api_key = api_key.strip()
        self._cache_dir = Path(cache_dir) if cache_dir is not None else None
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._min_interval_s = min_interval_s
        self._cache_ttl_s = cache_ttl_s
        self.use_cache = use_cache
        self._backoff_s = backoff_s
        self._usage_warn_threshold = usage_warn_threshold
        self._max_bytes = max_bytes
        self._clock = clock
        self._sleep = sleep
        self._last_request_at: float | None = None
        self._usage_lock = threading.Lock()
        self._mem_usage: dict[str, Any] = {}
        self._usage_warned = False
        # No Authorization default header: previews on the CDN must not get the key.
        self._http = httpx.Client(
            transport=transport,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "mcrar/0.1 (freesound client)"},
        )
        # Defence in depth: the key is only sent in a header, which httpx does not log.
        self._log_filter = _RedactingFilter(self._redact)
        logging.getLogger("httpx").addFilter(self._log_filter)

    def __repr__(self) -> str:
        return f"FreesoundClient(cache_dir={self._cache_dir!r})"

    # -- construction / lifecycle ------------------------------------------------------

    @classmethod
    def from_settings(
        cls,
        settings: Settings | None = None,
        secret_store: SecretStore | None = None,
        **kwargs: Any,
    ) -> FreesoundClient:
        """Build a client from the stored ``freesound_api_key`` secret and ``cache_dir``."""
        from mcrar.config import get_settings  # noqa: PLC0415
        from mcrar.secrets import SecretStore  # noqa: PLC0415

        settings = settings or get_settings()
        store = secret_store or SecretStore(settings)
        api_key = store.get(SECRET_NAME)
        if not api_key:
            raise FreesoundError(
                "No Freesound API key is configured. Get a free one at "
                "https://freesound.org/apiv2/apply and store it with: "
                f"mcrar secrets set {SECRET_NAME}"
            )
        kwargs.setdefault("cache_dir", settings.cache_dir / "freesound")
        return cls(api_key, **kwargs)

    def close(self) -> None:
        self._http.close()
        logging.getLogger("httpx").removeFilter(self._log_filter)

    def __enter__(self) -> FreesoundClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- redaction ---------------------------------------------------------------------

    def _redact(self, text: str) -> str:
        variants = {self._api_key, quote(self._api_key, safe=""), quote_plus(self._api_key)}
        for variant in variants:
            text = text.replace(variant, _REDACTED)
        return _TOKEN_RE.sub(r"\1" + _REDACTED, text)

    def _error(self, cls: type[FreesoundError], message: str) -> FreesoundError:
        return cls(self._redact(message))

    # -- public API --------------------------------------------------------------------

    def search_tracks(
        self,
        *,
        query: str = "",
        tags: str | Sequence[str] = (),
        licenses: Sequence[str] = ("cc0", "by"),
        duration_min_s: float | None = 10.0,
        duration_max_s: float | None = 600.0,
        sort: str = "score",
        music_like: bool = True,
        limit: int = 50,
    ) -> Iterator[SourceTrack]:
        """Lazily yield tracks of up to ``limit`` search results, in pages of up to 150.

        ``tags`` must all match (AND; only ``[a-z0-9_-]`` is accepted), ``licenses`` are keys of
        ``LICENSE_NAMES`` (any of them), and ``music_like`` restricts to music-like content
        (``MUSIC_LIKE_FILTER``). ``limit`` counts the results received, so sounds without a
        usable preview (skipped) count too. Bad arguments raise ValueError immediately; network
        errors surface when the iterator is consumed.
        """
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if sort not in SORTS:
            raise ValueError(f"Unknown sort {sort!r}; expected one of {list(SORTS)}")
        flt = build_filter(
            tags=tags,
            licenses=licenses,
            duration_min_s=duration_min_s,
            duration_max_s=duration_max_s,
            music_like=music_like,
        )
        params: dict[str, str] = {"sort": sort}
        text = " ".join(query.split())
        if text:
            params["query"] = text
        if flt:
            params["filter"] = flt
        return self._iter_search(params, limit)

    def get_tracks(self, ids: Sequence[str | int], *, use_cache: bool = False) -> list[SourceTrack]:
        """Fetch sounds by id (batches of up to 100), in the order requested.

        Unknown ids (and sounds without a usable preview) are absent from the result. ``ids``
        must be integers or digit strings, else ValueError. The cache is bypassed by default.
        """
        unique: list[str] = []
        for raw in ids:
            text = str(raw).strip()
            if isinstance(raw, bool) or not _ID_RE.fullmatch(text):
                raise ValueError(f"Invalid Freesound id {raw!r}: expected digits only")
            unique.append(str(int(text)))
        unique = list(dict.fromkeys(unique))
        by_id: dict[str, SourceTrack] = {}
        for start in range(0, len(unique), MAX_ID_BATCH):
            batch = unique[start : start + MAX_ID_BATCH]
            params = {"filter": "id:(" + " OR ".join(batch) + ")", "page_size": str(len(batch))}
            page = self._get_page(params, page=1, use_cache=use_cache)
            for item in page.results:
                track = parse_sound(item) if isinstance(item, Mapping) else None
                if track is not None:
                    by_id[track.source_id] = track
        return [by_id[i] for i in unique if i in by_id]

    def fetch_audio(self, track: SourceTrack, *, max_bytes: int | None = None) -> bytes:
        """Download the preview into memory (never to disk), at most ``max_bytes``."""
        limit = self._max_bytes if max_bytes is None else max_bytes
        url = track.stream_url
        if not url:
            raise self._error(
                FreesoundStreamError,
                f"Track {track.source_id} has no stream_url; refresh it with get_tracks()",
            )
        if not _is_freesound_https(url):
            raise self._error(
                FreesoundStreamError,
                f"Track {track.source_id} has a stream_url that is not an https {STREAM_HOST} URL",
            )
        what = f"audio download of track {track.source_id}"
        return self._retrying(what, lambda: self._attempt_audio(url, track.source_id, limit))

    def usage(self) -> dict[str, Any]:
        """``{"day": "YYYY-MM-DD", "requests": n, "cache_hits": m}`` for today (UTC)."""
        with self._usage_lock:
            return dict(self._read_usage())

    # -- search / paging ---------------------------------------------------------------

    def _iter_search(self, params: dict[str, str], limit: int) -> Iterator[SourceTrack]:
        # One page size for all pages: Freesound pages by ``page_size`` blocks, so a smaller
        # last page would re-read earlier results.
        size = min(MAX_PAGE_SIZE, limit)
        fetched = 0
        page_no = 1
        while fetched < limit:
            page = self._get_page({**params, "page_size": str(size)}, page=page_no, use_cache=None)
            for item in page.results[: limit - fetched]:
                track = parse_sound(item) if isinstance(item, Mapping) else None
                if track is not None:
                    yield track
            fetched += len(page.results)
            if not page.has_next or not page.results:
                return
            page_no += 1

    def _get_page(self, params: dict[str, str], *, page: int, use_cache: bool | None) -> _Page:
        full = {**params, "page": str(page), "fields": FIELDS}
        cached_allowed = self.use_cache if use_cache is None else use_cache
        key = self._cache_key(full)
        if cached_allowed:
            cached = self._cache_read(key)
            if cached is not None:
                logger.debug("Freesound cache hit %s", key[:12])
                self._count_cache_hit()
                return cached
        result = self._retrying("Freesound API request", lambda: self._attempt_api(full))
        if cached_allowed and result.results:
            self._cache_write(key, result)
        return result

    # -- retry machinery ---------------------------------------------------------------

    def _retrying(self, what: str, attempt: Callable[[], T | _Failure]) -> T:
        last: _Failure | None = None
        for n in range(1, self._max_attempts + 1):
            result = attempt()
            if not isinstance(result, _Failure):
                return result
            last = result
            if n < self._max_attempts:
                if result.retry_after is not None:
                    delay = min(result.retry_after, MAX_RETRY_AFTER_S)
                else:
                    delay = self._backoff_s * 2 ** (n - 1)
                logger.warning(
                    "%s failed (%s); retrying in %.1fs (attempt %d/%d)",
                    what,
                    self._redact(result.reason),
                    delay,
                    n + 1,
                    self._max_attempts,
                )
                self._sleep(delay)
        assert last is not None
        cls = FreesoundRateLimitError if last.rate_limited else FreesoundError
        raise self._error(cls, f"{what} failed after {self._max_attempts} attempts: {last.reason}")

    def _throttle(self) -> None:
        if self._last_request_at is not None and self._min_interval_s > 0:
            wait = self._min_interval_s - (self._clock() - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
        self._last_request_at = self._clock()

    def _attempt_api(self, params: dict[str, str]) -> _Page | _Failure:
        self._throttle()
        self._count_request()
        failure: _Failure | None = None
        fatal: str | None = None
        response: httpx.Response | None = None
        try:
            response = self._http.get(
                SEARCH_URL,
                params=params,
                headers={"Authorization": f"Token {self._api_key}"},
            )
        except httpx.TimeoutException:
            failure = _Failure("timeout")
        except httpx.TransportError as exc:
            failure = _Failure(type(exc).__name__)
        except httpx.HTTPError as exc:
            fatal = type(exc).__name__
        # Everything below runs outside the except blocks so no httpx exception stays attached
        # to the exceptions raised here.
        if fatal is not None:
            raise self._error(FreesoundError, f"Freesound API request failed: {fatal}")
        if failure is not None or response is None:
            return failure or _Failure("no response")
        return self._interpret(response)

    def _interpret(self, response: httpx.Response) -> _Page | _Failure:
        status = response.status_code
        if status in (401, 403):
            raise self._error(
                FreesoundAuthError,
                f"Freesound rejected the request (HTTP {status}); check the stored "
                f"{SECRET_NAME} secret",
            )
        if status == 429:
            return _Failure("HTTP 429", rate_limited=True, retry_after=_retry_after(response))
        if status >= 500:
            return _Failure(f"HTTP {status}")
        if status >= 400:
            raise self._error(FreesoundError, f"Freesound API returned HTTP {status}")
        try:
            payload = response.json()
        except ValueError:
            payload = None
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            raise self._error(FreesoundError, "Freesound API returned an unexpected response")
        return _Page(results=results, has_next=bool(payload.get("next")))

    def _attempt_audio(self, url: str, source_id: str, max_bytes: int) -> bytes | _Failure:
        failure: _Failure | None = None
        fatal: str | None = None
        too_big = False
        status_error: int | None = None
        body = b""
        try:
            # Deliberately no Authorization header: the CDN needs no key.
            with self._http.stream("GET", url) as response:
                status = response.status_code
                if status == 429:
                    failure = _Failure(
                        "HTTP 429", rate_limited=True, retry_after=_retry_after(response)
                    )
                elif status >= 500:
                    failure = _Failure(f"HTTP {status}")
                elif status >= 400:
                    status_error = status
                else:
                    declared = response.headers.get("content-length", "")
                    if declared.isdigit() and int(declared) > max_bytes:
                        too_big = True
                    else:
                        buffer = bytearray()
                        for chunk in response.iter_bytes():
                            buffer.extend(chunk)
                            if len(buffer) > max_bytes:
                                too_big = True
                                break
                        body = bytes(buffer)
        except httpx.TimeoutException:
            failure = _Failure("timeout")
        except httpx.TransportError as exc:
            failure = _Failure(type(exc).__name__)
        except httpx.HTTPError as exc:
            fatal = type(exc).__name__
        if fatal is not None:
            raise self._error(FreesoundStreamError, f"Audio download failed: {fatal}")
        if failure is not None:
            return failure
        if status_error is not None:
            raise self._error(
                FreesoundStreamError,
                f"Audio download of track {source_id} failed with HTTP {status_error}; "
                "refresh the track with get_tracks()",
            )
        if too_big:
            raise self._error(
                FreesoundStreamError,
                f"Audio of track {source_id} is larger than the {max_bytes} byte limit",
            )
        if not body:
            raise self._error(FreesoundStreamError, f"Audio of track {source_id} is empty")
        return body

    # -- disk cache --------------------------------------------------------------------

    @staticmethod
    def _cache_key(params: Mapping[str, str]) -> str:
        # The API key is a header, so it is not part of the parameters.
        items = sorted((k, str(v)) for k, v in params.items())
        payload = json.dumps([SEARCH_URL, items], separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def _cache_path(self, key: str) -> Path | None:
        return self._cache_dir / f"{key}.json" if self._cache_dir is not None else None

    def _cache_read(self, key: str) -> _Page | None:
        path = self._cache_path(key)
        if path is None:
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            fetched_at = float(data["fetched_at"])
            results = data["results"]
            has_next = bool(data.get("has_next", False))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None
        if not isinstance(results, list) or not results:
            return None
        if self._clock() - fetched_at > self._cache_ttl_s:
            return None
        return _Page(results=results, has_next=has_next)

    def _cache_write(self, key: str, page: _Page) -> None:
        path = self._cache_path(key)
        if path is not None:
            self._write_json(
                path,
                {"fetched_at": self._clock(), "results": page.results, "has_next": page.has_next},
            )

    def _write_json(self, path: Path, data: object) -> None:
        """Atomic best-effort write; cache problems must never break a request."""
        tmp: str | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".part")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            os.replace(tmp, path)
            tmp = None
        except OSError as exc:
            logger.debug("Could not write %s: %s", path.name, type(exc).__name__)
        finally:
            if tmp is not None:
                Path(tmp).unlink(missing_ok=True)

    # -- daily usage counter -----------------------------------------------------------

    def _day(self) -> str:
        return datetime.fromtimestamp(self._clock(), tz=UTC).strftime("%Y-%m-%d")

    def _read_usage(self) -> dict[str, Any]:
        day = self._day()
        data: Any = self._mem_usage
        if self._cache_dir is not None:
            try:
                data = json.loads((self._cache_dir / USAGE_FILE).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
        if not isinstance(data, dict) or data.get("day") != day:
            return {"day": day, "requests": 0, "cache_hits": 0}

        def count(name: str) -> int:
            value = data.get(name)
            return (
                value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0
            )

        return {"day": day, "requests": count("requests"), "cache_hits": count("cache_hits")}

    def _bump_usage(self, name: str) -> dict[str, Any]:
        with self._usage_lock:
            data = self._read_usage()
            data[name] += 1
            self._mem_usage = data
            if self._cache_dir is not None:
                self._write_json(self._cache_dir / USAGE_FILE, data)
            return data

    def _count_cache_hit(self) -> None:
        self._bump_usage("cache_hits")

    def _count_request(self) -> None:
        data = self._bump_usage("requests")
        if data["requests"] > self._usage_warn_threshold and not self._usage_warned:
            self._usage_warned = True
            logger.warning(
                "Freesound API usage for %s is %d requests (the limit is about 2,000/day)",
                data["day"],
                data["requests"],
            )


def _is_freesound_https(url: str) -> bool:
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        return False
    return parts.scheme == "https" and (host == STREAM_HOST or host.endswith("." + STREAM_HOST))
