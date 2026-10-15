"""The model pool: one load per key, serialised use, missing ml extra."""

from __future__ import annotations

import threading
import time
from typing import Any

import numpy as np
import pytest

from mcrar.api.models import NO_TORCH_MESSAGE, ModelPool, ModelUnavailableError
from mcrar.config import Settings, get_settings
from mcrar.ml import ModelLoadError


class Model:
    def __init__(self, key: str, *, commercial_ok: bool = True) -> None:
        self.key = key
        self.commercial_ok = commercial_ok
        self.closed = 0
        self.active = 0
        self.max_active = 0
        self._guard = threading.Lock()

    def embed_text(self, texts: Any) -> np.ndarray:
        with self._guard:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.01)
        with self._guard:
            self.active -= 1
        return np.ones((len(texts), 2), dtype=np.float32)

    def embed_audio(self, clips: Any) -> np.ndarray:
        return self.embed_text(clips)

    def close(self) -> None:
        self.closed += 1


def pool_with(factory: Any) -> ModelPool:
    return ModelPool(get_settings(), factory=factory, torch_available=lambda: True)


def test_concurrent_first_requests_load_the_model_once() -> None:
    loads: list[str] = []

    def factory(key: str, settings: Settings) -> Model:
        loads.append(key)
        time.sleep(0.05)
        return Model(key)

    pool = pool_with(factory)
    results: list[Any] = []
    threads = [threading.Thread(target=lambda: results.append(pool.get("clap"))) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert loads == ["clap"]
    assert len({id(r) for r in results}) == 1 and len(results) == 8
    assert pool.loaded_keys() == ["clap"]


def test_different_keys_load_independently() -> None:
    pool = pool_with(lambda key, settings: Model(key))
    pool.get("clap")
    pool.get("glap")
    assert pool.loaded_keys() == ["clap", "glap"]
    assert pool.loader("clap")() is pool.get("clap")


def test_calls_to_one_model_never_overlap_and_other_attributes_are_forwarded() -> None:
    model = Model("clap")
    pool = pool_with(lambda key, settings: model)
    proxy = pool.get("clap")
    threads = [threading.Thread(target=lambda: proxy.embed_text(["a"])) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert model.max_active == 1
    assert proxy.key == "clap"
    with pytest.raises(AttributeError):
        proxy.nonexistent  # noqa: B018


def test_closing_a_proxy_does_not_unload_the_model_but_closing_the_pool_does() -> None:
    model = Model("clap")
    pool = pool_with(lambda key, settings: model)
    pool.get("clap").close()
    assert model.closed == 0
    pool.close()
    assert model.closed == 1 and pool.loaded_keys() == []
    with pytest.raises(ModelUnavailableError):
        pool.get("clap")


def test_without_torch_nothing_is_loaded() -> None:
    loads: list[str] = []
    pool = ModelPool(
        get_settings(), factory=lambda k, s: loads.append(k), torch_available=lambda: False
    )
    with pytest.raises(ModelUnavailableError, match="ml extra"):
        pool.get("clap")
    assert NO_TORCH_MESSAGE.startswith("text search needs the ml extra") and loads == []


def test_load_failures_become_unavailable_errors_without_details() -> None:
    def refuse(key: str, settings: Settings) -> Model:
        raise ModelLoadError("could not load model 'muq-mulan'")

    def crash(key: str, settings: Settings) -> Model:
        raise RuntimeError("secret path C:/Users/someone/token")

    with pytest.raises(ModelUnavailableError, match="could not load model 'muq-mulan'"):
        pool_with(refuse).get("muq-mulan")
    with pytest.raises(ModelUnavailableError) as info:
        pool_with(crash).get("clap")
    assert "secret" not in str(info.value) and "RuntimeError" in str(info.value)


def test_a_non_commercial_model_loads_and_stays_loaded_across_a_settings_update() -> None:
    model = Model("muq-mulan", commercial_ok=False)
    pool = pool_with(lambda k, s: model)
    pool.get("muq-mulan")
    pool.update_settings(get_settings(default_embedder="glap"))
    assert pool.loaded_keys() == ["muq-mulan"] and model.closed == 0


def test_the_factory_sees_the_current_settings() -> None:
    seen: list[str] = []

    def factory(key: str, settings: Settings) -> Model:
        seen.append(settings.default_embedder)
        return Model(key)

    pool = ModelPool(get_settings(), factory=factory, torch_available=lambda: True)
    pool.update_settings(get_settings(default_embedder="glap"))
    pool.get("clap")
    assert seen == ["glap"]
