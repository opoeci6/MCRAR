"""Shared fixtures. Tests never touch the real repo's .secrets/ or settings file."""

import os
from pathlib import Path

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Tests marked ``models`` load the real embedding models (large downloads, GPU): they run
    only when asked for with ``-m models``."""
    if "models" in (config.getoption("markexpr") or ""):
        return
    skip = pytest.mark.skip(reason="real-model test; run with: pytest -m models")
    for item in items:
        if "models" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point MCRAR_HOME at tmp_path and drop every other MCRAR_* variable."""
    for key in list(os.environ):
        if key.upper().startswith("MCRAR_"):
            monkeypatch.delenv(key)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("MCRAR_HOME", str(home))
    return home
