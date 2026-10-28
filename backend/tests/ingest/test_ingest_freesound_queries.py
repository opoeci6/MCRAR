"""ingest_freesound_queries and combine_reports: the first N new sounds of several searches."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from ingest_support import FakeAnalyzer, FakeClient, make_track

from mcrar.catalog import CatalogRepository
from mcrar.ingest import (
    AnalysisStage,
    FreesoundQuery,
    IngestEvent,
    IngestFailure,
    IngestReport,
    combine_reports,
    ingest_freesound,
    ingest_freesound_queries,
)
from mcrar.sources import SourceTrack

CC0 = "https://creativecommons.org/publicdomain/zero/1.0/"
Q1 = FreesoundQuery(query="dark cave")
Q2 = FreesoundQuery(query="drone", licenses=("cc0", "by", "by-nc"), duration_min_s=30.0)


def _sounds(first: int, last: int) -> list[SourceTrack]:
    return [
        make_track(i, source="freesound", license_url=CC0, title=f"Sound {i}")
        for i in range(first, last + 1)
    ]


class FakeFreesound(FakeClient):
    """Like the Jamendo fake, but its queries are keyed by their ``query`` text."""

    def search_tracks(self, **kwargs: Any) -> Iterator[SourceTrack]:
        self.search_kwargs.append(kwargs)
        tracks = self.tracks
        if self.per_query is not None:
            tracks = self.per_query.get(kwargs.get("query", ""), [])
        return self._results(tracks[: kwargs["limit"]])


def _run(
    client: FakeFreesound,
    repo: CatalogRepository,
    queries: list[FreesoundQuery],
    limit: int,
    **kw: Any,
) -> IngestReport:
    return ingest_freesound_queries(
        client, repo, queries, limit=limit, stages=[AnalysisStage(FakeAnalyzer())], **kw
    )


def _id(repo: CatalogRepository, source_id: str) -> int:
    track = repo.get_track_by_source("freesound", source_id)
    assert track is not None
    return track.id


def test_it_stops_after_the_limit_without_scanning_further(repo: CatalogRepository) -> None:
    client = FakeFreesound(_sounds(1, 10))
    report = _run(client, repo, [Q1, Q2], limit=3)
    assert (report.seen, report.new, report.processed, report.failed) == (3, 3, 3, 0)
    assert client.pulled == ["1", "2", "3"]  # lazy
    assert len(client.search_kwargs) == 1  # the second query was not needed
    assert repo.get_track_by_source("freesound", "4") is None
    assert repo.get_track_by_source("jamendo", "1") is None  # stored as Freesound


def test_each_query_is_searched_with_its_arguments_and_the_scan_limit(
    repo: CatalogRepository,
) -> None:
    client = FakeFreesound([], per_query={})
    _run(client, repo, [Q1, Q2], limit=5, scan_limit=40)
    assert client.search_kwargs == [
        {
            "query": "dark cave",
            "licenses": ["cc0", "by"],
            "duration_min_s": 10.0,
            "duration_max_s": 600.0,
            "music_like": True,
            "sort": "score",
            "limit": 40,
        },
        {
            "query": "drone",
            "licenses": ["cc0", "by", "by-nc"],
            "duration_min_s": 30.0,
            "duration_max_s": 600.0,
            "music_like": True,
            "sort": "score",
            "limit": 40,
        },
    ]


def test_known_sounds_are_skipped_before_any_download_and_do_not_count(
    repo: CatalogRepository,
) -> None:
    ingest_freesound(
        FakeFreesound(_sounds(1, 2)),
        repo,
        query="x",
        limit=2,
        stages=[AnalysisStage(FakeAnalyzer())],
    )
    client = FakeFreesound(_sounds(1, 8))
    report = _run(client, repo, [Q1], limit=3)
    assert (report.seen, report.new, report.updated, report.processed) == (3, 3, 0, 3)
    assert sorted(client.fetched) == ["3", "4", "5"]
    assert report.new_track_ids == [_id(repo, s) for s in ("3", "4", "5")]


def test_a_sound_found_by_an_earlier_query_is_skipped_by_the_later_ones(
    repo: CatalogRepository,
) -> None:
    client = FakeFreesound([], per_query={"dark cave": _sounds(1, 2), "drone": _sounds(2, 4)})
    report = _run(client, repo, [Q1, Q2], limit=4)
    assert (report.seen, report.new) == (4, 4)
    assert client.fetched.count("2") == 1


def test_it_ends_normally_when_every_query_is_exhausted_early(repo: CatalogRepository) -> None:
    client = FakeFreesound([], per_query={"dark cave": _sounds(1, 2)})
    events: list[IngestEvent] = []
    report = _run(client, repo, [Q1, Q2], limit=50, on_progress=events.append)
    assert (report.new, report.aborted) == (2, None)
    assert [e.kind for e in events] == ["started", "track_done", "track_done", "finished"]
    assert all(e.total == 50 for e in events)


def test_no_queries_is_an_empty_run_and_the_limit_must_be_positive(repo: CatalogRepository) -> None:
    report = _run(FakeFreesound([]), repo, [], limit=5)
    assert (report.seen, report.new, report.new_track_ids) == (0, 0, [])
    with pytest.raises(ValueError, match="limit"):
        _run(FakeFreesound([]), repo, [Q1], limit=0)


def test_combine_reports_adds_up_runs_in_order() -> None:
    failure = IngestFailure("7", "Sound 7", "analysis", "boom")
    first = IngestReport(3, 2, 1, 2, 0, 1, [failure], 1.5, None, [10, 11])
    second = IngestReport(4, 4, 0, 3, 1, 0, [], 2.0, "interrupted", [12, 13, 14, 15])
    total = combine_reports([first, second])
    assert (total.seen, total.new, total.updated) == (7, 6, 1)
    assert (total.processed, total.skipped, total.failed) == (5, 1, 1)
    assert total.failures == [failure]
    assert total.elapsed_s == 3.5
    assert total.aborted == "interrupted"
    assert total.new_track_ids == [10, 11, 12, 13, 14, 15]
    empty = combine_reports([])
    assert (empty.seen, empty.aborted, empty.new_track_ids) == (0, None, [])
