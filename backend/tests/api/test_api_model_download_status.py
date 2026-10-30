"""``ModelPool.status`` tells a model that is downloading its weights from one that is loading."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from mcrar.api.models import ModelPool
from mcrar.config import Settings, get_settings
from mcrar.ml import ModelLoadError

WAIT_S = 5.0


class Model:
    def __init__(self, key: str) -> None:
        self.key = key

    def close(self) -> None:
        pass


def status_while_loading(monkeypatch: pytest.MonkeyPatch, progress: Any) -> dict[str, Any]:
    """The status entry of ``clap`` while its factory is blocked; ``progress`` is what the
    registry answers for it (a dict, or None for "not downloading")."""
    entered, proceed = threading.Event(), threading.Event()
    monkeypatch.setattr("mcrar.api.models.download_progress", lambda key: progress)

    def factory(key: str, settings: Settings) -> Model:
        entered.set()
        assert proceed.wait(WAIT_S)
        return Model(key)

    pool = ModelPool(get_settings(), factory=factory, torch_available=lambda: True)
    loader = threading.Thread(target=lambda: pool.get("clap"))
    loader.start()
    try:
        assert entered.wait(WAIT_S)
        (entry,) = pool.status()
    finally:
        proceed.set()
        loader.join(WAIT_S)
    return entry


def test_a_model_that_is_downloading_reports_the_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = status_while_loading(monkeypatch, {"done_bytes": 300, "total_bytes": 1000})
    assert entry == {
        "key": "clap",
        "state": "loading",
        "device": None,
        "dtype": None,
        "phase": "downloading",
        "download": {"done_bytes": 300, "total_bytes": 1000},
    }


def test_the_total_may_be_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = status_while_loading(monkeypatch, {"done_bytes": 5, "total_bytes": None})
    assert entry["phase"] == "downloading"
    assert entry["download"] == {"done_bytes": 5, "total_bytes": None}


def test_a_model_that_is_not_downloading_is_in_the_loading_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = status_while_loading(monkeypatch, None)
    assert entry == {
        "key": "clap",
        "state": "loading",
        "device": None,
        "dtype": None,
        "phase": "loading",
    }


def test_ready_and_error_entries_have_no_phase() -> None:
    def factory(key: str, settings: Settings) -> Model:
        if key == "glap":
            raise ModelLoadError("could not load model 'glap'")
        return Model(key)

    pool = ModelPool(get_settings(), factory=factory, torch_available=lambda: True)
    pool.get("clap")
    with pytest.raises(Exception, match="could not load model 'glap'"):
        pool.get("glap")
    entries = {e["key"]: e for e in pool.status()}
    assert entries["clap"] == {"key": "clap", "state": "ready", "device": None, "dtype": None}
    assert entries["glap"]["state"] == "error"
    assert "phase" not in entries["glap"] and "download" not in entries["glap"]


def test_the_real_registry_answers_none_for_a_model_nobody_downloads() -> None:
    from mcrar.api.models import download_progress

    assert download_progress("clap") is None
