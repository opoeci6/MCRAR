"""``JobManager``: one job at a time, events, cancelling, failures and history."""

from __future__ import annotations

import threading
from collections.abc import Callable

import pytest

from mcrar.api.jobs import (
    MAX_FAILURES,
    Job,
    JobBusyError,
    JobCancelled,
    JobManager,
    JobNotRunningError,
    ProgressSink,
    error_text,
    redact,
    report_to_dict,
)
from mcrar.ingest.pipeline import IngestEvent, IngestFailure, IngestReport

TIMEOUT_S = 20.0


def report(**changes: object) -> IngestReport:
    base: dict[str, object] = {
        "seen": 2, "new": 2, "updated": 0, "processed": 2, "skipped": 0, "failed": 0,
        "failures": [], "elapsed_s": 0.5,
    }  # fmt: skip
    return IngestReport(**{**base, **changes})  # type: ignore[arg-type]


def wait_ended(job: Job) -> Job:
    seen, ended = 0, False
    while not ended:
        events, ended = job.wait_for_events(seen, TIMEOUT_S)
        seen += len(events)
        assert events or ended, "timed out waiting for the job"
    return job


def pipeline_like(
    sink: ProgressSink, *, between: Callable[[], None] = lambda: None, tracks: int = 3
) -> IngestReport:
    """Behaves like the ingest driver: events, abort on an exception from the callback, and the
    ``finished`` event on the way out with the partial report attached to the exception."""
    done = 0
    try:
        sink.on_event(IngestEvent("started", 0, tracks))
        for n in range(1, tracks + 1):
            between()
            done = n
            sink.on_event(IngestEvent("track_done", n, tracks, f"t{n}", "ok"))
    except Exception as exc:
        partial = report(seen=done, new=done, processed=done)
        sink.on_event(IngestEvent("finished", done, tracks, "", str(exc)))  # must not raise
        exc.report = partial  # type: ignore[attr-defined]
        raise
    sink.on_event(IngestEvent("finished", done, tracks))
    return report(seen=done, new=done, processed=done)


def test_a_job_runs_and_records_ordered_events_and_the_report() -> None:
    manager = JobManager()
    job = manager.start("ingest-local", {"path": "/x"}, lambda sink: pipeline_like(sink))
    wait_ended(job)
    assert job.status == "done" and job.error is None
    events = job.events_after(0)
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    types = [e["type"] for e in events]
    assert types[0] == "started" and types[-1] == "done"
    assert types.count("progress") == 5  # started, 3 tracks, finished
    assert events[-1]["data"]["report"]["processed"] == 3
    detail = job.to_dict(detail=True)
    assert detail["report"]["processed"] == 3 and detail["params"] == {"path": "/x"}
    assert detail["finished_at"] is not None and len(job.id) == 8


def test_replay_after_a_sequence_number() -> None:
    manager = JobManager()
    job = wait_ended(manager.start("k", {}, lambda sink: pipeline_like(sink)))
    all_events = job.events_after(0)
    assert job.events_after(2) == all_events[2:]
    assert job.events_after(len(all_events)) == []


def test_wait_for_events_times_out_when_idle_and_wakes_on_news() -> None:
    job = Job("k", {})
    assert job.wait_for_events(0, 0.01) == ([], False)
    timer = threading.Timer(0.05, lambda: job.append("warning", {"message": "m"}))
    timer.start()
    events, ended = job.wait_for_events(0, TIMEOUT_S)
    timer.join()
    assert [e["type"] for e in events] == ["warning"] and not ended


def test_a_second_job_while_one_runs_is_refused() -> None:
    manager = JobManager()
    release = threading.Event()
    first = manager.start("a", {}, lambda sink: release.wait(TIMEOUT_S) and report())
    try:
        with pytest.raises(JobBusyError):
            manager.start("b", {}, lambda sink: report())
        assert manager.running() is first
    finally:
        release.set()
    wait_ended(first)
    assert manager.running() is None
    wait_ended(manager.start("b", {}, lambda sink: report()))  # free again


def test_cancelling_stops_at_the_next_event_and_keeps_the_partial_report() -> None:
    manager = JobManager()
    in_second_track = threading.Event()
    go = threading.Event()
    count = 0

    def between() -> None:
        nonlocal count
        count += 1
        if count == 2:
            in_second_track.set()
            assert go.wait(TIMEOUT_S)

    job = manager.start("k", {}, lambda sink: pipeline_like(sink, between=between, tracks=5))
    assert in_second_track.wait(TIMEOUT_S)
    assert manager.cancel(job.id) is job
    assert job.cancel_requested
    go.set()
    wait_ended(job)
    assert job.status == "cancelled"
    assert job.report is not None and job.report["processed"] == 2
    events = job.events_after(0)
    assert events[-1]["type"] == "cancelled" and events[-1]["data"]["report"]["processed"] == 2
    kinds = [e["data"]["kind"] for e in events if e["type"] == "progress"]
    assert kinds[-1] == "finished" and kinds.count("track_done") == 2
    with pytest.raises(JobNotRunningError):
        manager.cancel(job.id)


def test_the_finished_event_never_cancels_the_job() -> None:
    job = Job("k", {})
    sink = ProgressSink(job)
    job.request_cancel()
    sink.on_event(IngestEvent("finished", 3, 3))  # does not raise
    with pytest.raises(JobCancelled):
        sink.on_event(IngestEvent("track_done", 1, 3, "t", "ok"))


def test_a_cancel_that_comes_too_late_still_ends_done() -> None:
    manager = JobManager()
    at_end = threading.Event()
    go = threading.Event()

    def run(sink: ProgressSink) -> IngestReport:
        sink.on_event(IngestEvent("track_done", 1, 1, "t", "ok"))
        at_end.set()
        assert go.wait(TIMEOUT_S)
        sink.on_event(IngestEvent("finished", 1, 1))
        return report()

    job = manager.start("k", {}, run)
    assert at_end.wait(TIMEOUT_S)
    manager.cancel(job.id)
    go.set()
    assert wait_ended(job).status == "done"


def test_a_failure_ends_failed_with_the_type_and_a_redacted_message() -> None:
    manager = JobManager()

    def run(sink: ProgressSink) -> IngestReport:
        error = RuntimeError("bad https://api.jamendo.com/v3.0/tracks/?client_id=SECRET123&x=1")
        error.report = report(processed=1, seen=1, new=1)  # type: ignore[attr-defined]
        raise error

    job = wait_ended(manager.start("k", {}, run))
    assert job.status == "failed"
    assert job.error == "RuntimeError: bad <url>"
    assert "SECRET123" not in repr(job.to_dict(detail=True)) + repr(job.events_after(0))
    assert job.report is not None and job.report["processed"] == 1
    last = job.events_after(0)[-1]
    assert last["type"] == "failed" and last["data"]["error"] == "RuntimeError: bad <url>"


def test_the_last_finished_jobs_are_kept_newest_first() -> None:
    manager = JobManager(keep=3)
    jobs = [wait_ended(manager.start("k", {"n": n}, lambda sink: report())) for n in range(5)]
    kept = manager.list()
    assert [j.id for j in kept] == [j.id for j in reversed(jobs[-3:])]
    with pytest.raises(LookupError):
        manager.get(jobs[0].id)
    assert manager.get(jobs[-1].id) is jobs[-1]


def test_close_cancels_the_running_job_and_waits_for_it() -> None:
    manager = JobManager()
    started = threading.Event()
    stop = threading.Event()

    def run(sink: ProgressSink) -> IngestReport:
        started.set()
        while not stop.wait(0.005):
            sink.on_event(IngestEvent("track_done", 1, None, "t", "ok"))
        return report()

    job = manager.start("k", {}, run)
    assert started.wait(TIMEOUT_S)
    try:
        manager.close()
        assert job.status == "cancelled"
    finally:
        stop.set()
    with pytest.raises(JobBusyError):
        manager.start("k", {}, lambda sink: report())


def test_unknown_jobs() -> None:
    manager = JobManager()
    with pytest.raises(LookupError):
        manager.get("nope")
    with pytest.raises(LookupError):
        manager.cancel("nope")


def test_reports_cap_the_failure_list_and_hide_urls() -> None:
    failures = [
        IngestFailure(str(n), f"title {n}", "analysis", f"boom https://x.test/{n}?client_id=S")
        for n in range(MAX_FAILURES + 7)
    ]
    data = report_to_dict(report(failures=failures, failed=len(failures)))
    assert len(data["failures"]) == MAX_FAILURES and data["failures_total"] == MAX_FAILURES + 7
    assert data["failures"][0] == {
        "source_id": "0", "title": "title 0", "stage": "analysis", "message": "boom <url>",
    }  # fmt: skip
    assert data["aborted"] is None and data["elapsed_s"] == 0.5


def test_redaction_and_error_text() -> None:
    assert redact("see http://a.b/c?client_id=ZZ and client_id=QQ") == (
        "see <url> and client_id=<redacted>"
    )
    assert len(redact("x" * 1000)) <= 300
    assert error_text(ValueError("")) == "ValueError"
    assert error_text(KeyError("k")) == "KeyError: 'k'"
