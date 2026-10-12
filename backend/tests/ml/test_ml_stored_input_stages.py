"""Stages with ``needs_audio = False`` run on stored data: no download, no URL refresh."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ml_support import CountingStage, FakeJamendo, add_jamendo, add_local, write_wav

from mcrar.catalog import CatalogRepository
from mcrar.ingest import ingest_local, needs_audio, reprocess_catalog
from mcrar.sources import JamendoStreamError


class StoredStage(CountingStage):
    """Reads what an earlier stage stored (like tagging from an embedding)."""

    needs_audio = False

    def __init__(self, name: str = "tag:test", requires: CountingStage | None = None) -> None:
        super().__init__(name)
        self.requires = requires

    def run(self, repo: Any, track_id: int, audio: object) -> None:
        assert audio is None
        if self.requires is not None and track_id not in self.requires.done:
            raise RuntimeError("no stored input")
        super().run(repo, track_id, audio)


def test_needs_audio_defaults_to_true() -> None:
    assert needs_audio(CountingStage()) is True
    assert needs_audio(StoredStage()) is False


def test_stored_stage_alone_downloads_and_refreshes_nothing(repo: CatalogRepository) -> None:
    for n in range(1, 4):
        add_jamendo(repo, n)
    client = FakeJamendo()
    stage = StoredStage()
    report = reprocess_catalog(repo, stages=[stage], client=client)
    assert (report.processed, report.failed) == (3, 0)
    assert client.get_calls == [] and client.fetched == []
    assert [kind for _, kind in stage.runs] == [type(None)] * 3


def test_stored_stage_runs_after_the_audio_stage_in_the_same_pass(
    repo: CatalogRepository,
) -> None:
    for n in range(1, 4):
        add_jamendo(repo, n)
    client = FakeJamendo()
    embed = CountingStage("embed:x")
    tag = StoredStage(requires=embed)
    report = reprocess_catalog(repo, stages=[embed, tag], client=client)
    assert (report.processed, report.failed) == (3, 0)
    assert sorted(i for i, _ in client.fetched) == ["1", "2", "3"]  # once per track
    assert tag.done == embed.done


def test_only_tracks_with_a_pending_audio_stage_are_refreshed(repo: CatalogRepository) -> None:
    ids = [add_jamendo(repo, n) for n in range(1, 5)]
    embed = CountingStage("embed:x")
    embed.done.update(ids[:2])  # tracks 1 and 2 are already embedded
    tag = StoredStage(requires=embed)
    client = FakeJamendo()
    reprocess_catalog(repo, stages=[embed, tag], client=client)
    assert client.get_calls == [["3", "4"]]
    assert sorted(i for i, _ in client.fetched) == ["3", "4"]
    assert tag.done == set(ids)


def test_a_failed_download_fails_the_audio_stage_but_not_a_stored_stage_with_input(
    repo: CatalogRepository,
) -> None:
    track = add_jamendo(repo, 1)
    embed = CountingStage("embed:x")
    tag = StoredStage()  # its input exists independently of this download
    client = FakeJamendo(fetch_errors={"1": JamendoStreamError("gone")})
    report = reprocess_catalog(repo, stages=[embed, tag], client=client)
    assert report.failed == 1
    assert [f.stage for f in report.failures] == ["embed:x"]
    assert tag.done == {track}


def test_stored_stage_on_local_files_gets_no_path(repo: CatalogRepository, tmp_path: Path) -> None:
    add_local(repo, "a.wav", write_wav(tmp_path / "a.wav"))
    stage = StoredStage()
    report = reprocess_catalog(repo, stages=[stage])
    assert report.processed == 1
    assert stage.runs[0][1] is type(None)


def test_ingest_local_passes_none_to_stored_stages(repo: CatalogRepository, tmp_path: Path) -> None:
    write_wav(tmp_path / "pack" / "a.wav")
    audio_stage, stored = CountingStage("embed:x"), StoredStage()
    report = ingest_local(tmp_path / "pack", repo, stages=[audio_stage, stored])
    assert (report.processed, report.failed) == (1, 0)
    assert audio_stage.runs[0][1] is not type(None)
    assert stored.runs[0][1] is type(None)
