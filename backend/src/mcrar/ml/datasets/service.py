"""Dataset workflows and provenance, including DEAM's approved observed-checksum exception."""

from __future__ import annotations

import json
import subprocess
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from mcrar.config import Settings
from mcrar.ml.datasets.download import (
    digest,
    download_verified,
    extract_zip,
    validate_tar_paths,
    verify,
)
from mcrar.ml.datasets.embedding import EMBEDDER
from mcrar.ml.datasets.parsers import Sample, parse_deam, parse_fma, parse_mtg

NAMES = ("fma-medium", "mtg-moodtheme", "deam")
MTG_COMMIT = "cafd8e20c265ed84f1e61f1c875327971f43a62f"
MTG_MEMBERSHIP = {
    "audio_release": {"tracks": 18486, "tags": 59},
    "split0": {
        "tracks": 17982,
        "tags": 56,
        "train": 9949,
        "validation": 3802,
        "test": 4231,
    },
    "membership_confirmation": "https://github.com/opoeci6/MCRAR/issues/2#issuecomment-6117456637",
}
FMA_FILES = {
    "fma_metadata.zip": "f0df49ffe5f2a6008d7dc83c6915b31835dfe733",
    "fma_medium.zip": "c67b69ea232021025fca9231fc1c7c1a063ab50b",
}


def dataset_root(settings: Settings, name: str) -> Path:
    if name not in NAMES:
        raise ValueError(f"unknown dataset {name!r}; choose from: {', '.join(NAMES)}")
    return settings.data_dir / "datasets" / ("mtg-jamendo" if name == "mtg-moodtheme" else name)


def run_local(settings: Settings, command: list[str], *, capture: bool = False) -> str:
    import os

    wrapper = (
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(settings.home / "scripts/with-env.ps1"),
        ]
        if os.name == "nt"
        else [str(settings.home / "scripts/with-env.sh")]
    )
    result = subprocess.run(
        wrapper + command,
        cwd=settings.home,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else ""


def download_dataset(settings: Settings, name: str) -> dict:
    import sys

    root = dataset_root(settings, name)
    root.mkdir(parents=True, exist_ok=True)
    provenance = {"name": name}
    if name == "fma-medium":
        for filename, sha in FMA_FILES.items():
            print(f"Downloading/verifying {filename}", flush=True)
            path = download_verified(
                f"https://os.unil.cloud.switch.ch/fma/{filename}",
                root / filename,
                sha,
                algorithm="sha1",
            )
            extract_zip(path, root)
        provenance.update(
            checksums={f: {"sha1": sha} for f, sha in FMA_FILES.items()},
            checksum_source="https://github.com/mdeff/fma#data",
            data_license="CC BY 4.0 (metadata); per-track CC audio",
        )
    elif name == "mtg-moodtheme":
        repo = root / "repo"
        if not (repo / ".git").is_dir():
            run_local(
                settings,
                ["git", "clone", "https://github.com/MTG/mtg-jamendo-dataset.git", str(repo)],
            )
        run_local(settings, ["git", "-C", str(repo), "checkout", "--detach", MTG_COMMIT])
        commit = run_local(settings, ["git", "-C", str(repo), "rev-parse", "HEAD"], capture=True)
        if commit != MTG_COMMIT:
            raise ValueError("MTG dataset repository does not match the pinned commit")
        prefix = repo / "data/download/autotagging_moodtheme_audio-low"
        tar_hashes = _hashes(Path(str(prefix) + "_sha256_tars.txt"))
        track_hashes = _hashes(Path(str(prefix) + "_sha256_tracks.txt"))
        audio = root / "audio-low"
        audio.mkdir(exist_ok=True)
        complete = all(
            (audio / p).is_file() and digest(audio / p) == sha for p, sha in track_hashes.items()
        )
        if not complete:

            def fetch(item: tuple[str, str]) -> None:
                filename, sha = item
                print(f"Downloading/verifying {filename}", flush=True)
                try:
                    download_verified(
                        "https://cdn.freesound.org/mtg-jamendo/"
                        f"autotagging_moodtheme/audio-low/{filename}",
                        audio / filename,
                        sha,
                    )
                except Exception as exc:
                    print(f"Download failed: {filename}: {exc}", flush=True)
                    raise

            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(fetch, tar_hashes.items()))
            for filename in tar_hashes:
                validate_tar_paths(audio / filename, audio)
            # Use the publisher's downloader/unpacker with our interpreter. Archives have already
            # been checked, because upstream skips verification of pre-existing tar downloads.
            run_local(
                settings,
                [
                    sys.executable,
                    str(repo / "scripts/download/download.py"),
                    "--dataset",
                    "autotagging_moodtheme",
                    "--type",
                    "audio-low",
                    "--from",
                    "mtg-fast",
                    str(audio),
                    "--unpack",
                    "--remove",
                ],
            )
            for relative, sha in track_hashes.items():
                verify(audio / relative, sha)
        provenance.update(
            commit=commit,
            data_license="CC BY-NC-SA 4.0",
            checksums=tar_hashes,
            checksum_algorithm="sha256",
            checksum_source=f"https://github.com/MTG/mtg-jamendo-dataset/tree/{commit}/data/download",
            **MTG_MEMBERSHIP,
        )
    else:
        manifest = Path(__file__).with_name("deam_checksums.json")
        hashes = json.loads(manifest.read_text(encoding="utf-8"))
        for filename in ("DEAM_audio.zip", "DEAM_Annotations.zip"):
            info = hashes["files"][filename]
            path = download_verified(info["url"], root / filename, info["sha256"])
            verify_deam_archive(path, info)
            extract_zip(path, root)
        provenance.update(
            checksums=hashes,
            checksum_source="observed",
            data_license="CC BY-NC (version unspecified, per DEAM manual)",
            license_source="https://cvml.unige.ch/databases/DEAM/manual.pdf",
            split="80/10/10 over sorted song ids, seed 0",
        )
    (root / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    return provenance


def verify_deam_archive(path: Path, info: dict) -> None:
    """Enforce the independently cross-checked exception approved in GitHub issue #1."""
    if path.stat().st_size != info["bytes"]:
        raise ValueError(f"DEAM archive size mismatch: {path.name}")
    verify(path, info["sha256"])
    with zipfile.ZipFile(path) as archive:
        if len(archive.infolist()) != info["members"]:
            raise ValueError(f"DEAM archive member count mismatch: {path.name}")
        if (
            "mp3" in info
            and sum(i.filename.lower().endswith(".mp3") for i in archive.infolist()) != info["mp3"]
        ):
            raise ValueError("DEAM audio must contain exactly 1,802 MP3 files")
        bad = archive.testzip()
        if bad is not None:
            raise ValueError(f"DEAM ZIP CRC mismatch: {bad}")


def _hashes(path: Path) -> dict[str, str]:
    return {row.split()[1]: row.split()[0] for row in path.read_text().splitlines() if row.strip()}


def samples_for(settings: Settings, name: str) -> list[Sample]:
    root = dataset_root(settings, name)
    if name == "fma-medium":
        return parse_fma(root / "fma_metadata/tracks.csv", root / "fma_medium")
    if name == "mtg-moodtheme":
        return parse_mtg(root / "repo/data/splits/split-0", root / "audio-low")
    paths = [
        p
        for p in root.rglob("*.csv")
        if "static_annotations_averaged" in p.name and p.parent.name == "song_level"
    ]
    if not paths:
        raise ValueError("DEAM static per-song annotation CSVs are missing; download the dataset")
    audio = root / "MEMD_audio"
    if not audio.is_dir():
        raise ValueError("DEAM MEMD_audio directory is missing")
    return parse_deam(paths, audio)


def training_data(settings: Settings, name: str, label_set: str) -> tuple:
    samples = samples_for(settings, name)
    path = dataset_root(settings, name) / f"embeddings/{EMBEDDER}.npz"
    with np.load(path, allow_pickle=False) as saved:
        ids, matrix = saved["ids"], saved["matrix"]
    if (
        matrix.dtype != np.float32
        or matrix.shape != (len(ids), 512)
        or len(set(ids.tolist())) != len(ids)
        or not np.isfinite(matrix).all()
        or not np.allclose(np.linalg.norm(matrix, axis=1), 1, atol=1e-3)
    ):
        raise ValueError("invalid CLAP dataset embeddings")
    by_id = {s.id: s for s in samples}
    if any(int(i) not in by_id for i in ids):
        raise ValueError("embedding ids not found in dataset metadata")
    selected = [by_id[int(i)] for i in ids]
    labels = (
        ["value"]
        if label_set in {"valence", "arousal"}
        else sorted({t for s in samples for t in s.targets[label_set]})
    )
    if label_set in {"valence", "arousal"}:
        y = np.array([[s.targets[label_set]] for s in selected], dtype=np.float32)
        kind = "regression"
    elif label_set == "genre":
        y = np.array([labels.index(s.targets[label_set][0]) for s in selected], dtype=np.int64)
        kind = "single_label"
    else:
        y = np.array(
            [[float(t in s.targets[label_set]) for t in labels] for s in selected], dtype=np.float32
        )
        kind = "multi_label"
    splits = np.array([s.split for s in selected])
    if any(not (splits == s).any() for s in ("train", "validation", "test")):
        raise ValueError("embeddings must cover training, validation and test splits")
    missing = len(samples) - len(selected)
    if missing:
        report_path = path.with_suffix(".report.json")
        if not report_path.is_file():
            raise ValueError("incomplete dataset embeddings: no audited failure report")
        report = json.loads(report_path.read_text())
        skipped = {int(i) for i in report["failures"]}
        if set(by_id) - set(ids.tolist()) != skipped:
            raise ValueError("incomplete dataset embedding run; resume mcrar datasets embed first")
    return ids, matrix, y, splits, labels, kind
