"""``load_embedder``: pinned download, device and precision choice.

Importing this module does not import torch; :func:`load_embedder` does, and turns a missing
``ml`` extra into a readable :class:`MLDependencyError`.
"""

from __future__ import annotations

import gc
import time
import warnings
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import numpy as np

from mcrar.ml.embedders.base import Embedder
from mcrar.ml.errors import EmbedderMemoryError, MLDependencyError, ModelError, ModelLoadError
from mcrar.ml.registry import ModelSpec, ensure_downloaded, get_spec

if TYPE_CHECKING:
    from mcrar.config import Settings

FP16_MIN_COSINE = 0.99  # fp16 is used only if it agrees with fp32 at least this well
PROBE_TEXTS = ("a calm piano melody", "fast aggressive electronic dance music with heavy bass")
WARMUP_WINDOWS = 3  # what embed_track sends in one batch
DEVICES = ("auto", "cpu", "cuda")
DTYPES = ("auto", "fp16", "fp32")


def probe_audio(sample_rate: int, seconds: float) -> np.ndarray:
    """A deterministic music-like test signal: a few decaying plucked chords and light noise."""
    n = round(seconds * sample_rate)
    t = np.arange(n) / sample_rate
    rng = np.random.default_rng(12345)
    out = np.zeros(n, dtype=np.float64)
    beat = 0.5
    for k, root in enumerate((220.0, 261.63, 196.0, 246.94) * int(seconds / beat / 4 + 1)):
        start = round(k * beat * sample_rate)
        if start >= n:
            break
        seg = t[start : start + round(beat * sample_rate)] - t[start]
        for ratio, amp in ((1.0, 0.3), (1.25, 0.2), (1.5, 0.2), (2.0, 0.1)):
            out[start : start + seg.size] += (
                amp * np.sin(2 * np.pi * root * ratio * seg) * np.exp(-3 * seg)
            )
    out += 0.01 * rng.standard_normal(n)
    return (out / max(np.abs(out).max(), 1e-9) * 0.7).astype(np.float32)


def _torch() -> Any:
    try:
        import torch
    except ImportError:
        raise MLDependencyError(
            "torch is not installed; install the ML dependencies with: uv sync --extra ml"
        ) from None
    return torch


def resolve_device(device: str) -> str:
    torch = _torch()
    if device not in DEVICES:
        raise ModelError(f"unknown device '{device}'; choose from: {', '.join(DEVICES)}")
    if device == "cuda" and not torch.cuda.is_available():
        raise ModelError("device 'cuda' requested but no CUDA GPU is available")
    if device == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    return device


def _embedder_class(key: str) -> Callable[..., Any]:
    if key == "clap":
        from mcrar.ml.embedders.clap import ClapEmbedder

        return ClapEmbedder
    if key == "glap":
        from mcrar.ml.embedders.glap import GlapEmbedder

        return GlapEmbedder
    if key == "muq-mulan":
        from mcrar.ml.embedders.muq_mulan import MuqMulanEmbedder

        return MuqMulanEmbedder
    raise ModelError(f"no embedder implementation for '{key}'")


def _quiet_libraries() -> None:
    """Silence progress bars and chatty warnings of the model libraries during loading."""
    try:
        from transformers.utils import logging as hf_logging

        hf_logging.set_verbosity_error()
        hf_logging.disable_progress_bar()
    except ImportError:
        pass


def _probe(embedder: Any) -> tuple[np.ndarray, np.ndarray]:
    audio = probe_audio(embedder.sample_rate, embedder.window_s)
    return embedder.embed_audio([audio]), embedder.embed_text(list(PROBE_TEXTS))


def _agreement(ref: tuple[np.ndarray, np.ndarray], other: tuple[np.ndarray, np.ndarray]) -> float:
    """The lowest cosine between corresponding rows of two (audio, text) embedding pairs."""
    cosines = [
        float(np.dot(a, b))
        for r, o in zip(ref, other, strict=True)
        for a, b in zip(r, o, strict=True)
    ]
    return min(cosines)


def _warm_up(embedder: Any) -> None:
    """Run the batch shape the pipeline uses once, so out-of-memory shows up at load time."""
    audio = probe_audio(embedder.sample_rate, embedder.window_s)
    embedder.embed_audio([audio] * WARMUP_WINDOWS)
    embedder.embed_text(list(PROBE_TEXTS))


def _memory_error(key: str) -> EmbedderMemoryError:
    return EmbedderMemoryError(
        f"not enough GPU memory to load '{key}' next to the models already loaded. "
        "Pass fewer models with --models (for example --models clap), or use --device cpu."
    )


def load_embedder(
    key: str,
    *,
    settings: Settings,
    device: str = "auto",
    dtype: str = "auto",
    batch_size: int | None = None,
) -> Embedder:
    """Load the embedder ``key`` (``clap``, ``glap`` or ``muq-mulan``).

    - Downloads the pinned revision(s) on first use (always by commit hash).
    - ``device="auto"`` uses CUDA when available. ``dtype="auto"`` uses fp16 on CUDA only if
      fp16 and fp32 embeddings of the same probe audio and texts have a cosine of at least
      0.99; otherwise fp32. ``fp16_cosine`` and ``dtype_note`` on the result tell what happened.
    """
    spec = get_spec(key)
    if dtype not in DTYPES:
        raise ModelError(f"unknown dtype '{dtype}'; choose from: {', '.join(DTYPES)}")
    torch = _torch()
    dev = resolve_device(device)
    if dtype == "fp16" and dev != "cuda":
        raise ModelError("fp16 needs a CUDA GPU; use --dtype fp32 on the CPU")
    folders = ensure_downloaded(spec, settings)
    _quiet_libraries()
    embedder = _embedder_class(key)(spec, batch_size=batch_size)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _load_and_place(embedder, spec, folders, dev, dtype)
            _warm_up(embedder)
    except (torch.cuda.OutOfMemoryError, EmbedderMemoryError):
        embedder.close()
        raise _memory_error(key) from None
    except ModelError:
        embedder.close()
        raise
    except Exception as exc:  # a broken install, file or library version: say which model
        embedder.close()
        raise ModelLoadError(
            f"could not load model '{key}' ({type(exc).__name__}): {str(exc)[:300]}"
        ) from None
    if dev == "cuda":
        torch.cuda.empty_cache()
    return embedder


def _load_and_place(embedder: Any, spec: ModelSpec, folders: dict, device: str, dtype: str) -> None:
    started = time.monotonic()
    embedder.load_weights(folders)
    if device == "cpu":
        embedder.place("cpu", "fp32")
        embedder.dtype_note = "fp32 (CPU)"
    elif dtype == "fp32":
        embedder.place(device, "fp32")
        embedder.dtype_note = "fp32 (requested)"
    elif dtype == "fp16":
        embedder.place(device, "fp16")
        embedder.dtype_note = "fp16 (requested)"
    else:
        # Reference embeddings in fp32 on the CPU (no VRAM spent on a float32 copy), then the
        # same probe in fp16 on the GPU.
        embedder.place("cpu", "fp32")
        reference = _probe(embedder)
        embedder.place(device, "fp16")
        cosine = _agreement(reference, _probe(embedder))
        embedder.fp16_cosine = cosine
        if cosine >= FP16_MIN_COSINE:
            embedder.dtype_note = f"fp16 (agrees with fp32: cosine {cosine:.4f})"
        else:
            # fp16 lost too much; the float32 weights were cast in place, so load them again.
            embedder.module = None
            gc.collect()
            embedder.load_weights(folders)
            embedder.place(device, "fp32")
            embedder.dtype_note = f"fp32 (fp16 cosine {cosine:.4f} < {FP16_MIN_COSINE})"
    embedder.load_seconds = time.monotonic() - started
