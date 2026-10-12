"""Shared fixtures. Tests never touch the real repo's .secrets/ or settings file."""

import os
from pathlib import Path

import pytest

# Typer forces a colour terminal when GITHUB_ACTIONS (or FORCE_COLOR / PY_COLORS) is set, and the
# ANSI codes split option names in help output. Typer reads this once, when it is first imported,
# so set it here, before any test module imports the CLI: tests see plain text everywhere.
os.environ["_TYPER_FORCE_DISABLE_TERMINAL"] = "1"


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
