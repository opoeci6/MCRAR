"""The approved DEAM exception enforces size/hash/CRC/counts without a fallback."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from mcrar.ml.datasets.download import digest
from mcrar.ml.datasets.service import verify_deam_archive


def test_deam_observed_manifest_is_honest_and_complete() -> None:
    from mcrar.ml.datasets import service

    manifest = json.loads(Path(service.__file__).with_name("deam_checksums.json").read_text())
    assert manifest["checksum_source"] == "observed"
    assert manifest["approval"].endswith("issuecomment-6116833123")
    assert len(manifest["observers"]) == 2
    for row in manifest["files"].values():
        assert row["url"].startswith("https://cvml.unige.ch/databases/DEAM/")
        assert row["last_modified"] and row["etag"] and row["observation_date"]


def test_deam_size_hash_and_member_count_fail_hard(tmp_path: Path) -> None:
    path = tmp_path / "sample.zip"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("MEMD_audio/1.mp3", b"synthetic")
    path.write_bytes(buffer.getvalue())
    info = {"bytes": path.stat().st_size, "sha256": digest(path), "members": 1, "mp3": 1}
    verify_deam_archive(path, info)
    for key, value in (("bytes", 0), ("sha256", "0" * 64), ("members", 2), ("mp3", 2)):
        with pytest.raises(ValueError, match="mismatch|exactly"):
            verify_deam_archive(path, {**info, key: value})
    path.write_bytes(path.read_bytes().replace(b"synthetic", b"corrupted"))
    with pytest.raises(ValueError, match="CRC"):
        verify_deam_archive(path, {**info, "sha256": digest(path)})
