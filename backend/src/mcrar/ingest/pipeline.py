"""The ingest pipeline: metadata upsert, then per-track stages on the track's audio.

Design
- Metadata is always upserted (it refreshes licences and expiring stream URLs). Stages (analysis
  today, embeddings in M3a) are skipped per track when ``Stage.is_current`` says so, unless
  ``force``. Audio is obtained at most once per track, and not at all when every stage is
  current.
- Jamendo audio is downloaded by a small thread pool up to ``PREFETCH`` tracks ahead of the one
  being analysed, held in memory only. Analysis and every database write stay on the calling
  thread.
- Per-track failures are logged (``ingest_log``) and the run goes on. Auth and rate-limit errors
  (and a failing search) abort the run: the exception is re-raised after cleanup, with the
  partial :class:`IngestReport` attached as its ``report`` attribute. Ctrl+C returns the partial
  report with ``aborted="interrupted"``. Each stage write is atomic, so a rerun resumes.
- :func:`reprocess_catalog` runs stages over tracks already in the catalog (for example to add
  an embedding model) with the same prefetching, logging and abort rules. Jamendo stream URLs
  are signed and expire, so they are refreshed from the API just before each download.
- A stage with ``needs_audio = False`` (for example tagging from a stored embedding) runs on
  what earlier stages stored and gets ``audio=None``. Audio is fetched (and Jamendo URLs are
  refreshed) only when some pending stage needs it. Stages run in list order, so such a stage
  can follow the stage that produces its input in the same pass.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Literal, NamedTuple, Protocol

from mcrar.audio import ANALYSIS_VERSION, analyze_audio, load_audio
from mcrar.catalog import CatalogRepository, StoredTrack
from mcrar.ingest.mapping import to_track_record
from mcrar.licensing import LicenseInfo, parse_license
from mcrar.ml.embedders.base import Embedder, embed_track
from mcrar.ml.errors import EmbedderMemoryError
from mcrar.sources import JamendoAuthError, JamendoRateLimitError, SourceTrack
from mcrar.sources.local_folder import iter_audio_files, scan_local

logger = logging.getLogger(__name__)

PREFETCH = 2  # tracks downloaded ahead of the one being analysed
FETCH_WORKERS = 2
MAX_MESSAGE_CHARS = 200
UP_TO_DATE = "up to date"
NO_STREAM = "no audio stream"
INTERRUPTED = "interrupted"
REFRESH_BATCH = 50  # Jamendo tracks whose stream URLs are refreshed with one API request
# Errors that end the run instead of failing one track: they would hit every following track.
_ABORT_ERRORS = (JamendoAuthError, JamendoRateLimitError, EmbedderMemoryError)
_POLL_S = 0.25

Audio = bytes | Path
EventKind = Literal["started", "track_done", "track_skipped", "track_failed", "finished"]


# --------------------------------------------------------------------------------------
# Stages
# --------------------------------------------------------------------------------------


class Stage(Protocol):
    """One unit of per-track work (analysis, embedding, tagging, ...).

    Stages may also define ``needs_audio: bool``; it defaults to True when absent (see
    :func:`needs_audio`). A stage with ``needs_audio = False`` is called with ``audio=None``.
    """

    name: str
    version: str

    def is_current(self, repo: CatalogRepository, track_id: int) -> bool: ...

    def run(self, repo: CatalogRepository, track_id: int, audio: Audio | None) -> None: ...


def needs_audio(stage: Stage) -> bool:
    """Whether ``stage`` reads the track's audio (stages without the attribute do)."""
    return bool(getattr(stage, "needs_audio", True))


class AnalysisStage:
    """DSP features (BPM, key, loudness, energy) via :func:`mcrar.audio.analyze_audio`."""

    name = "analysis"
    version = ANALYSIS_VERSION

    def __init__(
        self,
        analyzer: Callable[..., Any] | None = None,
        *,
        max_seconds: float | None = 240,
    ) -> None:
        self._analyzer = analyzer if analyzer is not None else analyze_audio
        self._max_seconds = max_seconds

    def is_current(self, repo: CatalogRepository, track_id: int) -> bool:
        return repo.features_version(track_id) == self.version

    def run(self, repo: CatalogRepository, track_id: int, audio: Audio) -> None:
        features = self._analyzer(audio, max_seconds=self._max_seconds)
        repo.set_features(track_id, features.to_dict())


class EmbeddingStage:
    """One text-audio embedding per track for one model (see :mod:`mcrar.ml.embedders`).

    Decodes the first ``max_seconds`` at the model's sample rate, embeds up to three windows
    (:func:`~mcrar.ml.embedders.embed_track`) and stores the vector under ``embedder.model_id``.
    """

    def __init__(self, embedder: Embedder, *, max_seconds: float | None = 240) -> None:
        self.embedder = embedder
        self.name = f"embed:{embedder.key}"
        self.version = embedder.model_id
        self._max_seconds = max_seconds

    def is_current(self, repo: CatalogRepository, track_id: int) -> bool:
        return repo.get_embedding(track_id, self.version) is not None

    def run(self, repo: CatalogRepository, track_id: int, audio: Audio) -> None:
        clip = load_audio(
            audio, sr=self.embedder.sample_rate, mono=True, max_seconds=self._max_seconds
        )
        vector = embed_track(self.embedder, clip.samples, clip.sr)
        repo.set_embedding(track_id, self.version, vector)


# --------------------------------------------------------------------------------------
# Public data types
# --------------------------------------------------------------------------------------


class IngestFailure(NamedTuple):
    source_id: str
    title: str
    stage: str
    message: str


@dataclass(frozen=True)
class IngestReport:
    """Totals of one run. ``seen`` counts tracks pulled from the source; on an aborted run it
    can include tracks prefetched but not yet processed. ``new_track_ids`` are the catalog ids
    of the tracks this run added (their stages may still have failed or not run)."""

    seen: int
    new: int
    updated: int
    processed: int
    skipped: int
    failed: int
    failures: list[IngestFailure]
    elapsed_s: float
    aborted: str | None = None
    new_track_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class IngestEvent:
    """Progress notification. ``total`` is None (or an upper bound) when not known up front."""

    kind: EventKind
    index: int
    total: int | None
    title: str = ""
    message: str | None = None


@dataclass(frozen=True)
class JamendoQuery:
    """Search filters for :func:`ingest_jamendo` (a plain mapping works too)."""

    tags: Sequence[str] | None = None
    fuzzytags: Sequence[str] | None = None
    search: str | None = None
    vocalinstrumental: str | None = None
    commercial_only: bool = False
    order: str | None = None
    speed: str | None = None
    boost: str | None = None
    duration_between: tuple[int, int] | None = None  # seconds, (min, max)

    def to_kwargs(self) -> dict[str, Any]:
        """The ``JamendoClient.search_tracks`` keyword arguments that are actually set."""
        return {f.name: v for f in fields(self) if (v := getattr(self, f.name))}


ProgressCallback = Callable[[IngestEvent], None]


def _message(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc)[:MAX_MESSAGE_CHARS]}"


# --------------------------------------------------------------------------------------
# Shared per-track processing
# --------------------------------------------------------------------------------------


@dataclass
class _Prepared:
    """A track whose metadata is stored and whose pending stages are known."""

    source_id: str
    title: str
    track_id: int
    risk: str
    needs: list[Stage]
    get_audio: Callable[[], Audio] | None = None
    error: str | None = None
    future: Future[bytes] | None = None
    source: str | None = None  # the track's own source when a run mixes sources


class _Run:
    """Counters, the ingest log and progress events of one run."""

    def __init__(
        self,
        source: str,
        repo: CatalogRepository,
        stages: Sequence[Stage],
        force: bool,
        total: int | None,
        on_progress: ProgressCallback | None,
    ) -> None:
        self.source = source
        self.repo = repo
        self.stages = list(stages)
        self.force = force
        self.total = total
        self._on_progress = on_progress
        self._t0 = time.monotonic()
        self.seen = self.new = self.updated = 0
        self.processed = self.skipped = self.failed = 0
        self.index = 0
        self.failures: list[IngestFailure] = []
        self.new_track_ids: list[int] = []

    def emit(self, kind: EventKind, title: str = "", message: str | None = None) -> None:
        if self._on_progress is not None:
            self._on_progress(IngestEvent(kind, self.index, self.total, title, message))

    def prepare(
        self,
        src: SourceTrack,
        lic: LicenseInfo,
        *,
        attribution_extra: str | None = None,
    ) -> _Prepared:
        """Upsert the metadata and work out which stages still have to run."""
        record = to_track_record(src, lic, attribution_extra=attribution_extra)
        existing = self.repo.get_track_by_source(src.source, src.source_id)
        track_id = self.repo.upsert_track(record)
        self.seen += 1
        if existing is None:
            self.new += 1
            self.new_track_ids.append(track_id)
        elif any(getattr(existing, f.name) != getattr(record, f.name) for f in fields(record)):
            self.updated += 1
        needs = [s for s in self.stages if self.force or not s.is_current(self.repo, track_id)]
        return _Prepared(src.source_id, src.title, track_id, lic.risk, needs)

    def prepare_stored(self, track: StoredTrack, needs: list[Stage]) -> _Prepared:
        """A track already in the catalog (its metadata is left as it is)."""
        self.seen += 1
        title = track.title or track.source_id
        return _Prepared(track.source_id, title, track.id, track.risk, needs, source=track.source)

    def count_current(self) -> None:
        """A catalog track whose stages are all current: counted, but no log row or event."""
        self.seen += 1
        self.skipped += 1

    def process(self, item: _Prepared) -> None:
        """Run the pending stages of one track. KeyboardInterrupt and abort errors propagate."""
        self.index += 1
        for stage in self.stages:
            if stage not in item.needs:
                self._log(item, stage, "skipped", UP_TO_DATE)
        if not item.needs:
            self.skipped += 1
            self.emit("track_skipped", item.title, UP_TO_DATE)
            return
        audio: Audio | None = None
        audio_error: str | None = None
        if any(needs_audio(s) for s in item.needs):
            audio_error = item.error
            if audio_error is None:
                try:
                    assert item.get_audio is not None
                    audio = item.get_audio()  # fetched once, shared by every pending stage
                except _ABORT_ERRORS:
                    raise
                except Exception as exc:  # noqa: BLE001 - one bad track must not stop the run
                    audio_error = _message(exc)
        errors: list[str] = []
        for stage in item.needs:
            error = audio_error if needs_audio(stage) else None
            if error is None:
                try:
                    stage.run(self.repo, item.track_id, audio if needs_audio(stage) else None)
                except _ABORT_ERRORS:
                    raise
                except Exception as exc:  # noqa: BLE001
                    error = _message(exc)
                else:
                    self._log(item, stage, "ok")
                    continue
            assert error is not None
            errors.append(error)
            self._log(item, stage, "failed", error)
            self.failures.append(IngestFailure(item.source_id, item.title, stage.name, error))
        if errors:
            self.failed += 1
            self.emit("track_failed", item.title, errors[0])
        else:
            self.processed += 1
            self.emit("track_done", item.title, self._summary(item))

    def _log(self, item: _Prepared, stage: Stage, status: str, message: str | None = None) -> None:
        self.repo.log_ingest(
            item.source or self.source,
            item.source_id,
            stage.name,
            status,
            message,
            track_id=item.track_id,
        )

    def _summary(self, item: _Prepared) -> str:
        features = self.repo.get_features(item.track_id) or {}
        parts: list[str] = []
        if features.get("bpm") is not None:
            parts.append(f"{features['bpm']:.0f} BPM")
        if features.get("key"):
            parts.append(f"{features['key']} {features.get('mode') or ''}".strip())
        if not parts:  # nothing analysed (for example an embedding-only run): name the stages
            parts.append(", ".join(s.name for s in item.needs))
        parts.append(f"({item.risk})")
        return " ".join(parts)

    def report(self, aborted: str | None) -> IngestReport:
        return IngestReport(
            seen=self.seen,
            new=self.new,
            updated=self.updated,
            processed=self.processed,
            skipped=self.skipped,
            failed=self.failed,
            failures=list(self.failures),
            elapsed_s=time.monotonic() - self._t0,
            aborted=aborted,
            new_track_ids=list(self.new_track_ids),
        )


def _finish(run: _Run, aborted: str | None, error: Exception | None) -> IngestReport:
    report = run.report(aborted)
    run.emit("finished", message=aborted)
    if error is not None:
        error.report = report  # type: ignore[attr-defined]
        raise error
    return report


def _default_stages(stages: Sequence[Stage] | None) -> list[Stage]:
    return list(stages) if stages is not None else [AnalysisStage()]


# --------------------------------------------------------------------------------------
# Jamendo
# --------------------------------------------------------------------------------------


def _await(future: Future[bytes]) -> bytes:
    """Wait for a download in short slices so Ctrl+C is honoured on every platform."""
    while not future.done():
        wait([future], timeout=_POLL_S)
    return future.result()


def _start_fetch(
    executor: ThreadPoolExecutor, client: Any, item: _Prepared, track: SourceTrack
) -> None:
    """Download ``track`` in the background, or mark the item failed if it has no stream."""
    if track.stream_url:
        item.future = executor.submit(client.fetch_audio, track)
        item.get_audio = lambda f=item.future: _await(f)
    else:
        item.error = NO_STREAM


def _drive(
    run: _Run, executor: ThreadPoolExecutor, make_items: Callable[[], Iterator[_Prepared]]
) -> tuple[str | None, Exception | None]:
    """Process the items of ``make_items()`` with up to ``PREFETCH`` downloads in flight.

    ``make_items`` is called inside the guarded block and is lazy: preparing an item (metadata
    upsert, starting its download) happens only when the window needs it. Returns
    ``(aborted, error)`` for :func:`_finish`; shuts the executor down.
    """
    window: deque[_Prepared] = deque()
    current: _Prepared | None = None
    aborted: str | None = None
    error: Exception | None = None
    interrupted = False

    def pull(items: Iterator[_Prepared], size: int) -> None:
        while len(window) < size:
            item = next(items, None)
            if item is None:
                return
            window.append(item)

    try:
        run.emit("started")
        items = make_items()
        pull(items, PREFETCH + 1)
        while window:
            current = window.popleft()
            pull(items, PREFETCH)
            run.process(current)
            current.future = None  # release the audio bytes
            current = None
    except KeyboardInterrupt:
        aborted = INTERRUPTED
        interrupted = True
    except Exception as exc:  # noqa: BLE001 - abort errors and a failing search/database
        aborted = _message(exc)
        error = exc
    finally:
        for item in (*window, *([current] if current is not None else [])):
            if item.future is not None:
                item.future.cancel()
        # After Ctrl+C do not block on downloads still in flight; the threads end on their own.
        executor.shutdown(wait=not interrupted, cancel_futures=True)
    return aborted, error


def ingest_jamendo(
    client: Any,
    repo: CatalogRepository,
    *,
    query: Mapping[str, Any] | JamendoQuery,
    limit: int,
    force: bool = False,
    stages: Sequence[Stage] | None = None,
    on_progress: ProgressCallback | None = None,
) -> IngestReport:
    """Ingest up to ``limit`` tracks matching ``query`` from a :class:`JamendoClient`.

    Raises ``JamendoAuthError`` / ``JamendoRateLimitError`` (or whatever the search itself
    raised) after cleanup; the partial report is available as ``exc.report``. Ctrl+C returns a
    report with ``aborted="interrupted"``.
    """
    kwargs = query.to_kwargs() if isinstance(query, JamendoQuery) else dict(query)
    run = _Run("jamendo", repo, _default_stages(stages), force, limit, on_progress)
    executor = ThreadPoolExecutor(max_workers=FETCH_WORKERS, thread_name_prefix="mcrar-fetch")

    def make_items() -> Iterator[_Prepared]:
        for src in client.search_tracks(**kwargs, limit=limit):
            item = run.prepare(src, parse_license(src.license_url))
            if any(needs_audio(s) for s in item.needs):
                _start_fetch(executor, client, item, src)
            yield item

    aborted, error = _drive(run, executor, make_items)
    return _finish(run, aborted, error)


def ingest_jamendo_queries(
    client: Any,
    repo: CatalogRepository,
    *,
    queries: Sequence[JamendoQuery],
    max_new: int,
    scan_limit: int = 200,
    force: bool = False,
    stages: Sequence[Stage] | None = None,
    on_progress: ProgressCallback | None = None,
) -> IngestReport:
    """Ingest the first ``max_new`` tracks that are not in the catalog yet from ``queries``.

    The queries run in order, each scanning up to ``scan_limit`` results, lazily: a later query
    is searched only when the earlier ones ran out before ``max_new`` was reached. A track that is
    already in the catalog, or came up in an earlier query of this run, is skipped before any
    upsert or download and does not count. The progress total is ``max_new`` (an upper bound).
    Failures, aborts and Ctrl+C behave as in :func:`ingest_jamendo`.
    """
    if max_new < 1:
        raise ValueError("max_new must be at least 1")
    run = _Run("jamendo", repo, _default_stages(stages), force, max_new, on_progress)
    executor = ThreadPoolExecutor(max_workers=FETCH_WORKERS, thread_name_prefix="mcrar-fetch")

    def make_items() -> Iterator[_Prepared]:
        taken = 0
        seen_ids: set[str] = set()
        for query in queries:
            for src in client.search_tracks(**query.to_kwargs(), limit=scan_limit):
                if src.source_id in seen_ids or repo.get_track_by_source("jamendo", src.source_id):
                    continue
                seen_ids.add(src.source_id)
                item = run.prepare(src, parse_license(src.license_url))
                if any(needs_audio(s) for s in item.needs):
                    _start_fetch(executor, client, item, src)
                yield item
                taken += 1
                if taken >= max_new:
                    return

    aborted, error = _drive(run, executor, make_items)
    return _finish(run, aborted, error)


# --------------------------------------------------------------------------------------
# Existing catalog tracks
# --------------------------------------------------------------------------------------


def _refresh_jamendo(
    client: Any, tracks: list[StoredTrack]
) -> tuple[dict[str, SourceTrack], str | None]:
    """Fresh :class:`SourceTrack` objects (with unexpired stream URLs) by source id.

    Auth and rate-limit errors propagate (they end the run); any other failure is returned as
    a message that fails the tracks of this batch.
    """
    if not tracks:
        return {}, None
    if client is None:
        return {}, "no Jamendo client to refresh the stream URL"
    try:
        found = client.get_tracks([t.source_id for t in tracks])
    except _ABORT_ERRORS:
        raise
    except Exception as exc:  # noqa: BLE001 - fail this batch, keep the run going
        return {}, _message(exc)
    return {s.source_id: s for s in found}, None


def reprocess_catalog(
    repo: CatalogRepository,
    *,
    stages: Sequence[Stage],
    client: Any = None,
    source: str | None = None,
    force: bool = False,
    limit: int | None = None,
    on_progress: ProgressCallback | None = None,
) -> IngestReport:
    """Run ``stages`` over tracks already in the catalog (optionally only those of ``source``).

    Tracks whose stages are all current are counted as skipped without a log row or event.
    ``limit`` caps the number of tracks that actually need work. Jamendo tracks need a
    ``client``: their stream URLs are refreshed with ``client.get_tracks`` in batches of
    ``REFRESH_BATCH``, just before the downloads (the stored URLs carry expiring tokens), and
    audio is downloaded by the same prefetching pool as :func:`ingest_jamendo`. Local tracks
    are read from their stored ``local_path``. Failures, aborts and Ctrl+C behave as in
    :func:`ingest_jamendo`.
    """
    stage_list = list(stages)
    if not stage_list:
        raise ValueError("reprocess_catalog needs at least one stage")
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1")
    run = _Run("catalog", repo, stage_list, force, None, on_progress)
    executor = ThreadPoolExecutor(max_workers=FETCH_WORKERS, thread_name_prefix="mcrar-fetch")

    def attach_audio(
        item: _Prepared, track: StoredTrack, fresh: dict[str, SourceTrack], problem: str | None
    ) -> None:
        if track.source == "jamendo":
            if problem is not None:
                item.error = problem
            elif track.source_id not in fresh:
                item.error = "track no longer available from Jamendo"
            else:
                _start_fetch(executor, client, item, fresh[track.source_id])
        elif track.source == "local" and track.local_path:
            item.get_audio = lambda p=Path(track.local_path): p
        elif track.source == "local":
            item.error = "no file path stored for this track"
        else:
            item.error = f"cannot read audio of a '{track.source}' track"

    def make_items() -> Iterator[_Prepared]:
        pending: list[tuple[StoredTrack, list[Stage]]] = []
        for track in repo.iter_tracks(source):
            needs = [s for s in stage_list if force or not s.is_current(repo, track.id)]
            if needs:
                pending.append((track, needs))
            else:
                run.count_current()
        if limit is not None:
            pending = pending[:limit]
        run.total = len(pending)
        for start in range(0, len(pending), REFRESH_BATCH):
            batch = pending[start : start + REFRESH_BATCH]
            # Only tracks with a pending audio stage need a (refreshed) stream URL and a download.
            jamendo = [
                t for t, n in batch if t.source == "jamendo" and any(needs_audio(s) for s in n)
            ]
            fresh, problem = _refresh_jamendo(client, jamendo) if jamendo else ({}, None)
            for track, needs in batch:
                item = run.prepare_stored(track, needs)
                if any(needs_audio(s) for s in needs):
                    attach_audio(item, track, fresh, problem)
                yield item

    aborted, error = _drive(run, executor, make_items)
    return _finish(run, aborted, error)


# --------------------------------------------------------------------------------------
# Local folder
# --------------------------------------------------------------------------------------


def ingest_local(
    root: str | Path,
    repo: CatalogRepository,
    *,
    license_override: str | None = None,
    force: bool = False,
    stages: Sequence[Stage] | None = None,
    on_progress: ProgressCallback | None = None,
) -> IngestReport:
    """Ingest every audio file under ``root`` (see :func:`mcrar.sources.scan_local`)."""
    items = scan_local(root, license_override=license_override)  # validates eagerly
    total = sum(1 for _ in iter_audio_files(Path(root).resolve()))
    run = _Run("local", repo, _default_stages(stages), force, total, on_progress)
    aborted: str | None = None
    error: Exception | None = None
    try:
        run.emit("started")
        for local in items:
            item = run.prepare(
                local.source_track, local.license, attribution_extra=local.attribution_extra
            )
            item.get_audio = lambda p=local.path: p
            run.process(item)
    except KeyboardInterrupt:
        aborted = INTERRUPTED
    except Exception as exc:  # noqa: BLE001 - a failing scan or database
        aborted = _message(exc)
        error = exc
    return _finish(run, aborted, error)
