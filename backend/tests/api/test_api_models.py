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


# -- release and status ------------------------------------------------------------------------

WAIT_S = 10.0


def test_release_unloads_the_models_that_are_not_kept() -> None:
    made: dict[str, Model] = {}

    def factory(key: str, settings: Settings) -> Model:
        made[key] = Model(key)
        return made[key]

    pool = pool_with(factory)
    for key in ("clap", "glap", "muq-mulan"):
        pool.get(key)
    assert pool.release(keep={"glap"}) == ["clap", "muq-mulan"]
    assert pool.loaded_keys() == ["glap"]
    assert (made["clap"].closed, made["glap"].closed, made["muq-mulan"].closed) == (1, 0, 1)
    assert pool.release(keep=["glap"]) == []  # nothing left to release
    again = pool.get("clap")  # a request after the release loads afresh
    assert again.embed_text(["a"]).shape == (1, 2) and made["clap"].closed == 0
    pool.close()
    assert made["glap"].closed == 1 and made["clap"].closed == 1  # no double close of the others


def test_a_model_that_is_loading_is_not_released() -> None:
    entered, proceed = threading.Event(), threading.Event()

    def factory(key: str, settings: Settings) -> Model:
        if key == "glap":
            entered.set()
            assert proceed.wait(WAIT_S)
        return Model(key)

    pool = pool_with(factory)
    pool.get("clap")
    loader = threading.Thread(target=lambda: pool.get("glap"))
    loader.start()
    assert entered.wait(WAIT_S)
    assert pool.release(keep=set()) == ["clap"]  # glap is not in the pool yet
    proceed.set()
    loader.join(WAIT_S)
    assert pool.loaded_keys() == ["glap"]


def test_a_released_model_that_is_still_held_fails_cleanly() -> None:
    model = Model("clap")
    pool = pool_with(lambda key, settings: model)
    held = pool.get("clap")
    pool.release(keep=set())
    with pytest.raises(ModelUnavailableError, match="model 'clap' was unloaded.*try again"):
        held.embed_text(["a"])
    with pytest.raises(ModelUnavailableError, match="was unloaded"):
        held.embed_audio([np.zeros(4, dtype=np.float32)])
    assert model.closed == 1 and model.active == 0
    assert held.key == "clap"  # forwarded attributes still work


def test_unloading_waits_for_the_embedding_in_flight() -> None:
    entered, proceed = threading.Event(), threading.Event()

    class Slow(Model):
        def embed_text(self, texts: Any) -> np.ndarray:
            entered.set()
            assert proceed.wait(WAIT_S)
            return super().embed_text(texts)

    model = Slow("clap")
    pool = pool_with(lambda key, settings: model)
    held = pool.get("clap")
    results: list[Any] = []
    embedding = threading.Thread(target=lambda: results.append(held.embed_text(["a"])))
    embedding.start()
    assert entered.wait(WAIT_S)
    releasing = threading.Thread(target=lambda: pool.release(keep=set()))
    releasing.start()
    assert pool.loaded_keys() == []  # popped at once, so new requests load afresh...
    releasing.join(0.2)
    assert releasing.is_alive() and model.closed == 0  # ...but the close waits for the embedding
    proceed.set()
    embedding.join(WAIT_S)
    releasing.join(WAIT_S)
    assert len(results) == 1 and model.closed == 1


def test_a_failing_close_does_not_stop_the_release() -> None:
    class Broken(Model):
        def close(self) -> None:
            raise RuntimeError("secret path C:/Users/someone/token")

    made: dict[str, Model] = {}

    def factory(key: str, settings: Settings) -> Model:
        made[key] = Broken(key) if key == "clap" else Model(key)
        return made[key]

    pool = pool_with(factory)
    pool.get("clap")
    pool.get("glap")
    assert pool.release(keep=set()) == ["clap", "glap"]
    assert made["glap"].closed == 1 and pool.loaded_keys() == []


def test_status_tells_loading_ready_and_error_per_key() -> None:
    entered, proceed = threading.Event(), threading.Event()

    class Placed(Model):
        device = "cuda"
        dtype = "fp16"

    def factory(key: str, settings: Settings) -> Model:
        if key == "glap":
            entered.set()
            assert proceed.wait(WAIT_S)
            return Placed(key)
        if key == "muq-mulan":
            raise ModelLoadError("could not load model 'muq-mulan'")
        return Model(key)

    pool = pool_with(factory)
    assert pool.status() == []
    pool.get("clap")
    with pytest.raises(ModelUnavailableError):
        pool.get("muq-mulan")
    loader = threading.Thread(target=lambda: pool.get("glap"))
    loader.start()
    assert entered.wait(WAIT_S)
    assert pool.status() == [
        {"key": "clap", "state": "ready", "device": None, "dtype": None},
        {"key": "glap", "state": "loading", "device": None, "dtype": None, "phase": "loading"},
        {
            "key": "muq-mulan",
            "state": "error",
            "device": None,
            "dtype": None,
            "error": "could not load model 'muq-mulan'",
        },
    ]
    proceed.set()
    loader.join(WAIT_S)
    states = {s["key"]: s for s in pool.status()}
    assert states["glap"] == {"key": "glap", "state": "ready", "device": "cuda", "dtype": "fp16"}
    pool.release(keep={"glap"})  # unloads clap and forgets the error of muq-mulan
    assert [s["key"] for s in pool.status()] == ["glap"]


def test_the_error_of_a_key_goes_when_it_loads_later() -> None:
    attempts: list[str] = []

    def factory(key: str, settings: Settings) -> Model:
        attempts.append(key)
        if len(attempts) == 1:
            raise RuntimeError("boom")
        return Model(key)

    pool = pool_with(factory)
    with pytest.raises(ModelUnavailableError):
        pool.get("clap")
    assert pool.status()[0]["error"] == "could not load model 'clap' (RuntimeError)"
    pool.get("clap")
    assert pool.status() == [{"key": "clap", "state": "ready", "device": None, "dtype": None}]


def test_without_torch_status_reports_the_missing_extra() -> None:
    pool = ModelPool(get_settings(), factory=lambda k, s: Model(k), torch_available=lambda: False)
    with pytest.raises(ModelUnavailableError):
        pool.get("clap")
    assert pool.status() == [
        {"key": "clap", "state": "error", "device": None, "dtype": None, "error": NO_TORCH_MESSAGE}
    ]
