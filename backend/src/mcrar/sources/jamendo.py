"""Jamendo API client: track search, lookup by id and in-memory audio fetching.

Design notes
- The Jamendo API is flaky (timeouts, 5xx/429, and sometimes an empty page for a query that
  has results a few seconds later), so every request is retried with exponential backoff and
  the first page of a query is retried (up to ``empty_retries`` times, with doubling backoff)
  when it comes back empty: live, one retry 2 s later was observed to still be empty.
- The client id is a secret. It is sent as the ``client_id`` query parameter, which means that
  httpx exceptions and ``Response.url`` contain it. Nothing from httpx is ever surfaced as is:
  failures are re-raised as ``JamendoError`` with a redacted, URL-free message, outside of any
  ``except`` block so no exception chain keeps the original around. Cache keys, cache file
  names and the usage file never include the client id.
- Only JSON API responses are cached on disk. Audio is streamed into memory and never written.
- ``stream_url`` values carry a signed token and may expire: use :meth:`JamendoClient.get_tracks`
  to refresh them (it bypasses the cache by default for that reason).
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar
from urllib.parse import quote, quote_plus

import httpx

from mcrar.sources.base import SourceTrack

if TYPE_CHECKING:
    from mcrar.config import Settings
    from mcrar.secrets import SecretStore

logger = logging.getLogger(__name__)

SOURCE_NAME = "jamendo"
SECRET_NAME = "jamendo_client_id"
API_URL = "https://api.jamendo.com/v3.0/tracks/"
MAX_PAGE_SIZE = 200
USAGE_FILE = "usage.json"
USAGE_WARN_THRESHOLD = 30_000
DEFAULT_CACHE_TTL_S = 7 * 24 * 3600
_REDACTED = "***"
_CLIENT_ID_PARAM_RE = re.compile(r"(client_id=)[^&\s'\"]+", re.IGNORECASE)

T = TypeVar("T")


class JamendoError(RuntimeError):
    """A Jamendo request failed. Messages never contain the client id."""


class JamendoAuthError(JamendoError):
    """The client id was rejected (API error mentioning it, or HTTP 401/403 from the API)."""


class JamendoRateLimitError(JamendoError):
    """Still rate limited (HTTP 429 or an API rate-limit error) after all retries."""


class JamendoStreamError(JamendoError):
    """The audio stream could not be fetched (the signed stream URL may have expired)."""


# --------------------------------------------------------------------------------------
# Mapping JSON -> SourceTrack
# --------------------------------------------------------------------------------------


def _str(value: object) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


def _unescaped(value: object) -> str | None:
    """Like ``_str`` for display names: the API sends HTML entities (``Jazyus &amp; EdSeGaMe``)."""
    text = _str(value)
    return _str(html.unescape(text)) if text is not None else None


def _to_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes"):
            return True
        if lowered in ("false", "0", "no"):
            return False
    if isinstance(value, int):
        return bool(value)
    return None


def _to_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _str(item)) is not None]


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def parse_track(data: Mapping[str, Any]) -> SourceTrack | None:
    """Map one Jamendo track object to a :class:`SourceTrack`; None if it has no id."""
    source_id = _str(data.get("id"))
    if source_id is None:
        return None
    musicinfo = _mapping(data.get("musicinfo"))
    licenses = _mapping(data.get("licenses"))
    mtags = _mapping(musicinfo.get("tags"))

    allowed = _to_bool(data.get("audiodownload_allowed")) is True
    download_url = _str(data.get("audiodownload")) if allowed else None
    prolicensing = _to_bool(licenses.get("prolicensing")) is True
    vocal = _str(musicinfo.get("vocalinstrumental"))
    if vocal is not None:
        vocal = vocal.lower()
        if vocal not in ("vocal", "instrumental"):
            vocal = None

    tags: dict[str, object] = {
        "genres": _str_list(mtags.get("genres")),
        "instruments": _str_list(mtags.get("instruments")),
        "vartags": _str_list(mtags.get("vartags")),
        "speed": _str(musicinfo.get("speed")),
        "acousticelectric": _str(musicinfo.get("acousticelectric")),
        "gender": _str(musicinfo.get("gender")),
        "lang": _str(musicinfo.get("lang")),
        "content_id_free": _to_bool(data.get("content_id_free")),
        "probackground": _to_bool(licenses.get("probackground")),
    }
    return SourceTrack(
        source=SOURCE_NAME,
        source_id=source_id,
        title=_unescaped(data.get("name")) or "",
        artist=_unescaped(data.get("artist_name")) or "",
        album=_unescaped(data.get("album_name")),
        duration_s=_to_float(data.get("duration")),
        release_date=_str(data.get("releasedate")),
        source_url=_str(data.get("shareurl")) or _str(data.get("shorturl")),
        stream_url=_str(data.get("audio")),
        download_url=download_url,
        audiodownload_allowed=allowed,
        license_url=_str(data.get("license_ccurl")),
        commercial_license_url=_str(data.get("prourl")) if prolicensing else None,
        image_url=_str(data.get("image")) or _str(data.get("album_image")),
        vocal_instrumental=vocal,
        tags=tags,
    )


# --------------------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------------------


class _RedactingFilter(logging.Filter):
    """Scrubs the client id from records of the ``httpx`` logger, which logs full URLs."""

    def __init__(self, redact: Callable[[str], str]) -> None:
        super().__init__()
        self._redact = redact

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - never break logging
            return True
        redacted = self._redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True


class _Failure:
    """A transient failure of one attempt (the caller decides whether to retry)."""

    def __init__(self, reason: str, *, rate_limited: bool = False) -> None:
        self.reason = reason
        self.rate_limited = rate_limited


def _join(value: str | Sequence[str]) -> str:
    if isinstance(value, str):
        return " ".join(value.split())
    return " ".join(str(v).strip() for v in value if str(v).strip())


class JamendoClient:
    def __init__(
        self,
        client_id: str,
        *,
        cache_dir: Path | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
        max_attempts: int = 3,
        min_interval_s: float = 0.5,
        cache_ttl_s: float = DEFAULT_CACHE_TTL_S,
        use_cache: bool = True,
        backoff_s: float = 1.0,
        empty_retry_backoff_s: float = 2.0,
        empty_retries: int = 3,
        usage_warn_threshold: int = USAGE_WARN_THRESHOLD,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not isinstance(client_id, str) or not client_id.strip():
            raise ValueError("A non-empty Jamendo client id is required")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._client_id = client_id.strip()
        self._cache_dir = Path(cache_dir) if cache_dir is not None else None
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._min_interval_s = min_interval_s
        self._cache_ttl_s = cache_ttl_s
        self.use_cache = use_cache
        self._backoff_s = backoff_s
        self._empty_retry_backoff_s = empty_retry_backoff_s
        self._empty_retries = empty_retries
        self._usage_warn_threshold = usage_warn_threshold
        self._clock = clock
        self._sleep = sleep
        self._last_request_at: float | None = None
        self._usage_lock = threading.Lock()
        self._mem_usage: dict[str, Any] = {}
        self._usage_warned = False
        self._http = httpx.Client(
            transport=transport,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "mcrar/0.1 (jamendo client)"},
        )
        # httpx logs "HTTP Request: GET <full url>" at INFO, and our URL carries client_id.
        self._log_filter = _RedactingFilter(self._redact)
        logging.getLogger("httpx").addFilter(self._log_filter)

    def __repr__(self) -> str:
        return f"JamendoClient(cache_dir={self._cache_dir!r})"

    # -- construction / lifecycle ------------------------------------------------------

    @classmethod
    def from_settings(
        cls,
        settings: Settings | None = None,
        secret_store: SecretStore | None = None,
        **kwargs: Any,
    ) -> JamendoClient:
        """Build a client from the stored ``jamendo_client_id`` secret and ``cache_dir``."""
        from mcrar.config import get_settings  # noqa: PLC0415
        from mcrar.secrets import SecretStore  # noqa: PLC0415

        settings = settings or get_settings()
        store = secret_store or SecretStore(settings)
        client_id = store.get(SECRET_NAME)
        if not client_id:
            raise JamendoError(
                "No Jamendo client id is configured. Get a free one at "
                "https://devportal.jamendo.com and store it with: "
                f"mcrar secrets set {SECRET_NAME}"
            )
        kwargs.setdefault("cache_dir", settings.cache_dir / "jamendo")
        return cls(client_id, **kwargs)

    def close(self) -> None:
        self._http.close()
        logging.getLogger("httpx").removeFilter(self._log_filter)

    def __enter__(self) -> JamendoClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- redaction ---------------------------------------------------------------------

    def _redact(self, text: str) -> str:
        variants = {self._client_id, quote(self._client_id, safe=""), quote_plus(self._client_id)}
        for variant in variants:
            text = text.replace(variant, _REDACTED)
        return _CLIENT_ID_PARAM_RE.sub(r"\1" + _REDACTED, text)

    def _error(self, cls: type[JamendoError], message: str) -> JamendoError:
        return cls(self._redact(message))

    # -- public API --------------------------------------------------------------------

    def search_tracks(
        self,
        *,
        tags: str | Sequence[str] | None = None,
        fuzzytags: str | Sequence[str] | None = None,
        search: str | None = None,
        vocalinstrumental: str | None = None,
        speed: str | None = None,
        duration_between: tuple[int, int] | str | None = None,
        commercial_only: bool = False,
        order: str | None = None,
        boost: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Iterator[SourceTrack]:
        """Lazily yield up to ``limit`` tracks, fetching pages of up to 200 as needed.

        ``tags`` must all match (AND), ``fuzzytags`` match any (OR); lists are joined with
        spaces (sent as ``+``). ``commercial_only`` asks the server for tracks whose licence
        allows commercial use and modification (``ccnc=false&ccnd=false``); this is only a
        prefilter, licences still need parsing. Network errors surface when the iterator is
        consumed.
        """
        if limit < 0 or offset < 0:
            raise ValueError("limit and offset must not be negative")
        params: dict[str, str] = {}
        if tags:
            params["tags"] = _join(tags)
        if fuzzytags:
            params["fuzzytags"] = _join(fuzzytags)
        if search:
            params["search"] = search
        if vocalinstrumental:
            params["vocalinstrumental"] = vocalinstrumental
        if speed:
            params["speed"] = speed
        if duration_between:
            if isinstance(duration_between, str):
                params["durationbetween"] = duration_between
            else:
                low, high = duration_between
                params["durationbetween"] = f"{low}_{high}"
        if commercial_only:
            params["ccnc"] = "false"
            params["ccnd"] = "false"
        if order:
            params["order"] = order
        if boost:
            params["boost"] = boost
        return self._iter_search(params, limit, offset)

    def get_tracks(self, ids: Sequence[str | int], *, use_cache: bool = False) -> list[SourceTrack]:
        """Fetch tracks by id (batches of up to 200), in the order requested.

        Unknown ids are simply absent from the result. The cache is bypassed by default
        because the main use is refreshing expired stream URLs.
        """
        unique = list(dict.fromkeys(str(i).strip() for i in ids if str(i).strip()))
        by_id: dict[str, SourceTrack] = {}
        for start in range(0, len(unique), MAX_PAGE_SIZE):
            batch = unique[start : start + MAX_PAGE_SIZE]
            params = {"id": " ".join(batch), "limit": str(len(batch))}
            results = self._get_page(params, first_page=start == 0, use_cache=use_cache)
            for item in results:
                track = parse_track(item) if isinstance(item, Mapping) else None
                if track is not None:
                    by_id[track.source_id] = track
        return [by_id[i] for i in unique if i in by_id]

    def fetch_audio(self, track: SourceTrack, *, max_bytes: int = 40_000_000) -> bytes:
        """Download the track's stream into memory (never to disk), at most ``max_bytes``."""
        url = track.stream_url
        if not url:
            raise self._error(
                JamendoError,
                f"Track {track.source_id} has no stream_url; refresh it with get_tracks()",
            )
        if not url.lower().startswith(("http://", "https://")):
            raise self._error(JamendoError, f"Track {track.source_id} has an invalid stream_url")
        what = f"audio download of track {track.source_id}"
        return self._retrying(what, lambda: self._attempt_audio(url, track.source_id, max_bytes))

    def usage(self) -> dict[str, Any]:
        """``{"month": "YYYY-MM", "requests": n}``: real API requests made this month."""
        with self._usage_lock:
            return dict(self._read_usage())

    # -- search / paging ---------------------------------------------------------------

    @staticmethod
    def _base_params() -> dict[str, str]:
        return {"format": "json", "include": "musicinfo licenses", "audioformat": "mp32"}

    def _iter_search(
        self, params: dict[str, str], limit: int, offset: int
    ) -> Iterator[SourceTrack]:
        fetched = 0
        first = True
        while fetched < limit:
            size = min(MAX_PAGE_SIZE, limit - fetched)
            page_params = {**params, "limit": str(size), "offset": str(offset + fetched)}
            results = self._get_page(page_params, first_page=first, use_cache=self.use_cache)
            first = False
            for item in results[:size]:
                track = parse_track(item) if isinstance(item, Mapping) else None
                if track is not None:
                    yield track
            if len(results) < size:
                return
            fetched += size

    def _get_page(self, params: dict[str, str], *, first_page: bool, use_cache: bool) -> list[Any]:
        full = {**self._base_params(), **params}
        results = self._get_results(full, use_cache)
        delay = self._empty_retry_backoff_s
        for attempt in range(1, self._empty_retries + 1):
            if results or not first_page:
                break
            logger.info(
                "Jamendo returned an empty first page; retry %d/%d in %.1fs",
                attempt,
                self._empty_retries,
                delay,
            )
            self._sleep(delay)
            delay *= 2
            results = self._get_results(full, use_cache)
        return results

    def _get_results(self, params: dict[str, str], use_cache: bool) -> list[Any]:
        key = self._cache_key(params)
        if use_cache:
            cached = self._cache_read(key)
            if cached is not None:
                logger.debug("Jamendo cache hit %s", key[:12])
                return cached
        results = self._retrying("Jamendo API request", lambda: self._attempt_api(params))
        if use_cache and results:
            self._cache_write(key, results)
        return results

    # -- retry machinery ---------------------------------------------------------------

    def _retrying(self, what: str, attempt: Callable[[], T | _Failure]) -> T:
        last: _Failure | None = None
        for n in range(1, self._max_attempts + 1):
            result = attempt()
            if not isinstance(result, _Failure):
                return result
            last = result
            if n < self._max_attempts:
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
        cls = JamendoRateLimitError if last.rate_limited else JamendoError
        raise self._error(cls, f"{what} failed after {self._max_attempts} attempts: {last.reason}")

    def _throttle(self) -> None:
        if self._last_request_at is not None and self._min_interval_s > 0:
            wait = self._min_interval_s - (self._clock() - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
        self._last_request_at = self._clock()

    def _attempt_api(self, params: dict[str, str]) -> list[Any] | _Failure:
        self._throttle()
        self._count_request()
        failure: _Failure | None = None
        fatal: str | None = None
        response: httpx.Response | None = None
        try:
            response = self._http.get(API_URL, params={**params, "client_id": self._client_id})
        except httpx.TimeoutException:
            failure = _Failure("timeout")
        except httpx.TransportError as exc:
            failure = _Failure(type(exc).__name__)
        except httpx.HTTPError as exc:
            fatal = type(exc).__name__
        # Everything below runs outside the except blocks so no httpx exception (whose text
        # contains the full URL) stays attached to the exceptions raised here.
        if fatal is not None:
            raise self._error(JamendoError, f"Jamendo API request failed: {fatal}")
        if failure is not None or response is None:
            return failure or _Failure("no response")
        return self._interpret(response)

    def _interpret(self, response: httpx.Response) -> list[Any] | _Failure:
        status = response.status_code
        if status in (401, 403):
            raise self._error(
                JamendoAuthError,
                f"Jamendo rejected the request (HTTP {status}); check the stored "
                f"{SECRET_NAME} secret",
            )
        if status == 429:
            return _Failure("HTTP 429", rate_limited=True)
        if status >= 500:
            return _Failure(f"HTTP {status}")
        try:
            payload = response.json()
        except ValueError:
            payload = None
        headers = payload.get("headers") if isinstance(payload, dict) else None
        if not isinstance(headers, dict):
            if status >= 400:
                raise self._error(JamendoError, f"Jamendo API returned HTTP {status}")
            raise self._error(JamendoError, "Jamendo API returned an unexpected response")
        code = headers.get("code")
        failed = str(code) not in ("0", "None") or str(headers.get("status", "success")) != (
            "success"
        )
        if failed:
            message = str(headers.get("error_message") or "").strip()
            lowered = message.lower()
            detail = f"Jamendo API error (code {code})" + (f": {message}" if message else "")
            if "client_id" in lowered or "client id" in lowered or "clientid" in lowered:
                raise self._error(JamendoAuthError, detail)
            if "rate limit" in lowered or "too many" in lowered:
                return _Failure(detail, rate_limited=True)
            raise self._error(JamendoError, detail)
        results = payload.get("results")
        if not isinstance(results, list):
            raise self._error(JamendoError, "Jamendo API response has no results list")
        return results

    def _attempt_audio(self, url: str, source_id: str, max_bytes: int) -> bytes | _Failure:
        failure: _Failure | None = None
        fatal: str | None = None
        too_big = False
        status_error: int | None = None
        body = b""
        try:
            with self._http.stream("GET", url) as response:
                status = response.status_code
                if status == 429:
                    failure = _Failure("HTTP 429", rate_limited=True)
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
            raise self._error(JamendoStreamError, f"Audio download failed: {fatal}")
        if failure is not None:
            return failure
        if status_error is not None:
            raise self._error(
                JamendoStreamError,
                f"Audio download of track {source_id} failed with HTTP {status_error}; the "
                "stream URL may have expired, refresh it with get_tracks()",
            )
        if too_big:
            raise self._error(
                JamendoStreamError,
                f"Audio of track {source_id} is larger than the {max_bytes} byte limit",
            )
        if not body:
            raise self._error(JamendoStreamError, f"Audio of track {source_id} is empty")
        return body

    # -- disk cache --------------------------------------------------------------------

    @staticmethod
    def _cache_key(params: Mapping[str, str]) -> str:
        items = sorted((k, str(v)) for k, v in params.items() if k != "client_id")
        return hashlib.sha256(json.dumps(items, separators=(",", ":")).encode()).hexdigest()

    def _cache_path(self, key: str) -> Path | None:
        return self._cache_dir / f"{key}.json" if self._cache_dir is not None else None

    def _cache_read(self, key: str) -> list[Any] | None:
        path = self._cache_path(key)
        if path is None:
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            fetched_at = float(data["fetched_at"])
            results = data["results"]
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if not isinstance(results, list) or not results:
            return None
        if self._clock() - fetched_at > self._cache_ttl_s:
            return None
        return results

    def _cache_write(self, key: str, results: list[Any]) -> None:
        path = self._cache_path(key)
        if path is not None:
            self._write_json(path, {"fetched_at": self._clock(), "results": results})

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

    # -- monthly usage counter ---------------------------------------------------------

    def _month(self) -> str:
        return datetime.fromtimestamp(self._clock(), tz=UTC).strftime("%Y-%m")

    def _read_usage(self) -> dict[str, Any]:
        month = self._month()
        data: Any = self._mem_usage
        if self._cache_dir is not None:
            try:
                data = json.loads((self._cache_dir / USAGE_FILE).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
        if (
            isinstance(data, dict)
            and data.get("month") == month
            and isinstance(data.get("requests"), int)
            and data["requests"] >= 0
        ):
            return {"month": month, "requests": data["requests"]}
        return {"month": month, "requests": 0}

    def _count_request(self) -> None:
        with self._usage_lock:
            data = self._read_usage()
            data["requests"] += 1
            self._mem_usage = data
            if self._cache_dir is not None:
                self._write_json(self._cache_dir / USAGE_FILE, data)
            if data["requests"] > self._usage_warn_threshold and not self._usage_warned:
                self._usage_warned = True
                logger.warning(
                    "Jamendo API usage for %s is %d requests (free tier is about 35,000/month)",
                    data["month"],
                    data["requests"],
                )
