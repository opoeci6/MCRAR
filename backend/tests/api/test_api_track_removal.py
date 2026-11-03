"""Removing tracks: the preview, the delete (and its library file), and the missing-file sweep."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from api_support import ApiClient, make_client, wait_done
from recommend_support import fake_features, write_wav

from mcrar.catalog import TrackRecord
from mcrar.ingest import pipeline


def add_local(client: ApiClient, name: str, path: Path | None) -> int:
    return client.repo.upsert_track(
        TrackRecord(
            source="local",
            source_id=name,
            title=name,
            local_path=None if path is None else str(path),
        )
    )


def add_library_track(client: ApiClient, name: str) -> tuple[int, Path]:
    """A local track whose file is a copy inside ``<data_dir>/library``."""
    path = write_wav(client.settings.data_dir / "library" / f"{name}.wav")
    return add_local(client, name, path), path


def decorate(client: ApiClient, track_id: int) -> None:
    """A rating, a scene label and a shortlist entry in two projects for the track."""
    client.repo.set_rating("q1", track_id, 2)
    client.repo.set_rating("q2", track_id, 1)
    client.repo.set_scene_label(track_id, "me", ["stealth"], "low", "labelled")
    for name in ("Game A", "Game B"):
        client.repo.add_to_shortlist(client.repo.create_project(name), track_id, note="keep")


# -- preview -------------------------------------------------------------------------------------


def test_the_preview_counts_what_would_go_with_the_track(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        track_id, _ = add_library_track(client, "mine")
        assert client.get(f"/api/tracks/{track_id}/removal").json() == {
            "ratings": 0,
            "scene_labels": 0,
            "projects": 0,
            "copied_file": True,
        }
        decorate(client, track_id)
        assert client.get(f"/api/tracks/{track_id}/removal").json() == {
            "ratings": 2,
            "scene_labels": 1,
            "projects": 2,
            "copied_file": True,
        }


def test_the_preview_says_no_copied_file_for_other_tracks(tmp_path: Path) -> None:
    outside = write_wav(tmp_path / "elsewhere" / "x.wav")
    with make_client(tmp_path) as client:
        browsed = add_local(client, "browsed", outside)
        no_path = add_local(client, "nopath", None)
        jamendo = client.ids["Shadow Walk"]
        for track_id in (browsed, no_path, jamendo):
            body = client.get(f"/api/tracks/{track_id}/removal").json()
            assert body["copied_file"] is False, track_id


def test_a_path_that_climbs_out_of_the_library_is_not_a_copy(tmp_path: Path) -> None:
    outside = write_wav(tmp_path / "elsewhere" / "x.wav")
    with make_client(tmp_path) as client:
        library = client.settings.data_dir / "library"
        sneaky = library / ".." / ".." / "elsewhere" / "x.wav"
        track_id = add_local(client, "sneaky", sneaky)
        assert client.get(f"/api/tracks/{track_id}/removal").json()["copied_file"] is False
        assert client.delete(f"/api/tracks/{track_id}").status_code == 204
        assert outside.is_file()


def test_preview_and_delete_of_an_unknown_track_are_404(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert client.get("/api/tracks/99999/removal").status_code == 404
        assert client.delete("/api/tracks/99999").status_code == 404


# -- delete --------------------------------------------------------------------------------------


def test_delete_removes_the_track_its_data_and_the_library_copy(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        track_id, path = add_library_track(client, "mine")
        decorate(client, track_id)
        client.app.state.mcrar.stream_urls.put(track_id, "https://example.test/x")
        before = client.get("/api/tracks").json()["total"]
        response = client.delete(f"/api/tracks/{track_id}")
        assert response.status_code == 204 and response.content == b""
        assert not path.exists()
        assert client.get(f"/api/tracks/{track_id}").status_code == 404
        assert client.get("/api/tracks").json()["total"] == before - 1
        assert client.app.state.mcrar.stream_urls.get(track_id) is None
        assert client.repo.iter_scene_labels() == []
        assert client.repo.iter_ratings() == []
        assert client.repo.shortlist_counts() == {}
        assert client.delete(f"/api/tracks/{track_id}").status_code == 404  # gone for good


def test_delete_keeps_a_browsed_file_outside_the_library(tmp_path: Path) -> None:
    outside = write_wav(tmp_path / "elsewhere" / "x.wav")
    with make_client(tmp_path) as client:
        track_id = add_local(client, "browsed", outside)
        assert client.delete(f"/api/tracks/{track_id}").status_code == 204
        assert client.get(f"/api/tracks/{track_id}").status_code == 404
        assert outside.is_file()


def test_delete_of_a_track_whose_library_file_is_already_gone_works(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        track_id, path = add_library_track(client, "mine")
        path.unlink()
        assert client.delete(f"/api/tracks/{track_id}").status_code == 204


def test_delete_of_a_remote_track_touches_no_file(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        track_id = client.ids["Shadow Walk"]
        assert client.delete(f"/api/tracks/{track_id}").status_code == 204
        assert client.get(f"/api/tracks/{track_id}").status_code == 404


@pytest.fixture
def busy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """A client whose job manager has a job running until the test lets it go."""
    reached, go = threading.Event(), threading.Event()

    def gate(source: object, *, max_seconds: float | None = None):  # noqa: ANN202
        reached.set()
        assert go.wait(20), "the test never opened the gate"
        return fake_features(source)

    monkeypatch.setattr(pipeline, "analyze_audio", gate)
    folder = tmp_path / "music"
    write_wav(folder / "a.wav", freq=330.0)
    with make_client(tmp_path) as client:
        job = client.post("/api/ingest/local", json={"path": str(folder), "embed": False})
        job_id = job.json()["job"]["id"]
        try:
            assert reached.wait(20)
            yield client
        finally:
            go.set()
        wait_done(client, job_id)


def test_delete_and_remove_missing_are_409_while_a_job_runs(busy: ApiClient) -> None:
    track_id, path = add_library_track(busy, "mine")
    gone = add_local(busy, "gone", busy.settings.data_dir / "nowhere.wav")
    response = busy.delete(f"/api/tracks/{track_id}")
    assert response.status_code == 409 and "job is running" in response.json()["detail"]
    assert busy.post("/api/tracks/remove-missing").status_code == 409
    assert path.is_file() and busy.get(f"/api/tracks/{track_id}").status_code == 200
    assert busy.get(f"/api/tracks/{gone}").status_code == 200


# -- missing -------------------------------------------------------------------------------------


def baseline_missing(client: ApiClient) -> int:
    """The synthetic catalog's two local tracks have no file path: they count as missing."""
    return client.get("/api/tracks/missing").json()["count"]


def test_missing_lists_only_local_tracks_without_a_file(tmp_path: Path) -> None:
    present = write_wav(tmp_path / "here" / "p.wav")
    with make_client(tmp_path) as client:
        base = baseline_missing(client)
        assert base == 2  # "Chip Hero" and "Local Ambient" have no path in the test catalog
        add_local(client, "present", present)
        gone = add_local(client, "gone", tmp_path / "here" / "gone.wav")
        folder = add_local(client, "folder", tmp_path / "here")  # a folder is not a file
        body = client.get("/api/tracks/missing").json()
        assert body["count"] == base + 2
        by_id = {t["id"]: t for t in body["tracks"]}
        assert set(by_id[gone]) == {"id", "title", "local_path"}
        assert by_id[gone]["title"] == "gone"
        assert by_id[gone]["local_path"] == str(tmp_path / "here" / "gone.wav")
        assert folder in by_id and "present" not in {t["title"] for t in body["tracks"]}
        assert client.get("/api/tracks/missing").status_code == 200  # not read as a track id


def test_missing_caps_the_list_but_counts_them_all(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        base = baseline_missing(client)
        for n in range(205):
            add_local(client, f"m{n}", tmp_path / f"m{n}.wav")
        body = client.get("/api/tracks/missing").json()
        assert body["count"] == base + 205 and len(body["tracks"]) == 200


def test_remove_missing_removes_those_and_keeps_the_rest(tmp_path: Path) -> None:
    present = write_wav(tmp_path / "here" / "p.wav")
    with make_client(tmp_path) as client:
        base = baseline_missing(client)
        keep = add_local(client, "present", present)
        library_id, library_path = add_library_track(client, "mine")
        gone = add_local(client, "gone", tmp_path / "here" / "gone.wav")
        decorate(client, gone)
        total = client.get("/api/tracks").json()["total"]
        response = client.post("/api/tracks/remove-missing")
        assert response.status_code == 200 and response.json() == {"removed": base + 1}
        assert client.get(f"/api/tracks/{gone}").status_code == 404
        assert client.get(f"/api/tracks/{keep}").status_code == 200
        assert client.get(f"/api/tracks/{library_id}").status_code == 200 and library_path.is_file()
        assert client.get(f"/api/tracks/{client.ids['Shadow Walk']}").status_code == 200
        assert client.get("/api/tracks").json()["total"] == total - base - 1
        assert client.get("/api/tracks/missing").json() == {"count": 0, "tracks": []}
        assert client.post("/api/tracks/remove-missing").json() == {"removed": 0}
        assert present.is_file()


def test_the_missing_routes_do_not_clash_with_the_track_id_routes(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert client.get("/api/tracks/missing").json().keys() == {"count", "tracks"}
        assert client.delete("/api/tracks/missing").status_code == 422  # not a track id
        assert client.get("/api/tracks/1").status_code in (200, 404)
