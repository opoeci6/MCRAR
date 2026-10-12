"""GLAP (``mispeech/GLAP``, Xiaomi; 16 kHz, 1024-d, Apache-2.0) through its remote code.

Route: ``AutoModel.from_pretrained(<pinned local snapshot>, trust_remote_code=True)``, so the
code that runs is the pinned revision's ``modeling_glap.py``. The ``glap_model`` PyPI package is
not used: it needs ``dasheng`` and a conda libsndfile, and offers nothing the remote code lacks.

The remote ``encode_text`` builds its token tensors on the CPU even when the model sits on the
GPU, so text encoding is done here with the remote model's own tokenizer and text tower.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import torch
import torch.nn.functional as F

from mcrar.ml.embedders.torch_base import TorchEmbedder


def _features_to_half(_module: torch.nn.Module, _args: object, output: tuple) -> tuple:
    features, mask = output
    return features.to(torch.float16), mask


class GlapEmbedder(TorchEmbedder):
    def load_weights(self, folders: Mapping[str, Path]) -> None:
        from transformers import AutoModel

        folder = str(folders[self.spec.repo])
        self.module = AutoModel.from_pretrained(folder, trust_remote_code=True).eval()
        self._tokenizer = self.module._get_tokenizer()  # reads the file next to the weights
        self._hook = None

    def cast(self, dtype: str) -> None:
        super().cast(dtype)
        front_end = self.module.audio_encoder.front_end
        if self._hook is not None:
            self._hook.remove()
            self._hook = None
        if dtype == "fp16":
            # The mel front end (STFT, log) stays in float32; only its output is cast.
            front_end.float()
            self._hook = front_end.register_forward_hook(_features_to_half)
        else:
            front_end.float()

    def encode_audio(self, batch: torch.Tensor) -> torch.Tensor:
        return self.module.encode_audio(batch)

    def encode_text(self, texts: list[str]) -> torch.Tensor:
        model = self.module
        encode = self._tokenizer.create_encoder(lang="eng_Latn")
        ids = [encode(t)[: model.config.text_max_seq_len] for t in texts]
        longest = max(len(i) for i in ids)
        padded = torch.full((len(ids), longest), self._tokenizer.pad_idx, dtype=torch.long)
        mask = torch.zeros(len(ids), longest, dtype=torch.bool)
        for row, token_ids in enumerate(ids):
            padded[row, : len(token_ids)] = torch.tensor(token_ids, dtype=torch.long)
            mask[row, len(token_ids) :] = True
        sentence = model.text_encoder(padded.to(self.device), mask.to(self.device))
        return F.normalize(model.text_proj(sentence.to(self.torch_dtype)), dim=-1)
