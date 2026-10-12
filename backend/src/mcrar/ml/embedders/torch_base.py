"""Shared machinery of the torch-based embedders. Imports torch, so it is only loaded lazily."""

from __future__ import annotations

import gc
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import torch

from mcrar.ml.embedders.base import l2_normalize
from mcrar.ml.errors import EmbedderMemoryError
from mcrar.ml.registry import ModelSpec

DEFAULT_BATCH_SIZE = 8
TEXT_BATCH_SIZE = 32
DTYPES = {"fp32": torch.float32, "fp16": torch.float16}


def oom_message(key: str) -> str:
    return (
        f"the GPU ran out of memory running '{key}'. Pass fewer models (--models), a smaller "
        "--batch-size, or use --device cpu."
    )


class TorchEmbedder:
    """Base of the concrete embedders; subclasses implement the four hooks below.

    Life cycle (driven by :func:`mcrar.ml.embedders.load_embedder`): ``load_weights`` loads the
    float32 weights on the CPU, ``place`` casts and moves them, ``close`` frees them.
    """

    def __init__(self, spec: ModelSpec, *, batch_size: int | None = None) -> None:
        self.spec = spec
        self.key = spec.key
        self.model_id = spec.model_id
        self.dim = spec.dim
        self.sample_rate = spec.sample_rate
        self.window_s = spec.window_s
        self.commercial_ok = spec.commercial_ok
        self.batch_size = max(1, batch_size or DEFAULT_BATCH_SIZE)
        self.device = "cpu"
        self.dtype = "fp32"
        self.fp16_cosine: float | None = None  # result of the fp16-vs-fp32 check, if it ran
        self.dtype_note = ""  # why this precision was chosen
        self.load_seconds = 0.0
        self.module: Any = None

    # -- hooks ------------------------------------------------------------------------

    def load_weights(self, folders: Mapping[str, Path]) -> None:
        """Load float32 weights on the CPU into ``self.module`` (eval mode)."""
        raise NotImplementedError

    def encode_audio(self, batch: torch.Tensor) -> torch.Tensor:
        """``(B, samples)`` float32 on ``self.device`` to ``(B, dim)`` (any dtype)."""
        raise NotImplementedError

    def encode_text(self, texts: list[str]) -> torch.Tensor:
        """Strings to ``(B, dim)`` (any dtype)."""
        raise NotImplementedError

    def cast(self, dtype: str) -> None:
        """Cast ``self.module`` (still on the CPU) to ``dtype``; override for parts that must
        stay in float32."""
        self.module.to(DTYPES[dtype])

    # -- placement --------------------------------------------------------------------

    @property
    def torch_dtype(self) -> torch.dtype:
        return DTYPES[self.dtype]

    def place(self, device: str, dtype: str) -> None:
        """Cast to ``dtype`` while still on the CPU (so the GPU never sees the float32 copy),
        then move to ``device``."""
        self.cast(dtype)
        self.module.to(device)
        self.device, self.dtype = device, dtype

    def close(self) -> None:
        """Drop the weights and give the GPU memory back."""
        self.module = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    # -- public API -------------------------------------------------------------------

    def embed_audio(self, clips: Sequence[np.ndarray]) -> np.ndarray:
        arrays = [np.asarray(c, dtype=np.float32) for c in clips]
        for a in arrays:
            if a.ndim != 1 or a.size == 0:
                raise ValueError(f"clips must be non-empty mono arrays, got shape {a.shape}")
        out: list[np.ndarray] = []
        start = 0
        while start < len(arrays):
            # a batch is a run of equal-length clips, at most batch_size long
            end = start + 1
            while (
                end < len(arrays)
                and end - start < self.batch_size
                and arrays[end].size == arrays[start].size
            ):
                end += 1
            batch = torch.from_numpy(np.stack(arrays[start:end])).to(self.device)
            out.append(self._run(lambda b=batch: self.encode_audio(b)))
            start = end
        return self._finish(out, 0)

    def embed_text(self, texts: Sequence[str]) -> np.ndarray:
        items = [str(t) for t in texts]
        out = [
            self._run(lambda s=items[i : i + TEXT_BATCH_SIZE]: self.encode_text(s))
            for i in range(0, len(items), TEXT_BATCH_SIZE)
        ]
        return self._finish(out, len(items))

    def _run(self, call: Any) -> np.ndarray:
        try:
            with torch.inference_mode():
                return call().float().cpu().numpy()
        except torch.cuda.OutOfMemoryError:
            gc.collect()
            torch.cuda.empty_cache()
            raise EmbedderMemoryError(oom_message(self.key)) from None

    def _finish(self, parts: list[np.ndarray], expected: int) -> np.ndarray:
        if not parts:
            return np.empty((0, self.dim), dtype=np.float32)
        result = np.concatenate(parts, axis=0)
        if result.shape[1] != self.dim:
            raise ValueError(
                f"{self.key} produced {result.shape[1]}-d vectors, expected {self.dim}"
            )
        if not np.isfinite(result).all():
            raise ValueError(
                f"{self.key} produced non-finite values ({self.dtype} on {self.device})"
            )
        return l2_normalize(result)
