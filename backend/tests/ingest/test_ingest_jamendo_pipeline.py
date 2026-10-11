"""ingest_jamendo with a fake client and fake analyzers (plus one run of the real analysis)."""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from typing import Any

import pytest
from ingest_support import (
    CC_BY,
    CC_BY_NC_ND,
    FakeAnalyzer,
    FakeClient,
    RecordingStage,
    make_track,
    wav_bytes,
)

from mcrar.audio import ANALYSIS_VERSION, AudioDecodeError
from mcrar.catalog import CatalogRepository
from mcrar.ingest import (
    AnalysisStage,
    IngestEvent,
    IngestReport,
    JamendoQuery,
    ingest_jamendo,
)
from mcrar.sources import JamendoAuthError, JamendoRateLimitError, JamendoStreamError


def _tracks(n: int) -> list:
    return [make_track(i) for i in range(1, n + 1)]


def _run(
    client: FakeClient,
    repo: CatalogRepository,
    analyzer: FakeAnalyzer,
    *,
    limit: int | None = None,
    **kwargs: Any,
) -> IngestReport:
    return ingest_jamendo(
        client,
        repo,
        query=kwargs.pop("query", {}),
        limit=limit if limit is not None else len(client.tracks),
        stages=kwargs.pop("stages", [AnalysisStage(analyzer)]),
        **kwargs,
    )


def _fetch_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name.startswith("mcrar-fetch")]


def _stored(repo: CatalogRepository, source_id: str):  # noqa: ANN202
    track = repo.get_track_by_source("jamendo", source_id)
    assert track is not None
    return track


def test_new_tracks_are_stored_and_analysed(repo: CatalogRepository) -> None:
    client = FakeClient([make_track(1, license_url=CC_BY), make_track(2, license_url=CC_BY_NC_ND)])
    analyzer = FakeAnalyzer()
    report = _run(client, repo, analyzer)
    assert (report.seen, report.new, report.updated) == (2, 2, 0)
    assert (report.processed, report.skipped, report.failed) == (2, 0, 0)
    assert report.failures == []
    assert report.aborted is None
    assert report.elapsed_s >= 0
    assert analyzer.calls == 2
    assert all(isinstance(s, bytes) for s in analyzer.sources)
    green, red = _stored(repo, "1"), _stored(repo, "2")
    assert (green.risk, red.risk) == ("green", "red")
    assert repo.features_version(green.id) == ANALYSIS_VERSION
    entry = repo.get_ingest_status("jamendo", "1", "analysis")
    assert entry is not None and entry.status == "ok" and entry.track_id == green.id


def test_rerun_skips_but_refreshes_metadata(repo: CatalogRepository) -> None:
    first = FakeClient([make_track(i, stream_url=f"https://a.example/{i}?t=old") for i in (1, 2)])
    _run(first, repo, FakeAnalyzer())
    second = FakeClient([make_track(i, stream_url=f"https://a.example/{i}?t=new") for i in (1, 2)])
    analyzer = FakeAnalyzer()
    report = _run(second, repo, analyzer)
    assert (report.new, report.updated) == (0, 2)
    assert (report.processed, report.skipped, report.failed) == (0, 2, 0)
    assert analyzer.calls == 0
    assert second.fetched == []  # nothing to do, so no download
    assert _stored(repo, "1").stream_url == "https://a.example/1?t=new"
    entry = repo.get_ingest_status("jamendo", "1", "analysis")
    assert entry is not None and entry.status == "skipped" and entry.message == "up to date"


def test_unchanged_metadata_is_not_counted_as_updated(repo: CatalogRepository) -> None:
    _run(FakeClient(_tracks(2)), repo, FakeAnalyzer())
    report = _run(FakeClient(_tracks(2)), repo, FakeAnalyzer())
    assert (report.new, report.updated, report.skipped) == (0, 0, 2)


def test_force_reanalyses(repo: CatalogRepository) -> None:
    _run(FakeClient(_tracks(2)), repo, FakeAnalyzer())
    client = FakeClient(_tracks(2))
    analyzer = FakeAnalyzer()
    report = _run(client, repo, analyzer, force=True)
    assert (report.processed, report.skipped) == (2, 0)
    assert analyzer.calls == 2
    assert sorted(client.fetched) == ["1", "2"]


def test_outdated_analysis_version_is_redone(repo: CatalogRepository) -> None:
    _run(FakeClient(_tracks(1)), repo, FakeAnalyzer())
    track = _stored(repo, "1")
    repo.set_features(track.id, {"analysis_version": "audio-v0"})
    analyzer = FakeAnalyzer()
    report = _run(FakeClient(_tracks(1)), repo, analyzer)
    assert (report.processed, analyzer.calls) == (1, 1)
    assert repo.features_version(track.id) == ANALYSIS_VERSION


def test_stream_error_is_failed_and_the_run_continues(repo: CatalogRepository) -> None:
    client = FakeClient(_tracks(3), fetch_errors={"2": JamendoStreamError("stream expired")})
    report = _run(client, repo, FakeAnalyzer())
    assert (report.processed, report.failed) == (2, 1)
    assert report.failures == [("2", "Track 2", "analysis", "JamendoStreamError: stream expired")]
    entry = repo.get_ingest_status("jamendo", "2", "analysis")
    assert entry is not None
    assert (entry.status, entry.message) == ("failed", "JamendoStreamError: stream expired")
    assert repo.features_version(_stored(repo, "2").id) is None  # metadata kept, no features
    assert repo.features_version(_stored(repo, "3").id) == ANALYSIS_VERSION


def test_failed_track_is_retried_on_the_next_run(repo: CatalogRepository) -> None:
    _run(FakeClient(_tracks(2), fetch_errors={"1": JamendoStreamError("x")}), repo, FakeAnalyzer())
    report = _run(FakeClient(_tracks(2)), repo, FakeAnalyzer())
    assert (report.processed, report.skipped, report.failed) == (1, 1, 0)
    entry = repo.get_ingest_status("jamendo", "1", "analysis")
    assert entry is not None and entry.status == "ok" and entry.attempts == 2


def test_analysis_error_is_failed_and_the_run_continues(repo: CatalogRepository) -> None:
    analyzer = FakeAnalyzer(errors={2: AudioDecodeError("corrupt " + "x" * 400)})
    report = _run(FakeClient(_tracks(3)), repo, analyzer)
    assert (report.processed, report.failed) == (2, 1)
    (failure,) = report.failures
    assert failure.source_id == "2"
    assert failure.message.startswith("AudioDecodeError: corrupt")
    assert len(failure.message) == len("AudioDecodeError: ") + 200
    assert repo.failed_items("analysis")[0].source_id == "2"


def test_unexpected_exception_is_failed_and_the_run_continues(repo: CatalogRepository) -> None:
    report = _run(FakeClient(_tracks(2)), repo, FakeAnalyzer(errors={1: ZeroDivisionError("boom")}))
    assert (report.processed, report.failed) == (1, 1)
    assert report.failures[0].message == "ZeroDivisionError: boom"


def test_track_without_stream_url_is_failed(repo: CatalogRepository) -> None:
    client = FakeClient([make_track(1, stream_url=None), make_track(2)])
    report = _run(client, repo, FakeAnalyzer())
    assert (report.processed, report.failed) == (1, 1)
    assert report.failures == [("1", "Track 1", "analysis", "no audio stream")]
    assert client.fetched == ["2"]


def test_auth_error_aborts_keeping_earlier_tracks(repo: CatalogRepository) -> None:
    client = FakeClient(_tracks(6), fetch_errors={"3": JamendoAuthError("bad client id")})
    events: list[IngestEvent] = []
    with pytest.raises(JamendoAuthError) as raised:
        _run(client, repo, FakeAnalyzer(), on_progress=events.append)
    report = raised.value.report  # type: ignore[attr-defined]
    assert report.aborted == "JamendoAuthError: bad client id"
    assert (report.processed, report.failed) == (2, 0)
    assert events[-1].kind == "finished" and events[-1].message == report.aborted
    for n in ("1", "2"):
        assert repo.features_version(_stored(repo, n).id) == ANALYSIS_VERSION
    assert repo.get_ingest_status("jamendo", "3", "analysis") is None
    assert _fetch_threads() == []  # the prefetch pool was shut down


def test_rate_limit_aborts_too(repo: CatalogRepository) -> None:
    client = FakeClient(_tracks(3), fetch_errors={"1": JamendoRateLimitError("slow down")})
    with pytest.raises(JamendoRateLimitError) as raised:
        _run(client, repo, FakeAnalyzer())
    assert raised.value.report.aborted.startswith("JamendoRateLimitError")  # type: ignore[attr-defined]
    assert _fetch_threads() == []


def test_failing_search_aborts(repo: CatalogRepository) -> None:
    class BrokenSearch(FakeClient):
        def search_tracks(self, **kwargs: Any):  # noqa: ANN201
            def gen():  # noqa: ANN202
                yield self.tracks[0]
                raise RuntimeError("search died")

            return gen()

    with pytest.raises(RuntimeError, match="search died") as raised:
        _run(BrokenSearch(_tracks(3)), repo, FakeAnalyzer(), limit=3)
    assert raised.value.report.aborted == "RuntimeError: search died"  # type: ignore[attr-defined]
    assert _fetch_threads() == []


def test_prefetch_overlaps_download_and_analysis(repo: CatalogRepository) -> None:
    n, delay = 6, 0.2
    client = FakeClient(_tracks(n), fetch_delay=delay)
    analyzer = FakeAnalyzer(delay=delay)
    started = time.monotonic()
    report = _run(client, repo, analyzer)
    total = time.monotonic() - started
    assert report.processed == n
    assert total < 0.85 * n * 2 * delay  # sequential would take n * (fetch + analysis)
    # The download of track 2 starts before the analysis of track 1 ends.
    fetch_start = {sid: start for sid, start, _ in client.fetch_spans}
    assert fetch_start["2"] < analyzer.spans[0][1]
    # Never more than two tracks ahead of the one being analysed.
    for k, (analysis_start, _) in enumerate(analyzer.spans):
        started_fetches = sum(1 for s in fetch_start.values() if s <= analysis_start)
        assert started_fetches <= k + 3
    assert _fetch_threads() == []


def test_audio_is_fetched_once_for_several_stages(repo: CatalogRepository) -> None:
    client = FakeClient(_tracks(3))
    analyzer = FakeAnalyzer()
    extra = RecordingStage()
    report = _run(client, repo, analyzer, stages=[AnalysisStage(analyzer), extra])
    assert report.processed == 3
    assert sorted(client.fetched) == ["1", "2", "3"]
    assert analyzer.calls == 3 and len(extra.done) == 3
    for stage in ("analysis", "embedding"):
        entry = repo.get_ingest_status("jamendo", "2", stage)
        assert entry is not None and entry.status == "ok"


def test_only_the_stage_that_is_not_current_runs(repo: CatalogRepository) -> None:
    _run(FakeClient(_tracks(2)), repo, FakeAnalyzer())
    client = FakeClient(_tracks(2))
    analyzer = FakeAnalyzer()
    extra = RecordingStage()
    report = _run(client, repo, analyzer, stages=[AnalysisStage(analyzer), extra])
    assert (report.processed, analyzer.calls, len(extra.done)) == (2, 0, 2)
    assert sorted(client.fetched) == ["1", "2"]
    skipped = repo.get_ingest_status("jamendo", "1", "analysis")
    assert skipped is not None and skipped.status == "skipped"


def test_no_audio_is_fetched_when_every_stage_is_current(repo: CatalogRepository) -> None:
    extra = RecordingStage()
    analyzer = FakeAnalyzer()
    stages = [AnalysisStage(analyzer), extra]
    _run(FakeClient(_tracks(2)), repo, analyzer, stages=stages)
    client = FakeClient(_tracks(2))
    report = _run(client, repo, analyzer, stages=stages)
    assert report.skipped == 2
    assert client.fetched == []


def test_one_failing_stage_does_not_block_the_other(repo: CatalogRepository) -> None:
    class Exploding(RecordingStage):
        def run(self, repo: Any, track_id: int, audio: object) -> None:
            raise RuntimeError("no gpu")

    analyzer = FakeAnalyzer()
    report = _run(
        FakeClient(_tracks(1)), repo, analyzer, stages=[Exploding(), AnalysisStage(analyzer)]
    )
    assert (report.processed, report.failed) == (0, 1)
    assert report.failures == [("1", "Track 1", "embedding", "RuntimeError: no gpu")]
    assert analyzer.calls == 1
    entry = repo.get_ingest_status("jamendo", "1", "analysis")
    assert entry is not None and entry.status == "ok"


def test_keyboard_interrupt_returns_a_partial_report(repo: CatalogRepository) -> None:
    client = FakeClient(_tracks(5))
    analyzer = FakeAnalyzer(errors={3: KeyboardInterrupt()})
    events: list[IngestEvent] = []
    report = _run(client, repo, analyzer, on_progress=events.append)
    assert report.aborted == "interrupted"
    assert report.processed == 2
    assert events[-1].kind == "finished" and events[-1].message == "interrupted"
    # A rerun resumes: the two finished tracks are skipped, the rest are analysed.
    resumed = _run(FakeClient(_tracks(5)), repo, FakeAnalyzer())
    assert (resumed.skipped, resumed.processed, resumed.aborted) == (2, 3, None)


def test_progress_events(repo: CatalogRepository) -> None:
    client = FakeClient([make_track(1), make_track(2, stream_url=None), make_track(3)])
    events: list[IngestEvent] = []
    _run(client, repo, FakeAnalyzer(), limit=3, on_progress=events.append)
    _run(FakeClient([make_track(1)]), repo, FakeAnalyzer(), limit=3, on_progress=events.append)
    first = events[:5]
    assert [e.kind for e in first] == [
        "started",
        "track_done",
        "track_failed",
        "track_done",
        "finished",
    ]
    assert [e.index for e in first[1:4]] == [1, 2, 3]
    assert all(e.total == 3 for e in first)
    assert first[1].title == "Track 1" and first[1].message == "120 BPM C major (green)"
    assert first[2].message == "no audio stream"
    assert events[-2].kind == "track_skipped" and events[-2].message == "up to date"


def test_query_is_passed_to_the_client(repo: CatalogRepository) -> None:
    client = FakeClient(_tracks(1))
    query = JamendoQuery(tags=["rock", "indie"], vocalinstrumental="instrumental", order="x")
    _run(client, repo, FakeAnalyzer(), query=query, limit=5)
    _run(client, repo, FakeAnalyzer(), query={"search": "calm"}, limit=5)
    assert client.search_kwargs == [
        {"tags": ["rock", "indie"], "vocalinstrumental": "instrumental", "order": "x", "limit": 5},
        {"search": "calm", "limit": 5},
    ]


def test_real_analysis_of_downloaded_audio(repo: CatalogRepository) -> None:
    client = FakeClient([make_track(1)], audio=wav_bytes(bpm=120, seconds=8))
    report = ingest_jamendo(client, repo, query={}, limit=1)  # default stages: real analysis
    assert (report.processed, report.failed) == (1, 0), report.failures
    features = repo.get_features(_stored(repo, "1").id)
    assert features is not None
    assert features["analysis_version"] == ANALYSIS_VERSION
    assert features["sample_rate"] == 22050
    assert features["bpm"] is not None and abs(features["bpm"] - 120) < 6
    assert features["key"] is not None


def test_metadata_is_refreshed_even_when_analysis_fails(repo: CatalogRepository) -> None:
    track = make_track(1, license_url=CC_BY_NC_ND)
    _run(FakeClient([track]), repo, FakeAnalyzer(errors={1: ValueError("x")}))
    assert _stored(repo, "1").risk == "red"
    _run(FakeClient([replace(track, license_url=CC_BY)]), repo, FakeAnalyzer())
    assert _stored(repo, "1").risk == "green"
