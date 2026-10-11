"""Shared fixtures. Tests never touch the real repo's .secrets/ or settings file."""

import os
from pathlib import Path

import pytest


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
