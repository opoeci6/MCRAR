"""Giving the VRAM back: a changed default model, the end of a job, and what ``/api/health`` says.

The pool's factory is replaced by one that hands out a fresh fake per load, so the tests can see
which instance was closed. No torch, no sleeps: the tests wait on events and on the pool itself.
"""

from __future__ import annotations

import sys
import threading
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from api_support import ApiClient, make_client

from mcrar.api.jobs import JobManager
from mcrar.api.models import ModelUnavailableError
from mcrar.api.state import AppState
from mcrar.config import Settings
from mcrar.ml import ModelLoadError

WAIT_S = 20.0
MB = 1024 * 1024


class Fake:
    def __init__(self, key: str) -> None:
        self.key = key
        self.model_id = f"{key}@test"
        self.closed = 0

    def embed_text(self, texts: Any) -> np.ndarray:
        return np.ones((len(texts), 2), dtype=np.float32)

    embed_audio = embed_text

    def close(self) -> None:
        self.closed += 1


class Fleet:
    """The pool factory: one new ``Fake`` per load, kept per key."""

    def __init__(self) -> None:
        self.made: dict[str, list[Fake]] = defaultdict(list)

    def __call__(self, key: str, settings: Settings) -> Fake:
        fake = Fake(key)
        self.made[key].append(fake)
        return fake


def fleet_state(client: ApiClient) -> tuple[AppState, Fleet]:
    state: AppState = client.app.state.mcrar
    fleet = Fleet()
    state.pool._factory = fleet
    return state, fleet


def switch_default(client: ApiClient, key: str) -> None:
    assert client.put("/api/settings", json={"default_embedder": key}).status_code == 200


def wait_for_job_thread(state: AppState) -> None:
    """Block until the worker thread of the last job is gone (its ``on_idle`` hook has run)."""
    thread = state.jobs._thread
    assert thread is not None
    thread.join(WAIT_S)
    assert not thread.is_alive()


# -- a changed default model ---------------------------------------------------------------------


def test_switching_the_default_unloads_the_old_model_and_loads_the_new_one(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        state, fleet = fleet_state(client)
        state.pool.get("clap")
        switch_default(client, "glap")
        state.pool.get("glap")  # waits for the background load when it is still running
        assert state.pool.loaded_keys() == ["glap"]
        assert [f.closed for f in fleet.made["clap"]] == [1]
        assert len(fleet.made["glap"]) == 1 and fleet.made["glap"][0].closed == 0
        # a settings change that leaves the default alone does not touch the models
        client.put("/api/settings", json={"search": {"pool_size": 77}})
        assert state.pool.loaded_keys() == ["glap"] and len(fleet.made["glap"]) == 1


def test_without_the_ml_extra_a_switch_loads_nothing(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path, torch=False) as client:
        state, fleet = fleet_state(client)
        switch_default(client, "glap")  # no torch: nothing to load, and no error
        assert state.pool.loaded_keys() == [] and not fleet.made


def test_a_running_job_keeps_the_models_until_it_ends(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        state, fleet = fleet_state(client)
        loaded, gate = threading.Event(), threading.Event()

        def run(sink: Any) -> None:
            state.pool.get("clap")
            loaded.set()
            assert gate.wait(WAIT_S)

        state.jobs.start("test", {}, run)
        assert loaded.wait(WAIT_S)
        switch_default(client, "glap")
        state.pool.get("glap")
        assert state.pool.loaded_keys() == ["clap", "glap"]  # the job may still use CLAP
        assert fleet.made["clap"][0].closed == 0
        gate.set()
        wait_for_job_thread(state)
        assert state.pool.loaded_keys() == ["glap"]
        assert fleet.made["clap"][0].closed == 1 and fleet.made["glap"][0].closed == 0


def test_a_job_that_tagged_with_clap_leaves_only_the_default_loaded(tmp_path: Path) -> None:
    with make_client(tmp_path, settings_overrides={"default_embedder": "glap"}) as client:
        state, fleet = fleet_state(client)
        state.pool.get("glap")
        job = state.jobs.start("test", {}, lambda sink: state.pool.get("clap") and None)
        wait_for_job_thread(state)
        assert job.status == "done"
        assert state.pool.loaded_keys() == ["glap"]
        assert fleet.made["clap"][0].closed == 1 and fleet.made["glap"][0].closed == 0


def test_a_failed_job_also_releases(tmp_path: Path) -> None:
    with make_client(tmp_path, settings_overrides={"default_embedder": "glap"}) as client:
        state, fleet = fleet_state(client)

        def run(sink: Any) -> None:
            state.pool.get("clap")
            raise RuntimeError("boom")

        job = state.jobs.start("test", {}, run)
        wait_for_job_thread(state)
        assert job.status == "failed"
        assert state.pool.loaded_keys() == [] and fleet.made["clap"][0].closed == 1


def test_a_model_held_by_a_search_when_the_default_changes_answers_503(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        state, _ = fleet_state(client)
        held = state.pool.get("clap")
        switch_default(client, "glap")
        with pytest.raises(ModelUnavailableError, match="was unloaded"):
            held.embed_text(["a"])


# -- the job manager hooks -----------------------------------------------------------------------


def test_on_idle_runs_after_the_job_ended_and_its_errors_stay_inside() -> None:
    seen: list[str] = []
    ended = threading.Event()
    box: dict[str, JobManager] = {}

    def on_idle() -> None:
        seen.append(box["jobs"].list()[0].status)  # the final status is already set
        ended.set()
        raise RuntimeError("hook bug")

    jobs = box["jobs"] = JobManager(on_idle=on_idle)
    jobs.start("t", {}, lambda sink: None)
    assert ended.wait(WAIT_S)
    assert seen == ["done"]


def test_run_if_idle_does_not_run_while_a_job_runs() -> None:
    gate, started = threading.Event(), threading.Event()
    jobs = JobManager()
    ran: list[int] = []
    assert jobs.run_if_idle(lambda: ran.append(1)) is True

    def run(sink: Any) -> None:
        started.set()
        assert gate.wait(WAIT_S)

    jobs.start("t", {}, run)
    assert started.wait(WAIT_S)
    assert jobs.run_if_idle(lambda: ran.append(2)) is False
    gate.set()
    thread = jobs._thread
    assert thread is not None
    thread.join(WAIT_S)
    assert jobs.run_if_idle(lambda: ran.append(3)) is True
    assert ran == [1, 3]


# -- /api/health ---------------------------------------------------------------------------------


def health(client: ApiClient) -> dict[str, Any]:
    return client.get("/api/health").json()


def test_health_shows_loading_ready_and_error_models(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        state, _ = fleet_state(client)
        entered, proceed = threading.Event(), threading.Event()

        class Placed(Fake):
            device = "cuda"
            dtype = "fp16"

        def factory(key: str, settings: Settings) -> Fake:
            if key == "muq-mulan":
                raise ModelLoadError("could not load model 'muq-mulan'")
            if key == "glap":
                entered.set()
                assert proceed.wait(WAIT_S)
                return Placed(key)
            return Fake(key)

        state.pool._factory = factory
        state.pool.get("clap")
        loading = threading.Thread(target=lambda: state.pool.get("glap"))
        loading.start()
        assert entered.wait(WAIT_S)
        with pytest.raises(ModelUnavailableError, match="muq-mulan"):
            state.pool.get("muq-mulan")
        body = health(client)
        assert body["models_loaded"] == ["clap"]  # kept for older clients: only the ready ones
        assert body["models"] == [
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
        loading.join(WAIT_S)
        ready = {m["key"]: m for m in health(client)["models"]}
        assert ready["glap"] == {"key": "glap", "state": "ready", "device": "cuda", "dtype": "fp16"}
        assert health(client)["models_loaded"] == ["clap", "glap"]


def test_health_has_no_gpu_when_torch_was_never_imported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    with make_client(tmp_path) as client:
        assert health(client)["gpu"] is None
        assert "torch" not in sys.modules  # the health route never imports it


def fake_torch(*, available: bool = True, allocated: int = 0, reserved: int = 0) -> Any:
    def broken() -> int:
        raise RuntimeError("driver")

    return SimpleNamespace(
        cuda=SimpleNamespace(
            is_available=lambda: available,
            memory_allocated=(lambda: allocated) if available else broken,
            memory_reserved=(lambda: reserved) if available else broken,
        )
    )


def test_health_reports_the_vram_when_torch_is_loaded_and_cuda_is_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(
        sys.modules, "torch", fake_torch(allocated=1500 * MB + 7, reserved=2048 * MB)
    )
    with make_client(tmp_path) as client:
        assert health(client)["gpu"] == {"vram_allocated_mb": 1500, "vram_reserved_mb": 2048}


def test_health_has_no_gpu_without_cuda_or_when_the_driver_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path) as client:
        monkeypatch.setitem(sys.modules, "torch", fake_torch(available=False))
        assert health(client)["gpu"] is None
        broken = fake_torch()
        broken.cuda.memory_reserved = lambda: 1 / 0
        monkeypatch.setitem(sys.modules, "torch", broken)
        assert client.get("/api/health").status_code == 200 and health(client)["gpu"] is None
