"""ingest_jamendo_ids: tracks by id, metadata only with no stages (fake client, no network)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from ingest_support import FakeAnalyzer, FakeClient, make_track

from mcrar.catalog import CatalogRepository
from mcrar.ingest import AnalysisStage, IngestEvent, ingest_jamendo_ids
from mcrar.sources import JamendoAuthError, SourceTrack


class ByIdClient(FakeClient):
    def __init__(self, tracks: list[SourceTrack], error: Exception | None = None) -> None:
        super().__init__(tracks)
        self.lookups: list[list[str]] = []
        self.error = error

    def get_tracks(self, ids: Sequence[str | int], **kwargs: Any) -> list[SourceTrack]:
        self.lookups.append([str(i) for i in ids])
        if self.error is not None:
            raise self.error
        known = {t.source_id: t for t in self.tracks}
        return [known[str(i)] for i in ids if str(i) in known]


def test_without_stages_only_the_metadata_is_stored_and_no_audio_is_fetched(
    repo: CatalogRepository,
) -> None:
    client = ByIdClient([make_track(n) for n in (1, 2, 3)])
    events: list[IngestEvent] = []
    report = ingest_jamendo_ids(
        client, repo, ["1", 3, "1", "99"], stages=[], on_progress=events.append
    )

    assert client.lookups == [["1", "3", "99"]]  # deduplicated, one batch
    assert client.fetched == []  # no audio
    assert (report.seen, report.new, report.processed, report.skipped, report.failed) == (
        2,
        2,
        2,
        0,
        0,
    )
    track = repo.get_track_by_source("jamendo", "3")
    assert track is not None and track.title == "Track 3" and track.license_code == "CC BY 4.0"
    assert repo.get_track_by_source("jamendo", "2") is None  # not asked for
    assert repo.get_features(track.id) is None and repo.ingest_entries("jamendo", "3") == []
    done = [e for e in events if e.kind == "track_done"]
    assert [e.message.split(" (")[0] for e in done] == ["metadata only"] * 2
    assert events[0].kind == "started" and events[0].total == 3 and events[-1].kind == "finished"


def test_with_a_stage_the_audio_is_fetched_and_the_stage_runs(repo: CatalogRepository) -> None:
    client = ByIdClient([make_track(1), make_track(2)])
    analyzer = FakeAnalyzer()
    report = ingest_jamendo_ids(client, repo, ["1", "2"], stages=[AnalysisStage(analyzer)])
    assert (report.processed, report.failed) == (2, 0) and sorted(client.fetched) == ["1", "2"]
    assert analyzer.calls == 2
    again = ingest_jamendo_ids(client, repo, ["1"], stages=[AnalysisStage(analyzer)])
    assert again.skipped == 1 and analyzer.calls == 2  # up to date: nothing fetched again


def test_known_tracks_are_updated_and_an_auth_error_aborts_with_the_report(
    repo: CatalogRepository,
) -> None:
    client = ByIdClient([make_track(1)])
    ingest_jamendo_ids(client, repo, ["1"], stages=[])
    renamed = make_track(1, title="Renamed")
    second = ingest_jamendo_ids(ByIdClient([renamed]), repo, ["1"], stages=[])
    assert (second.new, second.updated) == (0, 1)
    assert repo.get_track_by_source("jamendo", "1").title == "Renamed"  # type: ignore[union-attr]

    failing = ByIdClient([], error=JamendoAuthError("bad id"))
    with pytest.raises(JamendoAuthError) as raised:
        ingest_jamendo_ids(failing, repo, ["5"], stages=[])
    assert raised.value.report.aborted is not None  # type: ignore[attr-defined]
