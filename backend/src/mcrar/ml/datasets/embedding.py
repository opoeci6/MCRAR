"""Checkpoint embeddings before deleting audio; retries preserve every completed track."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from mcrar.ml.datasets.parsers import Sample

if TYPE_CHECKING:
    from mcrar.audio import AudioClip
    from mcrar.ml.embedders import Embedder

EMBEDDER = "clap@195c3a3"


def atomic_npz(path: Path, **arrays: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as stream:
        np.savez_compressed(stream, **arrays)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def embed_dataset(
    samples: Sequence[Sample],
    embedder: Embedder,
    output: Path,
    *,
    delete_audio: bool = False,
    checkpoint_size: int = 32,
    batch_size: int = 1,
    progress: Callable[[str], None] = print,
) -> dict:
    from mcrar.audio import AudioError, load_audio
    from mcrar.ml.embedders import embed_track, track_windows

    started = time.monotonic()
    if embedder.model_id != EMBEDDER or embedder.dim != 512:
        raise ValueError(f"dataset embedding requires {EMBEDDER}, 512 dimensions")
    if min(checkpoint_size, batch_size) < 1:
        raise ValueError("checkpoint_size and batch_size must be positive")
    if len({s.id for s in samples}) != len(samples):
        raise ValueError("duplicate sample ids")
    output.parent.mkdir(parents=True, exist_ok=True)
    vectors = {}
    if output.is_file():
        with np.load(output, allow_pickle=False) as saved:
            ids, matrix = saved["ids"], saved["matrix"]
            if (
                matrix.shape != (len(ids), 512)
                or matrix.dtype != np.float32
                or not np.isfinite(matrix).all()
                or not np.allclose(np.linalg.norm(matrix, axis=1), 1, atol=1e-3)
            ):
                raise ValueError("invalid embedding checkpoint")
            if len(set(ids.tolist())) != len(ids):
                raise ValueError("duplicate embedding ids")
            vectors = dict(zip(ids.tolist(), matrix, strict=True))
            if not set(vectors) <= {s.id for s in samples}:
                raise ValueError("checkpoint contains ids outside this dataset")
    pending: list[Sample] = []
    failures = {}

    def checkpoint() -> None:
        if not pending:
            return
        ids = sorted(vectors)
        atomic_npz(
            output,
            ids=np.array(ids, dtype=np.int64),
            matrix=np.stack([vectors[i] for i in ids]).astype(np.float32),
        )
        if delete_audio:
            for sample in pending:
                sample.path.unlink(missing_ok=True)
        pending.clear()

    todo = []
    for sample in samples:
        if sample.id in vectors:
            if delete_audio:
                sample.path.unlink(missing_ok=True)
        else:
            todo.append(sample)

    def decode(sample: Sample) -> AudioClip | Exception:
        try:
            audio = load_audio(sample.path, sr=embedder.sample_rate, mono=True, max_seconds=240)
            if len(audio.samples) < embedder.sample_rate:
                raise ValueError("audio shorter than one second")
            return audio
        except (AudioError, OSError, ValueError) as exc:
            return exc

    try:
        # Batch canonical model windows, then let embed_track aggregate each track's cached
        # outputs. The cap, centres, padding and pinned model are identical to the catalog.
        group_size = max(1, batch_size // 3)
        with ThreadPoolExecutor(max_workers=min(4, group_size)) as pool:
            for start in range(0, len(todo), group_size):
                group = todo[start : start + group_size]
                decoded = list(pool.map(decode, group))
                good = []
                for sample, audio in zip(group, decoded, strict=True):
                    if isinstance(audio, Exception):
                        failures[str(sample.id)] = f"{type(audio).__name__}: {audio}"
                        progress(f"{sample.id}: skipped ({audio})")
                    else:
                        good.append((sample, audio))
                if good:
                    windows = [track_windows(a.samples, a.sr, embedder.window_s) for _, a in good]
                    encoded = embedder.embed_audio([w for group in windows for w in group])
                    offset = 0
                    for (sample, audio), clips in zip(good, windows, strict=True):
                        cached = _CachedWindows(
                            embedder, clips, encoded[offset : offset + len(clips)]
                        )
                        vectors[sample.id] = embed_track(cached, audio.samples, audio.sr)
                        offset += len(clips)
                        pending.append(sample)
                if len(pending) >= checkpoint_size:
                    checkpoint()
                    progress(f"embedded {len(vectors)}/{len(samples)}, skipped {len(failures)}")
    finally:
        checkpoint()
        report = {
            "embedder": EMBEDDER,
            "max_seconds": 240,
            "total": len(samples),
            "embedded": len(vectors),
            "skipped": len(failures),
            "failures": failures,
            "elapsed_s": time.monotonic() - started,
            "device": getattr(embedder, "device", "unknown"),
            "dtype": getattr(embedder, "dtype", "unknown"),
        }
        output.with_suffix(".report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
    return report


class _CachedWindows:
    """Replay one track's window outputs through the canonical aggregation helper."""

    def __init__(self, embedder: Embedder, clips: list[np.ndarray], vectors: np.ndarray) -> None:
        self.embedder, self.clips, self.vectors = embedder, clips, vectors

    def __getattr__(self, name: str):
        return getattr(self.embedder, name)

    def embed_audio(self, clips: Sequence[np.ndarray]) -> np.ndarray:
        if len(clips) != len(self.clips) or any(
            not np.array_equal(a, b) for a, b in zip(clips, self.clips, strict=True)
        ):
            raise ValueError("batched windows differ from the canonical embed_track windows")
        return self.vectors
