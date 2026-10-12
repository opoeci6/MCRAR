"""Offline streaming download and integrity tests, including interrupted resumes."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import httpx
import pytest

from mcrar.ml.datasets.download import download_verified, extract_zip, verify


def test_verified_resume_and_no_second_download(tmp_path: Path) -> None:
    content = b"publisher data" * 100
    path = tmp_path / "archive.zip"
    path.with_suffix(".zip.part").write_bytes(content[:17])
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["range"] == "bytes=17-"
        return httpx.Response(
            206,
            content=content[17:],
            headers={"content-range": f"bytes 17-{len(content) - 1}/{len(content)}"},
        )

    sha = hashlib.sha256(content).hexdigest()
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        download_verified("https://example.org/data", path, sha, client=client)
        download_verified("https://example.org/data", path, sha, client=client)
    assert path.read_bytes() == content and len(calls) == 1
    with pytest.raises(ValueError, match="mismatch"):
        verify(path, "0" * 64)


def test_ignored_range_restarts_and_bad_checksum_never_publishes(tmp_path: Path) -> None:
    path = tmp_path / "data.zip"
    path.with_suffix(".zip.part").write_bytes(b"partial")
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"all"))
    ) as c:
        download_verified(
            "https://example.org/data", path, hashlib.sha256(b"all").hexdigest(), client=c
        )
        with pytest.raises(ValueError, match="mismatch"):
            download_verified("https://example.org/data", tmp_path / "bad.zip", "0" * 64, client=c)
    assert path.read_bytes() == b"all"
    assert not (tmp_path / "bad.zip").exists()


def test_range_offset_and_safe_zip_extraction(tmp_path: Path) -> None:
    path = tmp_path / "a.zip"
    path.with_suffix(".zip.part").write_bytes(b"x")
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(206, content=b"x", headers={"content-range": "bytes 0-0/1"})
        )
    ) as c:
        with pytest.raises(ValueError, match="Content-Range"):
            download_verified("https://example.org/data", path, "0" * 64, client=c)
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("../escape.txt", "bad")
    path.write_bytes(data.getvalue())
    with pytest.raises(ValueError, match="unsafe"):
        extract_zip(path, tmp_path / "extract")
    assert not (tmp_path / "escape.txt").exists()


def test_transient_server_retry_preserves_verified_resume(tmp_path: Path, monkeypatch) -> None:
    from mcrar.ml.datasets import download as module

    calls, waits = [], []
    monkeypatch.setattr(module.time, "sleep", waits.append)

    def respond(request):
        calls.append(request)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, content=b"ok")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        download_verified(
            "https://example.org/data",
            tmp_path / "data.bin",
            hashlib.sha256(b"ok").hexdigest(),
            client=client,
        )
    assert len(calls) == 2 and waits == [1]


def test_upstream_tar_unpacking_cannot_escape_the_repo(tmp_path: Path) -> None:
    import tarfile

    from mcrar.ml.datasets.download import validate_tar_paths

    path = tmp_path / "unsafe.tar"
    with tarfile.open(path, "w") as archive:
        member = tarfile.TarInfo("../outside.mp3")
        member.size = 4
        archive.addfile(member, io.BytesIO(b"fake"))
    with pytest.raises(ValueError, match="unsafe tar"):
        validate_tar_paths(path, tmp_path / "audio")
