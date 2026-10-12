"""The precision decision of load_embedder (fp16 only if it agrees with fp32), without torch."""

from __future__ import annotations

import numpy as np
import pytest

from mcrar.ml import get_spec
from mcrar.ml.embedders.loader import (
    FP16_MIN_COSINE,
    PROBE_TEXTS,
    _agreement,
    _load_and_place,
    probe_audio,
)

DIM = 16


class Scripted:
    """An embedder whose fp16 outputs are the fp32 ones tilted by a chosen angle."""

    sample_rate = 8000
    window_s = 1.0

    def __init__(self, fp16_cosine: float) -> None:
        self.tilt = float(fp16_cosine)
        self.placed: list[tuple[str, str]] = []
        self.loads = 0
        self.module: object | None = None
        self.device = "cpu"
        self.dtype = "fp32"
        self.fp16_cosine: float | None = None
        self.dtype_note = ""
        self.load_seconds = 0.0

    def load_weights(self, folders: dict) -> None:
        self.loads += 1
        self.module = object()

    def place(self, device: str, dtype: str) -> None:
        self.placed.append((device, dtype))
        self.device, self.dtype = device, dtype

    def _rows(self, n: int) -> np.ndarray:
        base = np.zeros((n, DIM), dtype=np.float32)
        base[:, 0] = 1.0
        if self.dtype == "fp16":
            sin = np.sqrt(max(0.0, 1.0 - self.tilt**2))
            base[:, 0], base[:, 1] = self.tilt, sin
        return base

    def embed_audio(self, clips: list) -> np.ndarray:
        return self._rows(len(clips))

    def embed_text(self, texts: list) -> np.ndarray:
        return self._rows(len(texts))


def _place(embedder: Scripted, device: str = "cuda", dtype: str = "auto") -> Scripted:
    _load_and_place(embedder, get_spec("clap"), {}, device, dtype)
    return embedder


def test_fp16_is_used_when_it_agrees_with_fp32() -> None:
    embedder = _place(Scripted(0.9995))
    assert (embedder.device, embedder.dtype) == ("cuda", "fp16")
    assert embedder.placed == [("cpu", "fp32"), ("cuda", "fp16")]  # reference on the CPU first
    assert embedder.loads == 1
    assert embedder.fp16_cosine == pytest.approx(0.9995, abs=1e-6)
    assert embedder.dtype_note.startswith("fp16 (agrees with fp32")


def test_fp32_is_used_and_the_weights_reloaded_when_fp16_disagrees() -> None:
    embedder = _place(Scripted(0.95))
    assert (embedder.device, embedder.dtype) == ("cuda", "fp32")
    assert embedder.placed == [("cpu", "fp32"), ("cuda", "fp16"), ("cuda", "fp32")]
    assert embedder.loads == 2  # the float32 weights were cast in place, so loaded again
    assert embedder.fp16_cosine == pytest.approx(0.95, abs=1e-6)
    assert "fp16 cosine 0.9500 < 0.99" in embedder.dtype_note


def test_the_threshold_is_inclusive() -> None:
    assert FP16_MIN_COSINE == 0.99
    assert _place(Scripted(0.99)).dtype == "fp16"
    assert _place(Scripted(0.9899)).dtype == "fp32"


def test_the_worst_row_decides() -> None:
    ref = (np.array([[1.0, 0.0]]), np.array([[1.0, 0.0], [0.0, 1.0]]))
    other = (np.array([[1.0, 0.0]]), np.array([[1.0, 0.0], [0.6, 0.8]]))
    assert _agreement(ref, other) == pytest.approx(0.8)


def test_explicit_precision_skips_the_check() -> None:
    fp32 = _place(Scripted(0.1), dtype="fp32")
    assert (fp32.placed, fp32.fp16_cosine, fp32.loads) == ([("cuda", "fp32")], None, 1)
    fp16 = _place(Scripted(0.1), dtype="fp16")
    assert (fp16.placed, fp16.fp16_cosine) == ([("cuda", "fp16")], None)  # trusted when forced


def test_the_cpu_always_uses_fp32() -> None:
    embedder = _place(Scripted(0.9995), device="cpu")
    assert embedder.placed == [("cpu", "fp32")]
    assert embedder.dtype_note == "fp32 (CPU)"


def test_probe_audio_is_deterministic_float32_of_the_right_length() -> None:
    a = probe_audio(16000, 10.0)
    b = probe_audio(16000, 10.0)
    assert a.dtype == np.float32 and a.shape == (160000,)
    assert np.array_equal(a, b)
    assert np.isfinite(a).all() and 0.1 < np.abs(a).max() <= 0.7001
    assert len(PROBE_TEXTS) >= 2
