"""Streaming checksum validation, HTTP Range resume and safe archive extraction."""

from __future__ import annotations

import hashlib
import json
import re
import tarfile
import time
import zipfile
from pathlib import Path

import httpx


def digest(path: Path, algorithm: str = "sha256") -> str:
    checksum = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def verify(path: Path, expected: str, algorithm: str = "sha256") -> None:
    actual = digest(path, algorithm)
    if actual.lower() != expected.lower():
        raise ValueError(f"{algorithm} mismatch for {path.name}: expected {expected}, got {actual}")


def _download_once(
    url: str,
    path: Path,
    expected: str,
    *,
    algorithm: str = "sha256",
    client: httpx.Client | None = None,
) -> Path:
    if path.is_file():
        verify(path, expected, algorithm)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    offset = partial.stat().st_size if partial.exists() else 0
    if client is None:
        with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(120, connect=30)) as own:
            return _download_once(url, path, expected, algorithm=algorithm, client=own)
    with client.stream("GET", url, headers={"Range": f"bytes={offset}-"} if offset else {}) as r:
        if r.status_code == 416 and offset:
            verify(partial, expected, algorithm)
        else:
            r.raise_for_status()
            if r.status_code == 206:
                match = re.fullmatch(
                    r"bytes (\d+)-(\d+)/(\d+|\*)", r.headers.get("content-range", "")
                )
                if match is None or int(match[1]) != offset:
                    raise ValueError("server returned an invalid Content-Range")
            mode = "ab" if offset and r.status_code == 206 else "wb"
            with partial.open(mode) as stream:
                for chunk in r.iter_bytes(1024 * 1024):
                    stream.write(chunk)
            verify(partial, expected, algorithm)
    partial.replace(path)
    return path


def download_verified(
    url: str,
    path: Path,
    expected: str,
    *,
    algorithm: str = "sha256",
    client: httpx.Client | None = None,
) -> Path:
    """Retry transient transfers from the saved Range offset; integrity failures never retry."""
    for attempt in range(6):
        try:
            return _download_once(url, path, expected, algorithm=algorithm, client=client)
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in {
                429,
                500,
                502,
                503,
                504,
            }:
                raise
            if attempt == 5:
                raise
            delay = min(2**attempt, 16)
            print(f"{path.name}: transient download error; retrying in {delay}s", flush=True)
            time.sleep(delay)
    raise RuntimeError("download retry loop exhausted")


def extract_zip(path: Path, root: Path) -> None:
    marker = root / f".{path.name}.extracted.json"
    checksum = digest(path)
    if marker.is_file() and json.loads(marker.read_text())["sha256"] == checksum:
        return
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            target = (root / info.filename).resolve()
            if (
                not target.is_relative_to(root.resolve())
                or (info.external_attr >> 16) & 0o170000 == 0o120000
            ):
                raise ValueError(f"unsafe archive member: {info.filename}")
        archive.extractall(root)  # ZipFile validates the published per-member CRCs while reading.
    marker.write_text(json.dumps({"sha256": checksum}), encoding="utf-8")


def validate_tar_paths(path: Path, root: Path) -> None:
    """The upstream MTG unpacker predates extraction filters; enforce repo-local paths first."""
    with tarfile.open(path) as archive:
        for member in archive:
            target = (root / member.name).resolve()
            if not target.is_relative_to(root.resolve()) or not (member.isfile() or member.isdir()):
                raise ValueError(f"unsafe tar archive member: {member.name}")
