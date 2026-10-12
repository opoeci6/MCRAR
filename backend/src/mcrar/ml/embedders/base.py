"""The ``Embedder`` interface and the track-level embedding helper. numpy only, no torch."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

import numpy as np

WINDOW_CENTRES = (0.2, 0.5, 0.8)  # window centres as fractions of the decoded clip
_EPS = 1e-12


class Embedder(Protocol):
    """A text-audio embedding model that maps both modalities into one space.

    ``embed_audio`` takes mono float32 clips at ``sample_rate``; ``embed_text`` takes strings.
    Both return ``(n, dim)`` float32 arrays whose rows are L2-normalised.
    """

    key: str
    model_id: str
    dim: int
    sample_rate: int
    window_s: float
    commercial_ok: bool

    def embed_audio(self, clips: Sequence[np.ndarray]) -> np.ndarray: ...

    def embed_text(self, texts: Sequence[str]) -> np.ndarray: ...


def l2_normalize(vectors: np.ndarray) -> np.ndarray:
    """Row-wise L2 normalisation to float32 (all-zero rows stay zero)."""
    arr = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=-1, keepdims=True)
    return (arr / np.maximum(norms, _EPS)).astype(np.float32)


def window_starts(n_samples: int, window: int) -> list[int]:
    """Start offsets of the windows taken from a clip of ``n_samples`` samples.

    Three windows of ``window`` samples centred at 20%, 50% and 80% of the clip, moved inward
    where they would stick out. Identical windows (clips barely longer than one window) are
    reported once. A clip not longer than one window yields the single start ``0`` (the caller
    zero-pads it).
    """
    if n_samples <= window:
        return [0]
    starts: list[int] = []
    for fraction in WINDOW_CENTRES:
        start = round(fraction * n_samples) - window // 2
        start = min(max(start, 0), n_samples - window)
        if start not in starts:
            starts.append(start)
    return starts


def track_windows(samples: np.ndarray, sr: int, window_s: float) -> list[np.ndarray]:
    """The float32 windows :func:`embed_track` feeds to the model (see :func:`window_starts`)."""
    window = round(window_s * sr)
    if window <= 0:
        raise ValueError("window_s must be positive")
    clip = np.asarray(samples, dtype=np.float32)
    if clip.ndim != 1:
        raise ValueError(f"expected mono samples of shape (n,), got {clip.shape}")
    if clip.size == 0:
        raise ValueError("audio is empty")
    if clip.size < window:
        clip = np.pad(clip, (0, window - clip.size))
    return [np.ascontiguousarray(clip[s : s + window]) for s in window_starts(clip.size, window)]


def embed_track(embedder: Embedder, samples: np.ndarray, sr: int) -> np.ndarray:
    """One L2-normalised ``(dim,)`` float32 vector for a whole track.

    ``samples`` must be mono at ``embedder.sample_rate`` (the caller decodes at that rate).
    Up to three windows of ``embedder.window_s`` seconds are embedded in one batch, their
    normalised vectors averaged and re-normalised. Short clips use one zero-padded window.
    """
    if sr != embedder.sample_rate:
        raise ValueError(
            f"{embedder.key} needs audio at {embedder.sample_rate} Hz, got {sr} Hz; "
            "decode at the embedder's sample rate"
        )
    windows = track_windows(samples, sr, embedder.window_s)
    vectors = np.asarray(embedder.embed_audio(windows), dtype=np.float32)
    if vectors.ndim != 2 or vectors.shape[0] != len(windows):
        raise ValueError(
            f"{embedder.key} returned embeddings of shape {vectors.shape} "
            f"for {len(windows)} windows"
        )
    if vectors.shape[1] != embedder.dim:
        raise ValueError(
            f"{embedder.key} returned {vectors.shape[1]}-d embeddings, expected {embedder.dim}"
        )
    mean = l2_normalize(vectors).mean(axis=0)
    if not np.isfinite(mean).all() or float(np.linalg.norm(mean)) < _EPS:
        raise ValueError(f"{embedder.key} produced a degenerate (non-finite or zero) embedding")
    return l2_normalize(mean)
