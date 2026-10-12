"""Benchmark an embedder on synthetic audio: load time, VRAM, audio and text throughput."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from mcrar.ml.embedders.base import Embedder, embed_track
from mcrar.ml.embedders.loader import probe_audio

BENCH_TRACKS = 3  # timed track embeddings (after one warm-up)
TEXT_BATCH = 32
TEXT_REPEATS = 3
_PROMPTS = (
    "calm ambient pads with soft piano",
    "fast aggressive drum and bass with distorted synths",
    "orchestral battle music with brass and taiko drums",
    "relaxing lo-fi hip hop beat for studying",
    "tense suspense soundtrack with low drones",
    "upbeat 8-bit chiptune for a platformer level",
    "melancholic acoustic guitar ballad with soft vocals",
    "epic cinematic trailer music with choir",
)


@dataclass(frozen=True)
class BenchmarkResult:
    key: str
    model_id: str
    device: str
    dtype: str
    dtype_note: str
    dim: int
    load_s: float
    audio_s_per_s: float  # seconds of track audio embedded per second of wall time
    texts_per_s: float
    resident_vram_mb: float | None  # weights after loading
    peak_vram_mb: float | None  # torch.cuda.max_memory_allocated over load and run


def _cuda() -> object | None:
    """The ``torch.cuda`` module if torch is installed and a GPU is present, else None."""
    try:
        import torch
    except ImportError:
        return None
    return torch.cuda if torch.cuda.is_available() else None


def synthetic_track(sample_rate: int, seconds: float, seed: int) -> np.ndarray:
    """``seconds`` of a looped music-like probe signal, different per ``seed``."""
    rng = np.random.default_rng(seed)
    loop = probe_audio(sample_rate, 10.0)
    reps = int(np.ceil(seconds / 10.0))
    samples = np.tile(loop, reps)[: round(seconds * sample_rate)]
    noisy = samples * rng.uniform(0.5, 1.0) + 0.02 * rng.standard_normal(samples.size)
    return noisy.astype(np.float32)


def benchmark_embedder(load: Callable[[], Embedder], *, seconds: float = 60.0) -> BenchmarkResult:
    """Load the model with ``load`` and measure it. ``seconds`` is the length of each test track."""
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    cuda = _cuda()
    if cuda is not None:
        cuda.empty_cache()  # type: ignore[attr-defined]
        cuda.reset_peak_memory_stats()  # type: ignore[attr-defined]
    started = time.perf_counter()
    embedder = load()
    load_s = time.perf_counter() - started
    try:
        on_gpu = cuda is not None and getattr(embedder, "device", "cpu") == "cuda"
        resident = cuda.memory_allocated() / 2**20 if on_gpu else None  # type: ignore[attr-defined]

        tracks = [
            synthetic_track(embedder.sample_rate, seconds, seed) for seed in range(BENCH_TRACKS + 1)
        ]
        embed_track(embedder, tracks[0], embedder.sample_rate)  # warm-up (kernels, allocator)
        started = time.perf_counter()
        for track in tracks[1:]:
            embed_track(embedder, track, embedder.sample_rate)
        audio_s_per_s = BENCH_TRACKS * seconds / max(time.perf_counter() - started, 1e-9)

        texts = [_PROMPTS[i % len(_PROMPTS)] + f" {i}" for i in range(TEXT_BATCH)]
        embedder.embed_text(texts[:2])  # warm-up
        started = time.perf_counter()
        for _ in range(TEXT_REPEATS):
            embedder.embed_text(texts)
        texts_per_s = TEXT_REPEATS * len(texts) / max(time.perf_counter() - started, 1e-9)

        peak = cuda.max_memory_allocated() / 2**20 if on_gpu else None  # type: ignore[attr-defined]
        return BenchmarkResult(
            key=embedder.key,
            model_id=embedder.model_id,
            device=getattr(embedder, "device", "cpu"),
            dtype=getattr(embedder, "dtype", "fp32"),
            dtype_note=getattr(embedder, "dtype_note", ""),
            dim=embedder.dim,
            load_s=load_s,
            audio_s_per_s=audio_s_per_s,
            texts_per_s=texts_per_s,
            resident_vram_mb=resident,
            peak_vram_mb=peak,
        )
    finally:
        close = getattr(embedder, "close", None)
        if close is not None:
            close()
