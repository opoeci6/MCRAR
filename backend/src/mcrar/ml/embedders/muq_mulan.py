"""MuQ-MuLan-large (Tencent; 24 kHz, 512-d, weights CC-BY-NC-4.0) through the ``muq`` package.

``MuQMuLan.from_pretrained`` is not used, for three reasons: it loads a local folder's
``model.safetensors`` only (this repository ships a pickle), it loads non-strictly, and its
config names two more repositories (the MuQ audio backbone and ``xlm-roberta-base``) that it
would fetch at whatever revision is current. Instead the pinned snapshots of all three
repositories are downloaded, the config is pointed at the local folders, the module is built
from it and the main checkpoint is loaded strictly with ``torch.load(weights_only=True)``.
"""

from __future__ import annotations

import contextlib
import io
import json
from collections.abc import Mapping
from pathlib import Path

import torch

from mcrar.ml.embedders.torch_base import TorchEmbedder
from mcrar.ml.errors import ModelLoadError

_AUDIO_BACKBONE = "OpenMuQ/MuQ-large-msd-iter"
_TEXT_TOWER = "FacebookAI/xlm-roberta-base"


class MuqMulanEmbedder(TorchEmbedder):
    def load_weights(self, folders: Mapping[str, Path]) -> None:
        from muq import MuQMuLan

        main = folders[self.spec.repo]
        config = json.loads((main / "config.json").read_text(encoding="utf-8"))
        # The muq package picks code paths from substrings of these names; the local snapshot
        # folders keep the repository name in their path ("models--OpenMuQ--MuQ-...").
        config["audio_model"]["name"] = str(folders[_AUDIO_BACKBONE])
        config["text_model"]["name"] = str(folders[_TEXT_TOWER])
        if "muq" not in config["audio_model"]["name"].lower():
            raise ModelLoadError("the MuQ backbone snapshot path must contain 'muq'")
        if "xlm-roberta" not in config["text_model"]["name"]:
            raise ModelLoadError("the text tower snapshot path must contain 'xlm-roberta'")
        # huggingface_hub prints "Loading weights from local directory" for each backbone
        with contextlib.redirect_stdout(io.StringIO()):
            model = MuQMuLan(config)
        state = torch.load(main / "pytorch_model.bin", map_location="cpu", weights_only=True)
        result = model.load_state_dict(state, strict=False)
        # The backbones were already loaded from their own pinned snapshots; the main
        # checkpoint must still cover every parameter.
        if result.unexpected_keys or result.missing_keys:
            raise ModelLoadError(
                f"{self.spec.repo} checkpoint does not match the model: "
                f"{len(result.missing_keys)} missing, {len(result.unexpected_keys)} unexpected keys"
            )
        self.module = model.eval()
        self._clip_len = round(float(model.clip_secs) * model.sr)

    def place(self, device: str, dtype: str) -> None:
        super().place(device, dtype)
        # transformers' conformer rotary embedding caches its table in a plain attribute of
        # the first sequence length it sees; a table built on the CPU or in float32 would be
        # reused after moving the module, so drop it.
        for module in self.module.modules():
            if hasattr(module, "cached_rotary_positional_embedding"):
                module.cached_rotary_positional_embedding = None
                module.cached_sequence_length = None

    def encode_audio(self, batch: torch.Tensor) -> torch.Tensor:
        batch = batch.to(self.torch_dtype)
        if batch.shape[1] == self._clip_len:
            return self.module.mulan_module.get_audio_latents(batch)
        # Other lengths: the package's own cropping into 10 s clips, averaged per clip.
        return self.module(wavs=batch)

    def encode_text(self, texts: list[str]) -> torch.Tensor:
        return self.module(texts=texts)
