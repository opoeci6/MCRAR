"""ingest_jamendo_queries: the first N new tracks of several searches (fake client, no network)."""

from __future__ import annotations

import threading
from typing import Any

import pytest
from ingest_support import FakeAnalyzer, FakeClient, make_track

from mcrar.catalog import CatalogRepository
from mcrar.ingest import (
    AnalysisStage,
    IngestEvent,
    IngestReport,
    JamendoQuery,
    ingest_jamendo,
    ingest_jamendo_queries,
)
from mcrar.sources import JamendoAuthError

Q1 = JamendoQuery(search="dark cave", order="relevance")
Q2 = JamendoQuery(search="dark-cave", order="relevance")
Q3 = JamendoQuery(fuzzytags=["dark", "cave"])  # FakeClient keys it as "dark cave" too


def _tracks(first: int, last: int) -> list:
    return [make_track(i) for i in range(first, last + 1)]


def _run(
    client: FakeClient,
    repo: CatalogRepository,
    queries: list[JamendoQuery],
    max_new: int,
    analyzer: FakeAnalyzer | None = None,
    **kwargs: Any,
) -> IngestReport:
    return ingest_jamendo_queries(
        client,
        repo,
        queries=queries,
        max_new=max_new,
        stages=[AnalysisStage(analyzer or FakeAnalyzer())],
        **kwargs,
    )


def _fetch_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name.startswith("mcrar-fetch")]


def _id(repo: CatalogRepository, source_id: str) -> int:
    track = repo.get_track_by_source("jamendo", source_id)
    assert track is not None
    return track.id


def test_it_stops_after_max_new_tracks_without_scanning_further(repo: CatalogRepository) -> None:
    client = FakeClient(_tracks(1, 10))
    report = _run(client, repo, [Q1, Q2], max_new=3)
    assert (report.seen, report.new, report.processed, report.failed) == (3, 3, 3, 0)
    assert report.aborted is None
    assert client.pulled == ["1", "2", "3"]  # lazy: the 4th result was never taken
    assert sorted(client.fetched) == ["1", "2", "3"]
    assert len(client.search_kwargs) == 1  # the second query was not needed
    assert repo.get_track_by_source("jamendo", "4") is None


def test_each_query_is_searched_with_its_kwargs_and_the_scan_limit(
    repo: CatalogRepository,
) -> None:
    client = FakeClient([], per_query={})
    _run(client, repo, [Q1, Q2, Q3], max_new=5, scan_limit=40)
    assert client.search_kwargs == [
        {"search": "dark cave", "order": "relevance", "limit": 40},
        {"search": "dark-cave", "order": "relevance", "limit": 40},
        {"fuzzytags": ["dark", "cave"], "limit": 40},
    ]


def test_tracks_already_in_the_catalog_are_skipped_before_any_download_and_do_not_count(
    repo: CatalogRepository,
) -> None:
    ingest_jamendo(
        FakeClient(_tracks(1, 2)),
        repo,
        query={},
        limit=2,
        stages=[AnalysisStage(FakeAnalyzer())],
    )
    client = FakeClient(_tracks(1, 8))
    report = _run(client, repo, [Q1], max_new=3)
    assert (report.seen, report.new, report.updated, report.processed) == (3, 3, 0, 3)
    assert sorted(client.fetched) == ["3", "4", "5"]  # 1 and 2 were never downloaded
    assert client.pulled == ["1", "2", "3", "4", "5"]  # but they were scanned past
    assert report.new_track_ids == [_id(repo, s) for s in ("3", "4", "5")]


def test_a_track_found_by_an_earlier_query_is_skipped_by_the_later_ones(
    repo: CatalogRepository,
) -> None:
    client = FakeClient([], per_query={"dark cave": _tracks(1, 2), "dark-cave": _tracks(2, 4)})
    report = _run(client, repo, [Q1, Q2], max_new=4)
    assert (report.seen, report.new, report.processed) == (4, 4, 4)
    assert sorted(client.fetched) == ["1", "2", "3", "4"]
    assert client.fetched.count("2") == 1  # downloaded once


def test_a_query_without_results_moves_on_to_the_next(repo: CatalogRepository) -> None:
    client = FakeClient([], per_query={"dark-cave": _tracks(5, 6)})  # "dark cave" finds nothing
    report = _run(client, repo, [Q1, Q2], max_new=10)
    assert (report.seen, report.new) == (2, 2)
    assert [k["search"] for k in client.search_kwargs] == ["dark cave", "dark-cave"]


def test_it_ends_normally_when_every_query_is_exhausted_early(repo: CatalogRepository) -> None:
    client = FakeClient([], per_query={"dark cave": _tracks(1, 2)})
    events: list[IngestEvent] = []
    report = _run(client, repo, [Q1, Q2, Q3], max_new=50, on_progress=events.append)
    assert (report.new, report.processed, report.aborted) == (2, 2, None)
    assert len(client.search_kwargs) == 3  # all queries were tried
    assert [e.kind for e in events] == ["started", "track_done", "track_done", "finished"]
    assert all(e.total == 50 for e in events)  # the total is the cap


def test_no_queries_is_an_empty_run(repo: CatalogRepository) -> None:
    report = _run(FakeClient([]), repo, [], max_new=5)
    assert (report.seen, report.new, report.aborted, report.new_track_ids) == (0, 0, None, [])


def test_max_new_must_be_positive(repo: CatalogRepository) -> None:
    with pytest.raises(ValueError, match="max_new"):
        _run(FakeClient([]), repo, [Q1], max_new=0)


def test_new_track_ids_are_the_tracks_this_run_added(repo: CatalogRepository) -> None:
    report = _run(FakeClient(_tracks(1, 3)), repo, [Q1], max_new=3)
    assert report.new_track_ids == [_id(repo, s) for s in ("1", "2", "3")]
    again = _run(FakeClient(_tracks(1, 3)), repo, [Q1], max_new=3)
    assert again.new_track_ids == [] and again.seen == 0  # all known: nothing is taken


def test_ingest_jamendo_reports_its_new_track_ids_too(repo: CatalogRepository) -> None:
    stages = [AnalysisStage(FakeAnalyzer())]
    first = ingest_jamendo(FakeClient(_tracks(1, 2)), repo, query={}, limit=2, stages=stages)
    assert first.new_track_ids == [_id(repo, "1"), _id(repo, "2")]
    second = ingest_jamendo(FakeClient(_tracks(2, 3)), repo, query={}, limit=2, stages=stages)
    assert second.new == 1
    assert second.new_track_ids == [_id(repo, "3")]


def test_an_abort_error_keeps_the_partial_report_and_stops_the_pool(
    repo: CatalogRepository,
) -> None:
    client = FakeClient(_tracks(1, 6), fetch_errors={"3": JamendoAuthError("bad client id")})
    with pytest.raises(JamendoAuthError) as raised:
        _run(client, repo, [Q1], max_new=6)
    report = raised.value.report  # type: ignore[attr-defined]
    assert report.aborted == "JamendoAuthError: bad client id"
    assert report.processed == 2
    assert {_id(repo, "1"), _id(repo, "2")} <= set(report.new_track_ids)
    assert _fetch_threads() == []


def test_a_failing_search_aborts_like_ingest_jamendo(repo: CatalogRepository) -> None:
    class BrokenSecondSearch(FakeClient):
        def search_tracks(self, **kwargs: Any):  # noqa: ANN201
            if self.search_kwargs:
                raise RuntimeError("search died")
            return super().search_tracks(**kwargs)

    client = BrokenSecondSearch([], per_query={"dark cave": _tracks(1, 2)})
    with pytest.raises(RuntimeError, match="search died") as raised:
        _run(client, repo, [Q1, Q2], max_new=5)
    assert raised.value.report.aborted == "RuntimeError: search died"  # type: ignore[attr-defined]
    assert raised.value.report.new == 2  # type: ignore[attr-defined]  # taken before it died
    assert _fetch_threads() == []


def test_cancelling_from_the_progress_callback_returns_the_partial_report(
    repo: CatalogRepository,
) -> None:
    """Ctrl+C is the same path as the API job's cancel (a raise from ``on_progress``)."""
    done = 0

    def on_progress(event: IngestEvent) -> None:
        nonlocal done
        if event.kind == "track_done":
            done += 1
            if done == 2:
                raise KeyboardInterrupt

    client = FakeClient(_tracks(1, 10))
    report = _run(client, repo, [Q1], max_new=10, on_progress=on_progress)
    assert report.aborted == "interrupted"
    assert report.processed == 2
    assert {_id(repo, "1"), _id(repo, "2")} <= set(report.new_track_ids)
    assert len(client.pulled) < 10  # the scan stopped with the run
