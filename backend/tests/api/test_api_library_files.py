"""Copying files into the library folder (``POST /api/library/files``) and adding them to the
catalog (``POST /api/ingest/files``)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from api_support import ApiClient, make_client, wait_done
from recommend_support import MODEL_ID, fake_features, write_wav

from mcrar.api.routes import library_files
from mcrar.ingest import pipeline
from mcrar.sources.local_folder import file_sha256


@pytest.fixture(autouse=True)
def fast_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "analyze_audio", fake_features)


def library(client: ApiClient) -> Path:
    return client.settings.data_dir / "library"


def upload(client: ApiClient, data: bytes, name: str = "song.wav"):  # noqa: ANN201
    return client.post("/api/library/files", params={"name": name}, content=data)


def wav_bytes(tmp_path: Path, freq: float) -> bytes:
    return write_wav(tmp_path / "src" / f"{freq}.wav", freq=freq).read_bytes()


def stored(client: ApiClient) -> list[str]:
    """The names of the files in the library folder (not the ``.incoming`` folder inside it)."""
    folder = library(client)
    return [p.name for p in folder.iterdir() if p.is_file()] if folder.is_dir() else []


def incoming(client: ApiClient) -> list[Path]:
    folder = library(client) / ".incoming"
    return list(folder.iterdir()) if folder.is_dir() else []


# -- upload --------------------------------------------------------------------------------------


def test_an_upload_is_stored_under_its_hash(tmp_path: Path) -> None:
    data = wav_bytes(tmp_path, 330.0)
    with make_client(tmp_path) as client:
        response = upload(client, data, "My Song.WAV")
        assert response.status_code == 201, response.text
        body = response.json()
        copy = library(client) / body["file"]
        assert copy.read_bytes() == data
        assert body["file"] == f"{file_sha256(copy)}.wav"  # the hash of the final file, .wav
        assert (body["name"], body["size"], body["already"]) == ("My Song.WAV", len(data), False)
        assert stored(client) == [body["file"]]
        assert incoming(client) == []


def test_the_same_bytes_again_are_already_there(tmp_path: Path) -> None:
    data = wav_bytes(tmp_path, 330.0)
    with make_client(tmp_path) as client:
        first = upload(client, data, "one.wav").json()
        again = upload(client, data, "two.wav")
        assert again.status_code == 200
        assert again.json() == {
            "file": first["file"],
            "name": "two.wav",
            "size": len(data),
            "already": True,
        }
        assert stored(client) == [first["file"]]
        assert incoming(client) == []


def test_a_name_with_path_parts_is_reduced_to_its_base_name(tmp_path: Path) -> None:
    data = wav_bytes(tmp_path, 330.0)
    with make_client(tmp_path) as client:
        for name in ("C:\\Users\\me\\Music\\x.wav", "../../etc/x.wav", "/abs/x.wav"):
            body = upload(client, data, name).json()
            assert body["name"] == "x.wav" and "/" not in body["file"] and "\\" not in body["file"]
        assert len(stored(client)) == 1


@pytest.mark.parametrize("name", ["notes.txt", "noextension", "", "C:\\music\\", ".wav", "x.exe"])
def test_a_name_that_is_not_audio_is_422(tmp_path: Path, name: str) -> None:
    with make_client(tmp_path) as client:
        response = upload(client, b"data", name)
        assert response.status_code == 422, response.text
        assert stored(client) == []


def test_an_empty_upload_is_422_and_leaves_nothing(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert upload(client, b"").status_code == 422
        assert incoming(client) == []
        assert not stored(client)


def test_a_missing_name_is_422(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert client.post("/api/library/files", content=b"data").status_code == 422


def test_an_upload_over_the_limit_is_413_and_leaves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(library_files, "MAX_LIBRARY_FILE_BYTES", 1000)
    with make_client(tmp_path) as client:
        response = upload(client, b"x" * 1001)
        assert response.status_code == 413, response.text
        assert incoming(client) == []
        assert not stored(client)
        assert upload(client, b"x" * 1000).status_code == 201  # exactly the limit is fine


def test_the_limit_also_stops_a_body_without_a_content_length(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(library_files, "MAX_LIBRARY_FILE_BYTES", 1000)

    def chunks():  # noqa: ANN202
        for _ in range(5):
            yield b"x" * 400  # a generator body is sent chunked: no Content-Length

    with make_client(tmp_path) as client:
        response = client.post("/api/library/files", params={"name": "big.wav"}, content=chunks())
        assert response.status_code == 413, response.text
        assert incoming(client) == []
        assert not stored(client)


def test_a_failed_write_removes_the_part_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(source: Path, target: Path) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(library_files.os, "replace", broken)
    with make_client(tmp_path) as client:
        with pytest.raises(OSError, match="disk full"):
            upload(client, b"data")
        assert incoming(client) == [] and stored(client) == []


# -- ingest --------------------------------------------------------------------------------------


def upload_two(client: ApiClient, tmp_path: Path) -> list[dict]:
    return [
        upload(client, wav_bytes(tmp_path, 330.0), "First Song.wav").json(),
        upload(client, wav_bytes(tmp_path, 550.0), "C:\\x\\Second.wav").json(),
    ]


def entries(uploaded: list[dict]) -> list[dict]:
    return [{"file": u["file"], "title": Path(u["name"]).stem} for u in uploaded]


def test_ingest_of_copied_files_adds_tracks_titled_by_the_original_names(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        uploaded = upload_two(client, tmp_path)
        response = client.post(
            "/api/ingest/files", json={"files": entries(uploaded), "license": "CC BY 4.0"}
        )
        assert response.status_code == 202, response.text
        job = response.json()["job"]
        assert job["kind"] == "ingest-files"
        done = wait_done(client, job["id"])
        assert done["status"] == "done", done
        assert (done["report"]["new"], done["report"]["processed"]) == (2, 2)
        for item in uploaded:
            sha = item["file"].split(".")[0]
            track = client.repo.get_track_by_source("local", sha)
            assert track is not None
            assert track.title == Path(item["name"]).stem and track.album is None
            assert track.local_path == str(library(client) / item["file"])
            assert track.license_code == "CC BY 4.0"
            assert client.repo.get_embedding(track.id, MODEL_ID) is not None
        assert client.get(f"/api/tracks/{track.id}/stream").status_code == 200


def test_ingest_without_a_licence_is_unknown_and_a_rerun_skips(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        body = {"files": entries(upload_two(client, tmp_path))}
        first = wait_done(client, client.post("/api/ingest/files", json=body).json()["job"]["id"])
        assert first["report"]["new"] == 2
        track = client.repo.get_track_by_source("local", body["files"][0]["file"].split(".")[0])
        assert track is not None and track.risk == "unknown"
        again = wait_done(client, client.post("/api/ingest/files", json=body).json()["job"]["id"])
        assert (again["report"]["new"], again["report"]["processed"]) == (0, 0)
        assert again["report"]["skipped"] == 2


def test_ingest_can_skip_embedding(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        body = {"files": entries(upload_two(client, tmp_path)), "embed": False}
        done = wait_done(client, client.post("/api/ingest/files", json=body).json()["job"]["id"])
        assert done["status"] == "done" and client.loader.keys == []


GOOD = "a" * 64 + ".wav"


@pytest.mark.parametrize(
    "bad",
    [
        {"files": []},
        {"files": [{"file": "../x.wav", "title": "t"}]},
        {"files": [{"file": "song.wav", "title": "t"}]},
        {"files": [{"file": ("A" * 64) + ".wav", "title": "t"}]},
        {"files": [{"file": GOOD + "\n", "title": "t"}]},
        {"files": [{"file": GOOD, "title": ""}]},
        {"files": [{"file": GOOD, "title": "t" * 301}]},
        {"files": [{"file": GOOD, "title": "t", "extra": 1}]},
        {"files": [{"file": GOOD, "title": "t"}], "surprise": True},
        {"files": [{"file": GOOD, "title": "t"}] * 1001},
        {"files": [{"file": GOOD, "title": "t"}], "license": "not a licence at all"},
    ],
    ids=[
        "empty",
        "path",
        "no-hash",
        "uppercase",
        "newline",
        "no-title",
        "long-title",
        "extra-entry-field",
        "extra-field",
        "too-many",
        "bad-licence",
    ],
)
def test_ingest_rejects_bad_bodies_with_422(tmp_path: Path, bad: dict) -> None:
    with make_client(tmp_path) as client:
        wav = upload(client, wav_bytes(tmp_path, 330.0)).json()["file"]
        if "license" in bad:  # the file exists: only the licence is wrong
            bad = {**bad, "files": [{"file": wav, "title": "t"}]}
        assert client.post("/api/ingest/files", json=bad).status_code == 422
        assert client.get("/api/jobs").json() == {"jobs": []}


def test_ingest_of_a_file_that_is_not_in_the_library_is_422(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        known = upload(client, wav_bytes(tmp_path, 330.0)).json()["file"]
        body = {"files": [{"file": known, "title": "ok"}, {"file": GOOD, "title": "gone"}]}
        response = client.post("/api/ingest/files", json=body)
        assert response.status_code == 422 and GOOD in response.json()["detail"]
        assert client.get("/api/jobs").json() == {"jobs": []}


def test_ingest_files_while_a_job_runs_is_409(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reached, go = threading.Event(), threading.Event()

    def gate(source: object, *, max_seconds: float | None = None):  # noqa: ANN202
        reached.set()
        assert go.wait(20), "the test never opened the gate"
        return fake_features(source)

    monkeypatch.setattr(pipeline, "analyze_audio", gate)
    with make_client(tmp_path) as client:
        body = {"files": entries(upload_two(client, tmp_path)), "embed": False}
        first = client.post("/api/ingest/files", json=body).json()["job"]["id"]
        try:
            assert reached.wait(20)
            busy = client.post("/api/ingest/files", json=body)
            assert busy.status_code == 409 and first in busy.json()["detail"]
        finally:
            go.set()
        assert wait_done(client, first)["status"] == "done"
