"""ingest_freesound and ingest_freesound_ids with a fake client (no network)."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from typing import Any

import pytest
from ingest_support import CC_BY, FakeAnalyzer, FakeClient, make_track

from mcrar.audio import ANALYSIS_VERSION
from mcrar.catalog import CatalogRepository
from mcrar.ingest import (
    AnalysisStage,
    IngestEvent,
    IngestReport,
    ingest_freesound,
    ingest_freesound_ids,
)
from mcrar.sources import FreesoundAuthError, FreesoundRateLimitError, SourceTrack

CC0 = "https://creativecommons.org/publicdomain/zero/1.0/"
CC_BY_NC = "https://creativecommons.org/licenses/by-nc/4.0/"
SAMPLING_PLUS = "https://creativecommons.org/licenses/sampling+/1.0/"


def fs_track(n: int, *, license_url: str | None = CC_BY, **overrides: Any) -> SourceTrack:
    fields: dict[str, Any] = {
        "source": "freesound",
        "source_id": str(n),
        "title": f"Sound {n}",
        "artist": f"user{n}",
        "album": None,
        "duration_s": 42.0,
        "source_url": f"https://freesound.org/people/user{n}/sounds/{n}/",
        "stream_url": f"https://cdn.freesound.org/previews/{n}/{n}_1-hq.mp3",
        "license_url": license_url,
        "tags": {"vartags": ["loop", "warm"], "category": ["Music"]},
    }
    fields.update(overrides)
    return make_track(n, **fields)


class FreesoundFake(FakeClient):
    """FakeClient plus ``get_tracks`` (by id)."""

    def __init__(self, tracks: list[SourceTrack], **kwargs: Any) -> None:
        super().__init__(tracks, **kwargs)
        self.lookups: list[list[str]] = []

    def get_tracks(self, ids: Sequence[str | int], **kwargs: Any) -> list[SourceTrack]:
        self.lookups.append([str(i) for i in ids])
        known = {t.source_id: t for t in self.tracks}
        return [known[str(i)] for i in ids if str(i) in known]


def _tracks(n: int) -> list[SourceTrack]:
    return [fs_track(i) for i in range(1, n + 1)]


def _run(
    client: FakeClient, repo: CatalogRepository, analyzer: FakeAnalyzer, **kwargs: Any
) -> IngestReport:
    return ingest_freesound(
        client,
        repo,
        limit=kwargs.pop("limit", len(client.tracks)),
        stages=kwargs.pop("stages", [AnalysisStage(analyzer)]),
        **kwargs,
    )


def _stored(repo: CatalogRepository, source_id: str):  # noqa: ANN202
    track = repo.get_track_by_source("freesound", source_id)
    assert track is not None
    return track


def _fetch_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name.startswith("mcrar-fetch")]


def test_sounds_are_stored_as_freesound_with_the_licence_of_their_preview(
    repo: CatalogRepository,
) -> None:
    licences = [CC0, CC_BY, CC_BY_NC, SAMPLING_PLUS]
    client = FreesoundFake([fs_track(i, license_url=u) for i, u in enumerate(licences, 1)])
    analyzer = FakeAnalyzer()
    report = _run(client, repo, analyzer)
    assert (report.seen, report.new, report.updated) == (4, 4, 0)
    assert (report.processed, report.skipped, report.failed) == (4, 0, 0)
    assert analyzer.calls == 4 and all(isinstance(s, bytes) for s in analyzer.sources)
    stored = [_stored(repo, str(i)) for i in range(1, 5)]
    assert [t.source for t in stored] == ["freesound"] * 4
    assert [t.license_family for t in stored] == ["cc0", "cc-by", "cc-by-nc", "sampling-plus"]
    assert [t.risk for t in stored] == ["green", "green", "red", "red"]
    assert stored[0].stream_url == "https://cdn.freesound.org/previews/1/1_1-hq.mp3"
    assert stored[1].source_tags == {"vartags": ["loop", "warm"], "category": ["Music"]}
    assert repo.features_version(stored[0].id) == ANALYSIS_VERSION
    entry = repo.get_ingest_status("freesound", "1", "analysis")
    assert entry is not None and entry.status == "ok" and entry.track_id == stored[0].id
    assert repo.get_track_by_source("jamendo", "1") is None


def test_the_search_filters_reach_the_client(repo: CatalogRepository) -> None:
    client = FreesoundFake(_tracks(1))
    _run(client, repo, FakeAnalyzer())
    _run(
        client,
        repo,
        FakeAnalyzer(),
        query="calm pad",
        tags=("loop", "warm"),
        licenses=("cc0",),
        duration_min_s=20,
        duration_max_s=90,
        sort="downloads_desc",
        limit=7,
    )
    assert client.search_kwargs == [
        {
            "query": "",
            "tags": [],
            "licenses": ["cc0", "by"],
            "duration_min_s": 10.0,
            "duration_max_s": 600.0,
            "sort": "score",
            "limit": 1,
        },
        {
            "query": "calm pad",
            "tags": ["loop", "warm"],
            "licenses": ["cc0"],
            "duration_min_s": 20,
            "duration_max_s": 90,
            "sort": "downloads_desc",
            "limit": 7,
        },
    ]


def test_an_existing_track_is_skipped_unless_forced(repo: CatalogRepository) -> None:
    _run(FreesoundFake(_tracks(2)), repo, FakeAnalyzer())
    client = FreesoundFake(_tracks(2))
    analyzer = FakeAnalyzer()
    again = _run(client, repo, analyzer)
    assert (again.new, again.updated, again.processed, again.skipped) == (0, 0, 0, 2)
    assert client.fetched == [] and analyzer.calls == 0  # nothing to do, so no download
    assert len(repo.list_tracks(source="freesound", limit=10)[0]) == 2  # no duplicates

    forced_client = FreesoundFake(_tracks(2))
    forced = _run(forced_client, repo, analyzer, force=True)
    assert (forced.new, forced.processed, forced.skipped) == (0, 2, 0)
    assert sorted(forced_client.fetched) == ["1", "2"] and analyzer.calls == 2


def test_a_failed_download_fails_the_track_only(repo: CatalogRepository) -> None:
    client = FreesoundFake(_tracks(3), fetch_errors={"2": RuntimeError("preview gone")})
    report = _run(client, repo, FakeAnalyzer())
    assert (report.processed, report.failed) == (2, 1)
    assert report.failures == [("2", "Sound 2", "analysis", "RuntimeError: preview gone")]
    entry = repo.get_ingest_status("freesound", "2", "analysis")
    assert entry is not None and entry.status == "failed"


def test_a_sound_without_a_preview_url_fails_with_no_audio_stream(repo: CatalogRepository) -> None:
    client = FreesoundFake([fs_track(1, stream_url=None), fs_track(2)])
    report = _run(client, repo, FakeAnalyzer())
    assert report.failures == [("1", "Sound 1", "analysis", "no audio stream")]
    assert client.fetched == ["2"]


@pytest.mark.parametrize(
    "error",
    [FreesoundAuthError("bad key"), FreesoundRateLimitError("slow down")],
)
def test_auth_and_rate_limit_errors_abort_with_the_partial_report(
    repo: CatalogRepository, error: Exception
) -> None:
    client = FreesoundFake(_tracks(6), fetch_errors={"3": error})
    events: list[IngestEvent] = []
    with pytest.raises(type(error)) as raised:
        _run(client, repo, FakeAnalyzer(), on_progress=events.append)
    report = raised.value.report  # type: ignore[attr-defined]
    assert report.aborted == f"{type(error).__name__}: {error}"
    assert (report.processed, report.failed) == (2, 0)
    assert events[-1].kind == "finished" and events[-1].message == report.aborted
    for n in ("1", "2"):
        assert repo.features_version(_stored(repo, n).id) == ANALYSIS_VERSION
    assert repo.get_ingest_status("freesound", "3", "analysis") is None
    assert _fetch_threads() == []


def test_a_failing_search_aborts_with_the_report(repo: CatalogRepository) -> None:
    class Broken(FreesoundFake):
        def search_tracks(self, **kwargs: Any):  # noqa: ANN201
            raise ValueError("Invalid tag 'a b'")

    with pytest.raises(ValueError, match="Invalid tag") as raised:
        _run(Broken(_tracks(2)), repo, FakeAnalyzer(), limit=2)
    assert raised.value.report.aborted == "ValueError: Invalid tag 'a b'"  # type: ignore[attr-defined]
    assert _fetch_threads() == []


def test_progress_events(repo: CatalogRepository) -> None:
    client = FreesoundFake([fs_track(1), fs_track(2, stream_url=None), fs_track(3)])
    events: list[IngestEvent] = []
    _run(client, repo, FakeAnalyzer(), limit=3, on_progress=events.append)
    assert [e.kind for e in events] == [
        "started",
        "track_done",
        "track_failed",
        "track_done",
        "finished",
    ]
    assert [e.index for e in events[1:4]] == [1, 2, 3]
    assert all(e.total == 3 for e in events)
    assert events[1].title == "Sound 1" and events[1].message == "120 BPM C major (green)"
    assert events[2].message == "no audio stream"


# -- by id ---------------------------------------------------------------------------------------


def test_ids_without_stages_store_only_the_metadata(repo: CatalogRepository) -> None:
    client = FreesoundFake([fs_track(n) for n in (1, 2, 3)])
    events: list[IngestEvent] = []
    report = ingest_freesound_ids(
        client, repo, ["1", 3, "1", "99"], stages=[], on_progress=events.append
    )
    assert client.lookups == [["1", "3", "99"]]  # deduplicated, one batch
    assert client.fetched == []
    assert (report.seen, report.new, report.processed, report.failed) == (2, 2, 2, 0)
    track = _stored(repo, "3")
    assert track.title == "Sound 3" and track.license_family == "cc-by"
    assert repo.get_track_by_source("freesound", "2") is None  # not asked for
    assert repo.ingest_entries("freesound", "3") == []
    assert events[0].kind == "started" and events[0].total == 3 and events[-1].kind == "finished"


def test_ids_with_a_stage_fetch_the_audio_once_and_skip_when_current(
    repo: CatalogRepository,
) -> None:
    client = FreesoundFake(_tracks(2))
    analyzer = FakeAnalyzer()
    report = ingest_freesound_ids(client, repo, ["1", "2"], stages=[AnalysisStage(analyzer)])
    assert (report.processed, report.failed) == (2, 0) and sorted(client.fetched) == ["1", "2"]
    again = ingest_freesound_ids(client, repo, ["1"], stages=[AnalysisStage(analyzer)])
    assert again.skipped == 1 and analyzer.calls == 2


def test_ids_abort_on_an_auth_error(repo: CatalogRepository) -> None:
    class Rejecting(FreesoundFake):
        def get_tracks(self, ids: Sequence[str | int], **kwargs: Any) -> list[SourceTrack]:
            raise FreesoundAuthError("bad key")

    with pytest.raises(FreesoundAuthError) as raised:
        ingest_freesound_ids(Rejecting([]), repo, ["5"], stages=[])
    assert raised.value.report.aborted is not None  # type: ignore[attr-defined]
