"""load_embedder error handling, with a stand-in embedder class (needs torch installed)."""

from __future__ import annotations

from typing import Any

import pytest

from mcrar.config import get_settings
from mcrar.ml import EmbedderMemoryError, ModelLoadError
from mcrar.ml.embedders import load_embedder, loader

torch = pytest.importorskip("torch")


class Failing:
    """Raises ``error`` from ``load_weights`` and records ``close``."""

    error: BaseException

    def __init__(self, spec: Any, batch_size: int | None = None) -> None:
        self.closed = False

    def load_weights(self, folders: dict) -> None:
        raise self.error

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def failing(monkeypatch: pytest.MonkeyPatch) -> type[Failing]:
    instances: list[Failing] = []

    class Tracked(Failing):
        def __init__(self, spec: Any, batch_size: int | None = None) -> None:
            super().__init__(spec, batch_size)
            instances.append(self)

    Tracked.instances = instances  # type: ignore[attr-defined]
    monkeypatch.setattr(loader, "ensure_downloaded", lambda spec, settings: {})
    monkeypatch.setattr(loader, "_embedder_class", lambda key: Tracked)
    return Tracked


def test_cuda_out_of_memory_becomes_a_clear_error_and_frees_the_model(
    failing: type[Failing],
) -> None:
    failing.error = torch.cuda.OutOfMemoryError("CUDA out of memory. Tried to allocate 2 GiB")
    with pytest.raises(EmbedderMemoryError) as err:
        load_embedder("glap", settings=get_settings(), device="cpu")
    message = str(err.value)
    assert "not enough GPU memory to load 'glap'" in message
    assert "--models" in message
    assert "CUDA out of memory" not in message  # no raw torch text
    assert failing.instances[0].closed  # type: ignore[attr-defined]


def test_unexpected_load_errors_name_the_model_and_hide_the_traceback(
    failing: type[Failing],
) -> None:
    failing.error = KeyError("audio_encoder.blocks.0.attn.qkv.weight")
    with pytest.raises(ModelLoadError) as err:
        load_embedder("clap", settings=get_settings(), device="cpu")
    assert str(err.value).startswith("could not load model 'clap' (KeyError)")
    assert failing.instances[0].closed  # type: ignore[attr-defined]


def test_bad_device_and_dtype_are_rejected_before_any_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(spec: Any, settings: Any) -> dict:
        raise AssertionError("must not download")

    monkeypatch.setattr(loader, "ensure_downloaded", boom)
    from mcrar.ml import ModelError

    with pytest.raises(ModelError, match="unknown device 'tpu'"):
        load_embedder("clap", settings=get_settings(), device="tpu")
    with pytest.raises(ModelError, match="unknown dtype 'bf16'"):
        load_embedder("clap", settings=get_settings(), dtype="bf16")
    with pytest.raises(ModelError, match="fp16 needs a CUDA GPU"):
        load_embedder("clap", settings=get_settings(), device="cpu", dtype="fp16")
