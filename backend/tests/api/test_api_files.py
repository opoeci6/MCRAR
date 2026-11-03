"""The folder browser (``/api/files/...``) and the ``local_files`` flag of ``/api/health``."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from api_support import make_client

from mcrar.api.routes import files as files_routes
from mcrar.api.security import is_loopback_host


def make_tree(tmp_path: Path) -> Path:
    root = tmp_path / "browse"
    for name in ("beta", "Alpha", "gamma", ".hidden"):
        (root / name).mkdir(parents=True)
    for name in ("a.wav", "B.MP3", "c.Flac", "notes.txt", ".secret.wav"):
        (root / name).write_bytes(b"x")
    (root / "beta" / "inner.wav").write_bytes(b"x")  # not recursive: never counted
    return root


def test_roots_lists_the_drives_and_the_usual_places(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        body = client.get("/api/files/roots").json()
    assert set(body) == {"roots", "places"} and body["roots"]
    for entry in body["roots"] + body["places"]:
        assert set(entry) == {"name", "path"} and Path(entry["path"]).is_dir()
    if os.name == "nt":
        assert all(r["path"][1:] == ":\\" and r["name"] == r["path"] for r in body["roots"])
    else:
        assert body["roots"] == [{"name": "/", "path": "/"}]
    assert {p["path"] for p in body["places"]} <= {str(Path.home()), str(Path.home() / "Music")}


def test_list_a_folder(tmp_path: Path) -> None:
    root = make_tree(tmp_path)
    with make_client(tmp_path) as client:
        response = client.get("/api/files/list", params={"path": str(root)})
    assert response.status_code == 200, response.text
    assert response.json() == {
        "path": str(root.resolve()),
        "parent": str(root.resolve().parent),
        "folders": [
            {"name": "Alpha", "path": str(root.resolve() / "Alpha")},
            {"name": "beta", "path": str(root.resolve() / "beta")},
            {"name": "gamma", "path": str(root.resolve() / "gamma")},
        ],
        "audio_files": 3,  # a.wav, B.MP3, c.Flac; not notes.txt, not the hidden one
        "truncated": False,
    }


@pytest.mark.skipif(os.name != "nt", reason="file attributes are Windows-only")
def test_folders_and_files_windows_hides_are_left_out(tmp_path: Path) -> None:
    import ctypes

    root = make_tree(tmp_path)
    (root / "AppData").mkdir()
    (root / "hidden.wav").write_bytes(b"x")
    for name, attributes in (("AppData", 0x2), ("gamma", 0x4), ("hidden.wav", 0x2)):
        assert ctypes.windll.kernel32.SetFileAttributesW(str(root / name), attributes)
    with make_client(tmp_path) as client:
        body = client.get("/api/files/list", params={"path": str(root)}).json()
    assert [f["name"] for f in body["folders"]] == ["Alpha", "beta"]
    assert body["audio_files"] == 3


def test_a_listed_folder_can_be_listed_in_turn_and_a_root_has_no_parent(tmp_path: Path) -> None:
    root = make_tree(tmp_path)
    with make_client(tmp_path) as client:
        inner = client.get("/api/files/list", params={"path": str(root / "beta")}).json()
        assert inner["audio_files"] == 1 and inner["folders"] == []
        assert inner["parent"] == str(root.resolve())
        top = Path(root.resolve().anchor)
        listing = client.get("/api/files/list", params={"path": str(top)})
        assert listing.status_code == 200 and listing.json()["parent"] is None


def test_the_listing_is_capped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_tree(tmp_path)
    monkeypatch.setattr(files_routes, "MAX_ENTRIES", 2)
    with make_client(tmp_path) as client:
        body = client.get("/api/files/list", params={"path": str(root)}).json()
    assert body["truncated"] is True
    assert len(body["folders"]) + body["audio_files"] <= 2


@pytest.mark.parametrize("bad", ["relative", "missing", "file", "empty"])
def test_list_rejects_bad_paths_with_422(tmp_path: Path, bad: str) -> None:
    root = make_tree(tmp_path)
    path = {
        "relative": "browse",
        "missing": str(root / "nope"),
        "file": str(root / "a.wav"),
        "empty": "",
    }[bad]
    with make_client(tmp_path) as client:
        response = client.get("/api/files/list", params={"path": path})
        assert response.status_code == 422, response.text


def test_list_without_a_path_is_422(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert client.get("/api/files/list").status_code == 422


def test_an_unreadable_folder_is_a_plain_422(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_tree(tmp_path)

    def denied(path: object) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(files_routes.os, "scandir", denied)
    with make_client(tmp_path) as client:
        response = client.get("/api/files/list", params={"path": str(root)})
    assert response.status_code == 422 and "cannot read" in response.json()["detail"]


def test_no_listing_for_a_server_that_is_not_loopback_only(tmp_path: Path) -> None:
    root = make_tree(tmp_path)
    with make_client(tmp_path, settings_overrides={"api_host": "0.0.0.0"}) as client:
        for response in (
            client.get("/api/files/roots"),
            client.get("/api/files/list", params={"path": str(root)}),
        ):
            assert response.status_code == 403
            assert "loopback" in response.json()["detail"]


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("localhost", True),
        ("::1", True),
        ("0.0.0.0", False),
        ("lan.test", False),
    ],
)
def test_health_says_whether_local_files_can_be_browsed(
    tmp_path: Path, host: str, expected: bool
) -> None:
    with make_client(tmp_path, settings_overrides={"api_host": host}) as client:
        response = client.get("/api/health", headers={"Host": "127.0.0.1"})
        assert response.json()["local_files"] is expected


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("127.0.0.2", True),
        ("localhost", True),
        ("LocalHost", True),
        ("::1", True),
        ("[::1]", True),
        (" 127.0.0.1 ", True),
        ("0.0.0.0", False),
        ("::", False),
        ("", False),
        ("192.168.1.20", False),
        ("example.com", False),
    ],
)
def test_is_loopback_host(host: str, expected: bool) -> None:
    assert is_loopback_host(host) is expected
