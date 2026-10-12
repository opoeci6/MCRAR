"""Basic CLI commands stay independent of audio and training libraries."""

from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.parametrize("args", [[], ["--help"], ["secrets", "list"]])
def test_cli_startup_does_not_import_audio_or_training_libraries(args: list[str]) -> None:
    code = """
import sys
import mcrar.cli

if sys.argv[1:]:
    from typer.testing import CliRunner
    result = CliRunner().invoke(mcrar.cli.app, sys.argv[1:])
    assert result.exit_code == 0, result.output

heavy = {"librosa", "scipy", "torch", "sklearn"}
loaded = sorted({name.split(".")[0] for name in sys.modules} & heavy)
assert not loaded, loaded
"""
    result = subprocess.run(
        [sys.executable, "-c", code, *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
