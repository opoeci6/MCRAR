"""``JobManager``: one background ingest job at a time, with an event log the API can stream.

Design
- At most one job runs (the catalog has one writer and the GPU one model): :meth:`JobManager.start`
  raises :class:`JobBusyError` while another job runs. The job runs in a daemon worker thread and
  is handed a :class:`ProgressSink`; its ``run`` callable returns the final report (an
  ``IngestReport``-like dataclass).
- A :class:`Job` keeps an append-only event list (``seq`` starts at 1) behind a
  ``threading.Condition``. Readers (the SSE route) call :meth:`Job.wait_for_events`, which blocks
  in a worker thread until new events exist, the timeout passes or the job ended. The last event
  of a job is always ``done``, ``failed`` or ``cancelled`` and is appended in the same locked step
  that sets the final status.
- Cancelling sets a flag. The pipeline has no cancel token, so :meth:`ProgressSink.on_event`
  raises the private :class:`JobCancelled` on the next progress event after the flag is set; the
  pipeline aborts, attaches its partial report to the exception and re-raises, and the job ends
  ``cancelled`` with that report. The closing ``finished`` event never raises (the pipeline emits
  it while cleaning up).
- Nothing secret is stored: callers pass parameters without secrets, and every message that
  reaches an event, a report or the error field has URLs and ``client_id`` values removed.
- The last ``keep`` finished jobs are remembered. :meth:`JobManager.close` cancels the running job
  and waits a bounded time for it.

This module never imports the ingest pipeline, so importing the API stays light.
"""

from __future__ import annotations

import logging
import re
import threading
import uuid
from collections.abc import Callable
from dataclasses import fields
from datetime import UTC, datetime
from typing import Any, Literal

log = logging.getLogger(__name__)

JobStatus = Literal["running", "done", "failed", "cancelled"]
FINAL_EVENTS = frozenset({"done", "failed", "cancelled"})
MAX_FAILURES = 50
MAX_NEW_TRACK_IDS = 200
MAX_MESSAGE_CHARS = 300
KEEP_JOBS = 20
CLOSE_TIMEOUT_S = 30.0

_URL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://\S+")
_CLIENT_ID = re.compile(r"client_id=[^&\s]+", re.IGNORECASE)


def redact(text: str) -> str:
    """``text`` without URLs and client ids, cut to a short length (safe to show and store)."""
    text = _CLIENT_ID.sub("client_id=<redacted>", text)
    text = _URL.sub("<url>", text)
    return text if len(text) <= MAX_MESSAGE_CHARS else text[: MAX_MESSAGE_CHARS - 3] + "..."


def error_text(exc: BaseException) -> str:
    """``TypeName: message`` for a job error, redacted."""
    message = redact(str(exc)).strip()
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


class JobBusyError(RuntimeError):
    """Another job is running (HTTP 409)."""


class JobNotRunningError(RuntimeError):
    """The job already ended, so it cannot be cancelled (HTTP 409)."""


class JobCancelled(Exception):  # noqa: N818 - not an error condition, an internal control signal
    """Raised from the progress callback to stop the pipeline; never leaves this module."""


def report_to_dict(report: Any) -> dict[str, Any]:
    """An ``IngestReport`` as plain JSON data; the failure list is capped at ``MAX_FAILURES`` and
    the new track ids at ``MAX_NEW_TRACK_IDS``."""
    data = {f.name: getattr(report, f.name) for f in fields(report) if f.name != "failures"}
    if "new_track_ids" in data:
        data["new_track_ids"] = list(data["new_track_ids"])[:MAX_NEW_TRACK_IDS]
    failures = list(report.failures)
    data["failures"] = [
        {
            k: redact(v) if isinstance(v, str) and k == "message" else v
            for k, v in f._asdict().items()
        }
        for f in failures[:MAX_FAILURES]
    ]
    data["failures_total"] = len(failures)
    if isinstance(data.get("aborted"), str):  # the text of the exception that stopped the run
        data["aborted"] = redact(data["aborted"])
    return data


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Job:
    """One run: parameters, status, the event log and the final report."""

    def __init__(self, kind: str, params: dict[str, Any]) -> None:
        self.id = uuid.uuid4().hex[:8]
        self.kind = kind
        self.params = dict(params)
        self.created_at = _now()
        self.finished_at: str | None = None
        self.status: JobStatus = "running"
        self.report: dict[str, Any] | None = None
        self.error: str | None = None
        self._events: list[dict[str, Any]] = []
        self._progress: dict[str, Any] | None = None
        self._cancel = threading.Event()
        self._cond = threading.Condition()

    # -- events ------------------------------------------------------------------------------

    def append(self, type_: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._cond:
            return self._append(type_, data or {})

    def _append(self, type_: str, data: dict[str, Any]) -> dict[str, Any]:
        event = {"seq": len(self._events) + 1, "type": type_, "data": data}
        self._events.append(event)
        if type_ == "progress" and data.get("kind") != "finished":
            self._progress = {"index": data.get("index"), "total": data.get("total")}
        self._cond.notify_all()
        return event

    def events_after(self, seq: int = 0) -> list[dict[str, Any]]:
        with self._cond:
            return self._events[max(seq, 0) :]

    def wait_for_events(self, after: int, timeout: float) -> tuple[list[dict[str, Any]], bool]:
        """Events with ``seq > after``, waiting up to ``timeout`` seconds if there are none yet.

        Returns ``(events, ended)``; ``ended`` is true once the job has its final event.
        """
        after = max(after, 0)
        with self._cond:
            self._cond.wait_for(
                lambda: len(self._events) > after or self.status != "running", timeout
            )
            return self._events[after:], self.status != "running"

    # -- state -------------------------------------------------------------------------------

    @property
    def cancel_requested(self) -> bool:
        return self._cancel.is_set()

    def request_cancel(self) -> None:
        self._cancel.set()

    def finish(
        self,
        status: JobStatus,
        report: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Set the final status and append the final event in one step."""
        with self._cond:
            self.status = status
            self.report = report
            self.error = error
            self.finished_at = _now()
            data: dict[str, Any] = {"report": report}
            if error is not None:
                data["error"] = error
            self._append(status, data)

    def to_dict(self, *, detail: bool = False) -> dict[str, Any]:
        """The job as JSON data: a summary, or with the final report when ``detail``."""
        with self._cond:
            data: dict[str, Any] = {
                "id": self.id,
                "kind": self.kind,
                "params": self.params,
                "status": self.status,
                "created_at": self.created_at,
                "finished_at": self.finished_at,
                "cancel_requested": self.cancel_requested,
                "error": self.error,
                "progress": self._progress,
            }
            if detail:
                data["event_count"] = len(self._events)
                data["report"] = self.report
            return data


class ProgressSink:
    """What a job's ``run`` callable reports through: pipeline events and warnings."""

    def __init__(self, job: Job) -> None:
        self._job = job

    def warning(self, message: str) -> None:
        self._job.append("warning", {"message": redact(message)})

    def on_event(self, event: Any) -> None:
        """The ``on_progress`` callback for the ingest pipeline (an ``IngestEvent``)."""
        self._job.append(
            "progress",
            {
                "kind": event.kind,
                "index": event.index,
                "total": event.total,
                "title": event.title,
                "message": None if event.message is None else redact(event.message),
            },
        )
        if event.kind != "finished" and self._job.cancel_requested:
            raise JobCancelled


class JobManager:
    def __init__(self, *, keep: int = KEEP_JOBS, close_timeout_s: float = CLOSE_TIMEOUT_S) -> None:
        self._keep = keep
        self._close_timeout_s = close_timeout_s
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}  # oldest first
        self._current: Job | None = None
        self._thread: threading.Thread | None = None
        self._closed = False

    def start(self, kind: str, params: dict[str, Any], run: Callable[[ProgressSink], Any]) -> Job:
        """Run ``run(sink)`` in a worker thread. Raises :class:`JobBusyError` if a job runs."""
        with self._lock:
            if self._closed:
                raise JobBusyError("the server is shutting down")
            if self._current is not None and self._current.status == "running":
                raise JobBusyError(f"job {self._current.id} is still running")
            job = Job(kind, params)
            self._jobs[job.id] = job
            self._current = job
            self._prune()
            thread = threading.Thread(
                target=self._work, args=(job, run), name=f"mcrar-job-{job.id}", daemon=True
            )
            self._thread = thread
        thread.start()
        return job

    def _work(self, job: Job, run: Callable[[ProgressSink], Any]) -> None:
        job.append("started", {"kind": job.kind, "params": job.params})
        try:
            report = run(ProgressSink(job))
        except JobCancelled as exc:
            partial = getattr(exc, "report", None)
            report = None if partial is None else report_to_dict(partial)
            if report is not None:
                report["aborted"] = "cancelled"  # not the internal "JobCancelled" exception text
            job.finish("cancelled", report)
        except BaseException as exc:  # noqa: BLE001 - whatever happens, the job must end
            log.warning("job %s failed (%s)", job.id, type(exc).__name__)
            partial = getattr(exc, "report", None)
            job.finish(
                "failed", None if partial is None else report_to_dict(partial), error_text(exc)
            )
        else:
            job.finish("done", None if report is None else report_to_dict(report))
        with self._lock:
            self._prune()

    def _prune(self) -> None:
        """Forget the oldest finished jobs beyond ``keep`` (the lock is held)."""
        finished = [j for j in self._jobs.values() if j.status != "running"]
        for job in finished[: max(len(finished) - self._keep, 0)]:
            del self._jobs[job.id]

    # -- queries and control -----------------------------------------------------------------

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise LookupError(f"no job with id {job_id}")
        return job

    def list(self) -> list[Job]:
        """Remembered jobs, newest first."""
        with self._lock:
            return list(reversed(self._jobs.values()))

    def running(self) -> Job | None:
        with self._lock:
            job = self._current
        return job if job is not None and job.status == "running" else None

    def cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status != "running":
            raise JobNotRunningError(f"job {job_id} already {job.status}")
        job.request_cancel()
        return job

    def close(self) -> None:
        """Stop accepting jobs, cancel the running one and wait for it (bounded)."""
        with self._lock:
            self._closed = True
            job, thread = self._current, self._thread
        if job is not None and job.status == "running":
            job.request_cancel()
        if thread is not None and thread.is_alive():
            thread.join(self._close_timeout_s)
            if thread.is_alive():
                log.warning(
                    "job %s did not stop within %.0f s",
                    job.id if job else "?",
                    self._close_timeout_s,
                )
