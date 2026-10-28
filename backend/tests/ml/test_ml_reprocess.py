"""reprocess_catalog: Jamendo URL refresh, local paths, shared audio, failures and aborts."""

from __future__ import annotations

from pathlib import Path

import pytest
from ml_support import (
    CountingStage,
    FakeJamendo,
    add_freesound,
    add_jamendo,
    add_local,
    write_wav,
)

from mcrar.catalog import CatalogRepository, TrackRecord
from mcrar.ingest import IngestEvent, reprocess_catalog
from mcrar.ingest.pipeline import REFRESH_BATCH
from mcrar.ml import EmbedderMemoryError
from mcrar.sources import (
    FreesoundAuthError,
    FreesoundStreamError,
    JamendoAuthError,
    JamendoRateLimitError,
    JamendoStreamError,
)


def test_refresh_batch_is_fifty() -> None:
    assert REFRESH_BATCH == 50


def test_jamendo_stream_urls_are_refreshed_in_batches_of_fifty(repo: CatalogRepository) -> None:
    ids = [add_jamendo(repo, n) for n in range(1, 121)]
    client = FakeJamendo()
    stage = CountingStage()
    report = reprocess_catalog(repo, stages=[stage], client=client)

    assert [len(call) for call in client.get_calls] == [50, 50, 20]
    assert client.get_calls[0] == [str(n) for n in range(1, 51)]
    assert client.get_calls[2] == [str(n) for n in range(101, 121)]
    assert (report.seen, report.processed, report.failed, report.new, report.updated) == (
        120,
        120,
        0,
        0,
        0,
    )
    assert stage.done == set(ids)
    # downloads used the refreshed URL of their own batch, never the stored (expired) one
    urls = dict(client.fetched)
    assert len(urls) == 120
    assert all("token=old" not in u for u in urls.values())
    assert urls["1"].endswith("token=fresh1")
    assert urls["60"].endswith("token=fresh2")
    assert urls["120"].endswith("token=fresh3")


def test_refreshing_is_lazy_so_urls_stay_fresh(repo: CatalogRepository) -> None:
    for n in range(1, 111):
        add_jamendo(repo, n)
    client = FakeJamendo()
    stage = CountingStage()
    seen_calls: list[int] = []
    original = stage.run

    def run(repo_: object, track_id: int, audio: object) -> None:
        seen_calls.append(len(client.get_calls))
        original(repo_, track_id, audio)

    stage.run = run  # type: ignore[method-assign]
    reprocess_catalog(repo, stages=[stage], client=client)
    # the second and third batches are requested only when the pipeline gets close to them
    assert seen_calls[0] == 1
    assert seen_calls[-1] == 3
    assert seen_calls == sorted(seen_calls)


def test_stored_metadata_is_left_alone(repo: CatalogRepository) -> None:
    track_id = add_jamendo(repo, 7)
    before = repo.get_track(track_id)
    reprocess_catalog(repo, stages=[CountingStage()], client=FakeJamendo())
    assert repo.get_track(track_id) == before


def test_local_tracks_use_their_stored_path_and_need_no_client(
    repo: CatalogRepository, tmp_path: Path
) -> None:
    paths = [write_wav(tmp_path / f"{n}.wav") for n in range(3)]
    for n, path in enumerate(paths):
        add_local(repo, f"{n}.wav", path)
    stage = CountingStage()
    report = reprocess_catalog(repo, stages=[stage])  # no client at all
    assert (report.processed, report.failed) == (3, 0)
    assert [kind for _, kind in stage.runs] == [type(paths[0])] * 3  # a Path, not bytes


def test_audio_is_fetched_once_for_two_stages(repo: CatalogRepository) -> None:
    for n in range(1, 4):
        add_jamendo(repo, n)
    client = FakeJamendo()
    one, two = CountingStage("embed:a"), CountingStage("embed:b")
    report = reprocess_catalog(repo, stages=[one, two], client=client)
    assert report.processed == 3
    assert sorted(i for i, _ in client.fetched) == ["1", "2", "3"]  # once per track, not per stage
    assert len(one.runs) == len(two.runs) == 3


def test_only_the_pending_stage_runs_and_all_current_tracks_are_skipped(
    repo: CatalogRepository,
) -> None:
    for n in range(1, 4):
        add_jamendo(repo, n)
    client = FakeJamendo()
    one, two = CountingStage("embed:a"), CountingStage("embed:b")
    reprocess_catalog(repo, stages=[one], client=client)
    client.get_calls.clear()
    client.fetched.clear()

    report = reprocess_catalog(repo, stages=[one, two], client=client)
    assert len(one.runs) == 3 and len(two.runs) == 3  # `one` did not run again
    assert report.processed == 3

    client.get_calls.clear()
    client.fetched.clear()
    again = reprocess_catalog(repo, stages=[one, two], client=client)
    assert (again.seen, again.skipped, again.processed) == (3, 3, 0)
    assert client.get_calls == [] and client.fetched == []  # no API call when nothing is pending


def test_force_reprocesses_current_tracks(repo: CatalogRepository) -> None:
    add_jamendo(repo, 1)
    client = FakeJamendo()
    stage = CountingStage()
    reprocess_catalog(repo, stages=[stage], client=client)
    forced = reprocess_catalog(repo, stages=[stage], client=client, force=True)
    assert forced.processed == 1
    assert len(stage.runs) == 2


def test_source_filter_and_limit(repo: CatalogRepository, tmp_path: Path) -> None:
    for n in range(1, 4):
        add_jamendo(repo, n)
    for n in range(3):
        add_local(repo, f"{n}.wav", write_wav(tmp_path / f"{n}.wav"))
    client = FakeJamendo()

    stage = CountingStage()
    only_local = reprocess_catalog(repo, stages=[stage], source="local")
    assert only_local.processed == 3 and client.get_calls == []

    limited = reprocess_catalog(repo, stages=[stage], client=client, source="jamendo", limit=2)
    assert limited.processed == 2
    assert client.get_calls == [["1", "2"]]  # only the limited tracks are refreshed


def test_limit_counts_tracks_that_need_work_not_current_ones(repo: CatalogRepository) -> None:
    ids = [add_jamendo(repo, n) for n in range(1, 6)]
    stage = CountingStage()
    stage.done.update(ids[:3])  # the first three are already done
    report = reprocess_catalog(repo, stages=[stage], client=FakeJamendo(), limit=1)
    assert (report.processed, report.skipped, report.seen) == (1, 3, 4)
    assert len(stage.runs) == 1 and stage.runs[0][0] == ids[3]


def test_progress_events_carry_title_and_total(repo: CatalogRepository) -> None:
    add_jamendo(repo, 1)
    add_jamendo(repo, 2)
    events: list[IngestEvent] = []
    reprocess_catalog(
        repo, stages=[CountingStage("embed:x")], client=FakeJamendo(), on_progress=events.append
    )
    assert [e.kind for e in events] == ["started", "track_done", "track_done", "finished"]
    done = [e for e in events if e.kind == "track_done"]
    assert [(e.index, e.total, e.title) for e in done] == [(1, 2, "Track 1"), (2, 2, "Track 2")]
    assert done[0].message == "embed:x (green)"


def test_ingest_log_rows_use_the_tracks_own_source(repo: CatalogRepository, tmp_path: Path) -> None:
    jid = add_jamendo(repo, 5)
    lid = add_local(repo, "x.wav", write_wav(tmp_path / "x.wav"))
    reprocess_catalog(repo, stages=[CountingStage("embed:x")], client=FakeJamendo())
    assert repo.get_ingest_status("jamendo", "5", "embed:x").status == "ok"  # type: ignore[union-attr]
    assert repo.get_ingest_status("local", "x.wav", "embed:x").track_id == lid  # type: ignore[union-attr]
    assert repo.get_ingest_status("jamendo", "5", "embed:x").track_id == jid  # type: ignore[union-attr]


# -- failures keep the run going --------------------------------------------------------------


def test_a_failed_download_is_logged_and_the_run_continues(repo: CatalogRepository) -> None:
    for n in range(1, 4):
        add_jamendo(repo, n)
    client = FakeJamendo(fetch_errors={"2": JamendoStreamError("HTTP 404 for track 2")})
    stage = CountingStage("embed:x")
    report = reprocess_catalog(repo, stages=[stage], client=client)
    assert (report.processed, report.failed) == (2, 1)
    (failure,) = report.failures
    assert (failure.source_id, failure.stage) == ("2", "embed:x")
    assert "JamendoStreamError" in failure.message
    assert repo.get_ingest_status("jamendo", "2", "embed:x").status == "failed"  # type: ignore[union-attr]
    # a later run retries only the failed track
    retry = reprocess_catalog(repo, stages=[stage], client=FakeJamendo())
    assert (retry.processed, retry.skipped) == (1, 2)


def test_a_track_missing_from_the_refresh_fails_alone(repo: CatalogRepository) -> None:
    for n in range(1, 4):
        add_jamendo(repo, n)
    report = reprocess_catalog(repo, stages=[CountingStage()], client=FakeJamendo(missing=[2]))
    assert (report.processed, report.failed) == (2, 1)
    assert report.failures[0].source_id == "2"
    assert "no longer available" in report.failures[0].message


def test_a_failing_refresh_fails_only_its_batch(repo: CatalogRepository) -> None:
    for n in range(1, 61):  # two batches: 50 + 10
        add_jamendo(repo, n)
    client = FakeJamendo(get_error=JamendoStreamError("HTTP 500"), get_error_on_call=1)
    report = reprocess_catalog(repo, stages=[CountingStage()], client=client)
    assert (report.processed, report.failed) == (10, 50)
    assert all("JamendoStreamError" in f.message for f in report.failures)
    assert report.aborted is None


def test_jamendo_tracks_without_a_client_fail_cleanly(
    repo: CatalogRepository, tmp_path: Path
) -> None:
    add_jamendo(repo, 1)
    add_local(repo, "x.wav", write_wav(tmp_path / "x.wav"))
    report = reprocess_catalog(repo, stages=[CountingStage()])
    assert (report.processed, report.failed) == (1, 1)
    assert "no Jamendo client" in report.failures[0].message


def test_missing_local_file_or_path_fails_the_track(
    repo: CatalogRepository, tmp_path: Path
) -> None:
    add_local(repo, "gone.wav", tmp_path / "gone.wav")  # never written
    add_local(repo, "nopath.wav", None)
    good = add_local(repo, "ok.wav", write_wav(tmp_path / "ok.wav"))
    stage = CountingStage()
    # a stage that really opens the file, like the embedding stage does
    from mcrar.audio import load_audio

    class Opening(CountingStage):
        def run(self, repo_: object, track_id: int, audio: object) -> None:
            load_audio(audio)  # type: ignore[arg-type]
            super().run(repo_, track_id, audio)

    stage = Opening("embed:x")
    report = reprocess_catalog(repo, stages=[stage])
    assert (report.processed, report.failed) == (1, 2)
    assert stage.done == {good}
    messages = {f.source_id: f.message for f in report.failures}
    assert "not found" in messages["gone.wav"]
    assert "no file path" in messages["nopath.wav"]


def test_a_failing_stage_does_not_stop_the_other_stages_or_tracks(
    repo: CatalogRepository,
) -> None:
    for n in range(1, 3):
        add_jamendo(repo, n)

    class Bad(CountingStage):
        def run(self, repo_: object, track_id: int, audio: object) -> None:
            raise ValueError("boom")

    good, bad = CountingStage("embed:good"), Bad("embed:bad")
    report = reprocess_catalog(repo, stages=[bad, good], client=FakeJamendo())
    assert report.failed == 2
    assert len(good.runs) == 2  # the other stage still ran for both tracks
    assert {f.stage for f in report.failures} == {"embed:bad"}


# -- aborts -----------------------------------------------------------------------------------


def test_an_auth_error_during_download_aborts_with_the_partial_report(
    repo: CatalogRepository,
) -> None:
    for n in range(1, 6):
        add_jamendo(repo, n)
    client = FakeJamendo(fetch_errors={"3": JamendoAuthError("bad client id")})
    stage = CountingStage()
    with pytest.raises(JamendoAuthError) as err:
        reprocess_catalog(repo, stages=[stage], client=client)
    report = err.value.report  # type: ignore[attr-defined]
    assert report.aborted is not None and "JamendoAuthError" in report.aborted
    assert report.processed == 2  # tracks 1 and 2 were done before the abort
    assert len(stage.runs) == 2


def test_an_auth_error_while_refreshing_aborts(repo: CatalogRepository) -> None:
    add_jamendo(repo, 1)
    client = FakeJamendo(get_error=JamendoRateLimitError("quota"), get_error_on_call=1)
    with pytest.raises(JamendoRateLimitError) as err:
        reprocess_catalog(repo, stages=[CountingStage()], client=client)
    assert err.value.report.processed == 0  # type: ignore[attr-defined]


def test_running_out_of_gpu_memory_aborts_instead_of_failing_every_track(
    repo: CatalogRepository,
) -> None:
    for n in range(1, 4):
        add_jamendo(repo, n)

    class OutOfMemory(CountingStage):
        def run(self, repo_: object, track_id: int, audio: object) -> None:
            raise EmbedderMemoryError("the GPU ran out of memory")

    with pytest.raises(EmbedderMemoryError) as err:
        reprocess_catalog(repo, stages=[OutOfMemory("embed:x")], client=FakeJamendo())
    assert err.value.report.failed == 0  # type: ignore[attr-defined]


def test_ctrl_c_returns_a_partial_report(repo: CatalogRepository) -> None:
    for n in range(1, 5):
        add_jamendo(repo, n)

    class Interrupting(CountingStage):
        interrupted = False

        def run(self, repo_: object, track_id: int, audio: object) -> None:
            if len(self.runs) == 1 and not self.interrupted:
                self.interrupted = True
                raise KeyboardInterrupt
            super().run(repo_, track_id, audio)

    stage = Interrupting()
    report = reprocess_catalog(repo, stages=[stage], client=FakeJamendo())
    assert report.aborted == "interrupted"
    assert report.processed == 1
    rerun = reprocess_catalog(repo, stages=[stage], client=FakeJamendo())
    assert rerun.aborted is None and rerun.processed == 3  # resumes where it stopped


def test_arguments_are_validated(repo: CatalogRepository) -> None:
    with pytest.raises(ValueError, match="at least one stage"):
        reprocess_catalog(repo, stages=[])
    with pytest.raises(ValueError, match="limit"):
        reprocess_catalog(repo, stages=[CountingStage()], limit=0)


def test_an_empty_catalog_is_a_clean_no_op(repo: CatalogRepository) -> None:
    report = reprocess_catalog(repo, stages=[CountingStage()], client=FakeJamendo())
    assert (report.seen, report.processed, report.failed, report.aborted) == (0, 0, 0, None)


# -- Freesound ----------------------------------------------------------------------------------


def test_freesound_previews_are_fetched_with_the_freesound_client_and_never_refreshed(
    repo: CatalogRepository,
) -> None:
    ids = [add_freesound(repo, n) for n in (1, 2)]
    add_jamendo(repo, 7)
    jamendo, freesound = FakeJamendo(), FakeJamendo()
    stage = CountingStage()
    report = reprocess_catalog(repo, stages=[stage], client=jamendo, freesound_client=freesound)
    assert (report.processed, report.failed) == (3, 0)
    assert stage.done >= set(ids)
    assert freesound.get_calls == []  # the stored preview URL is stable: no lookup
    assert dict(freesound.fetched) == {
        "1": "https://cdn.freesound.org/previews/1/1_1-hq.mp3",
        "2": "https://cdn.freesound.org/previews/2/2_1-hq.mp3",
    }
    assert [source_id for source_id, _ in jamendo.fetched] == ["7"]  # Jamendo kept its refresh
    assert jamendo.get_calls == [["7"]]
    assert repo.get_ingest_status("freesound", "1", "count").status == "ok"  # type: ignore[union-attr]


def test_source_filter_freesound_leaves_the_other_sources_alone(repo: CatalogRepository) -> None:
    add_freesound(repo, 1)
    add_jamendo(repo, 2)
    jamendo, freesound = FakeJamendo(), FakeJamendo()
    report = reprocess_catalog(
        repo,
        stages=[CountingStage()],
        client=jamendo,
        freesound_client=freesound,
        source="freesound",
    )
    assert (report.seen, report.processed) == (1, 1)
    assert jamendo.get_calls == [] and jamendo.fetched == []
    assert [i for i, _ in freesound.fetched] == ["1"]


def test_freesound_tracks_without_a_client_fail_cleanly(repo: CatalogRepository) -> None:
    add_freesound(repo, 1)
    add_jamendo(repo, 2)
    report = reprocess_catalog(repo, stages=[CountingStage()], client=FakeJamendo())
    assert (report.processed, report.failed, report.aborted) == (1, 1, None)
    (failure,) = report.failures
    assert failure.source_id == "1" and "no Freesound client" in failure.message
    entry = repo.get_ingest_status("freesound", "1", "count")
    assert entry is not None and entry.status == "failed"


def test_a_freesound_track_without_a_preview_url_fails_alone(repo: CatalogRepository) -> None:
    add_freesound(repo, 1)
    repo.upsert_track(
        TrackRecord(source="freesound", source_id="2", title="Sound 2", stream_url=None)
    )
    freesound = FakeJamendo()
    report = reprocess_catalog(repo, stages=[CountingStage()], freesound_client=freesound)
    assert (report.processed, report.failed) == (1, 1)
    assert report.failures[0].message == "no audio stream"
    assert [i for i, _ in freesound.fetched] == ["1"]


def test_a_freesound_auth_error_aborts_the_reprocess(repo: CatalogRepository) -> None:
    for n in range(1, 5):
        add_freesound(repo, n)
    freesound = FakeJamendo(fetch_errors={"3": FreesoundAuthError("bad key")})
    stage = CountingStage()
    with pytest.raises(FreesoundAuthError) as err:
        reprocess_catalog(repo, stages=[stage], freesound_client=freesound)
    report = err.value.report  # type: ignore[attr-defined]
    assert report.aborted is not None and "FreesoundAuthError" in report.aborted
    assert report.processed == 2 and len(stage.runs) == 2


def test_a_freesound_download_error_fails_only_its_track(repo: CatalogRepository) -> None:
    for n in range(1, 4):
        add_freesound(repo, n)
    freesound = FakeJamendo(fetch_errors={"2": FreesoundStreamError("HTTP 404")})
    report = reprocess_catalog(repo, stages=[CountingStage()], freesound_client=freesound)
    assert (report.processed, report.failed) == (2, 1)
    assert "FreesoundStreamError" in report.failures[0].message
