"""LAION CLAP ``larger_clap_music_and_speech`` through ``transformers`` (48 kHz, 512-d, Apache-2.0).

``laion/larger_clap_music`` is not used: its Hugging Face checkpoint is broken (logit_scale loads
as 1.0 and every text prompt maps to the same embedding, cosine 0.999), checked on 2026-10-11.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import numpy as np
import torch

from mcrar.ml.embedders.torch_base import TorchEmbedder


def _features(output: object) -> torch.Tensor:
    """transformers 5 returns a ModelOutput whose ``pooler_output`` is the projected embedding;
    older versions return the tensor itself."""
    return output if isinstance(output, torch.Tensor) else output.pooler_output  # type: ignore[attr-defined]


class ClapEmbedder(TorchEmbedder):
    def load_weights(self, folders: Mapping[str, Path]) -> None:
        from transformers import AutoTokenizer, ClapFeatureExtractor, ClapModel

        folder = str(folders[self.spec.repo])
        self.module = ClapModel.from_pretrained(folder).eval()
        self._extractor = ClapFeatureExtractor.from_pretrained(folder)
        self._tokenizer = AutoTokenizer.from_pretrained(folder)

    def close(self) -> None:
        self._extractor = None  # the processors hold no weights; dropped with the model anyway
        self._tokenizer = None
        super().close()

    def encode_audio(self, batch: torch.Tensor) -> torch.Tensor:
        # The feature extractor crops longer clips at random ("rand_trunc"); crop the centre
        # instead so that embedding the same clip twice gives the same vector.
        limit = round(self.window_s * self.sample_rate)
        clips = []
        for row in batch.cpu().numpy():
            if row.size > limit:
                start = (row.size - limit) // 2
                row = row[start : start + limit]
            clips.append(np.ascontiguousarray(row))
        inputs = self._extractor(clips, sampling_rate=self.sample_rate, return_tensors="pt")
        features = inputs["input_features"].to(self.device, self.torch_dtype)
        return _features(self.module.get_audio_features(input_features=features))

    def encode_text(self, texts: list[str]) -> torch.Tensor:
        tokens = self._tokenizer(texts, padding=True, truncation=True, return_tensors="pt")
        tokens = {k: v.to(self.device) for k, v in tokens.items()}
        return _features(self.module.get_text_features(**tokens))
