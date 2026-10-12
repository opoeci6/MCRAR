"""Read the publishers' metadata without pandas; retain their official splits."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SPLITS = {"training": "train", "train": "train", "validation": "validation", "test": "test"}


def label_id(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


@dataclass(frozen=True)
class Sample:
    id: int
    path: Path
    split: str
    targets: dict[str, tuple[str, ...] | float]


def parse_fma(metadata: Path, audio: Path) -> list[Sample]:
    with metadata.open(encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream)
        fields = list(zip(next(reader), next(reader), strict=True))
        index = {key: i for i, key in enumerate(fields)}
        result = []
        for row in reader:
            if not row or not row[0].isdigit():
                continue
            if row[index["set", "subset"]] not in {"small", "medium"}:
                continue
            genre = row[index["track", "genre_top"]]
            if not genre:
                raise ValueError(f"FMA track {row[0]} has no top-level genre")
            tid = int(row[0])
            result.append(
                Sample(
                    tid,
                    audio / f"{tid // 1000:03d}/{tid:06d}.mp3",
                    SPLITS[row[index["set", "split"]]],
                    {"genre": (label_id(genre),)},
                )
            )
    return sorted(result, key=lambda s: s.id)


def parse_mtg(splits: Path, audio: Path) -> list[Sample]:
    result = []
    seen = set()
    for split in ("train", "validation", "test"):
        path = splits / f"autotagging_moodtheme-{split}.tsv"
        with path.open(encoding="utf-8", newline="") as stream:
            for row in csv.reader(stream, delimiter="\t"):
                if not row or row[0] == "TRACK_ID":
                    continue
                tid = int(row[0].removeprefix("track_"))
                if tid in seen:
                    raise ValueError(f"MTG track {tid} occurs in more than one split")
                seen.add(tid)
                relative = Path(row[3])
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError(f"unsafe audio path: {row[3]}")
                # Split TSVs name the standard MP3; the prescribed audio-low release adds .low.
                relative = relative.with_suffix(".low.mp3")
                tags = tuple(
                    label_id(t.removeprefix("mood/theme---"))
                    for t in row[5:]
                    if t.startswith("mood/theme---")
                )
                if not tags:
                    raise ValueError(f"MTG track {tid} has no mood/theme tags")
                result.append(Sample(tid, audio / relative, split, {"moodtheme": tags}))
    return sorted(result, key=lambda s: s.id)


def parse_deam(paths: list[Path], audio: Path, *, seed: int = 0) -> list[Sample]:
    rows = {}
    for path in sorted(paths):
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, skipinitialspace=True)
            for raw in reader:
                row = {k.strip(): v.strip() for k, v in raw.items()}
                tid = int(row["song_id"])
                values = {
                    name: (float(row[f"{name}_mean"]) - 1) / 8 for name in ("valence", "arousal")
                }
                if not all(np.isfinite(v) and 0 <= v <= 1 for v in values.values()):
                    raise ValueError(f"DEAM song {tid} has labels outside [1, 9]")
                if tid in rows and rows[tid] != values:
                    raise ValueError(f"DEAM song {tid} has conflicting static annotations")
                rows[tid] = values
    ids = np.array(sorted(rows), dtype=np.int64)
    order = np.random.default_rng(seed).permutation(ids)
    a, b = int(len(ids) * 0.8), int(len(ids) * 0.9)
    split = {
        int(tid): "train" if i < a else "validation" if i < b else "test"
        for i, tid in enumerate(order)
    }
    return [Sample(int(tid), audio / f"{tid}.mp3", split[int(tid)], rows[int(tid)]) for tid in ids]
