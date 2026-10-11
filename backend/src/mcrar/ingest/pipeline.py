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
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Literal, NamedTuple, Protocol

from mcrar.audio import ANALYSIS_VERSION, analyze_audio
from mcrar.catalog import CatalogRepository
from mcrar.ingest.mapping import to_track_record
from mcrar.licensing import LicenseInfo, parse_license
from mcrar.sources import JamendoAuthError, JamendoRateLimitError, SourceTrack
from mcrar.sources.local_folder import iter_audio_files, scan_local

logger = logging.getLogger(__name__)

PREFETCH = 2  # tracks downloaded ahead of the one being analysed
FETCH_WORKERS = 2
MAX_MESSAGE_CHARS = 200
UP_TO_DATE = "up to date"
NO_STREAM = "no audio stream"
INTERRUPTED = "interrupted"
_ABORT_ERRORS = (JamendoAuthError, JamendoRateLimitError)
_POLL_S = 0.25

Audio = bytes | Path
EventKind = Literal["started", "track_done", "track_skipped", "track_failed", "finished"]


# --------------------------------------------------------------------------------------
# Stages
# --------------------------------------------------------------------------------------


class Stage(Protocol):
    """One unit of per-track work on the audio (analysis, embedding, ...)."""

    name: str
    version: str

    def is_current(self, repo: CatalogRepository, track_id: int) -> bool: ...

    def run(self, repo: CatalogRepository, track_id: int, audio: Audio) -> None: ...


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
    can include tracks prefetched but not yet processed."""

    seen: int
    new: int
    updated: int
    processed: int
    skipped: int
    failed: int
    failures: list[IngestFailure]
    elapsed_s: float
    aborted: str | None = None


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
        elif any(getattr(existing, f.name) != getattr(record, f.name) for f in fields(record)):
            self.updated += 1
        needs = [s for s in self.stages if self.force or not s.is_current(self.repo, track_id)]
        return _Prepared(src.source_id, src.title, track_id, lic.risk, needs)

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
            error = audio_error
            if audio is not None:
                try:
                    stage.run(self.repo, item.track_id, audio)
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
            self.source, item.source_id, stage.name, status, message, track_id=item.track_id
        )

    def _summary(self, item: _Prepared) -> str:
        features = self.repo.get_features(item.track_id) or {}
        parts: list[str] = []
        if features.get("bpm") is not None:
            parts.append(f"{features['bpm']:.0f} BPM")
        if features.get("key"):
            parts.append(f"{features['key']} {features.get('mode') or ''}".strip())
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
    window: deque[_Prepared] = deque()
    current: _Prepared | None = None
    aborted: str | None = None
    error: Exception | None = None
    interrupted = False

    def pull(source: Iterator[SourceTrack], size: int) -> None:
        while len(window) < size:
            src = next(source, None)
            if src is None:
                return
            item = run.prepare(src, parse_license(src.license_url))
            if item.needs:
                if src.stream_url:
                    item.future = executor.submit(client.fetch_audio, src)
                    item.get_audio = lambda f=item.future: _await(f)
                else:
                    item.error = NO_STREAM
            window.append(item)

    try:
        run.emit("started")
        source = iter(client.search_tracks(**kwargs, limit=limit))
        pull(source, PREFETCH + 1)
        while window:
            current = window.popleft()
            pull(source, PREFETCH)
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
