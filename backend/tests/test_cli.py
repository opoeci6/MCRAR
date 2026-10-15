import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mcrar import __version__, cli
from mcrar.cli import PROJECT_LOCAL_PATH_VARS, app
from mcrar.secrets import SecretStore

runner = CliRunner()
VALUE = "very-secret-value-42"


def _project_local_env(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for var in PROJECT_LOCAL_PATH_VARS:
        monkeypatch.setenv(var, str(home / ".cache" / var))
    monkeypatch.setenv("PYTHONNOUSERSITE", "1")
    monkeypatch.setattr(sys, "executable", str(home / ".venv" / "Scripts" / "python.exe"))
    monkeypatch.setattr(sys, "base_prefix", str(home / ".tools" / "python"))


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_config_show_has_no_secrets(isolated_env: Path) -> None:
    runner.invoke(app, ["secrets", "set", "token", "--stdin"], input=VALUE)
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["default_embedder"] == "clap"
    assert data["secrets_backend"] == "file"
    assert VALUE not in result.output
    assert "token" not in result.output


def test_secrets_set_stdin_then_list(isolated_env: Path) -> None:
    result = runner.invoke(app, ["secrets", "set", "token", "--stdin"], input=VALUE + "\n")
    assert result.exit_code == 0, result.output
    assert VALUE not in result.output
    listed = runner.invoke(app, ["secrets", "list"])
    assert listed.exit_code == 0
    assert "token" in listed.output
    assert "file" in listed.output
    assert VALUE not in listed.output
    # the trailing newline is stripped from the stored value
    assert SecretStore().get("token") == VALUE


def test_secrets_set_hidden_prompt(isolated_env: Path) -> None:
    result = runner.invoke(app, ["secrets", "set", "token"], input=f"{VALUE}\n{VALUE}\n")
    assert result.exit_code == 0, result.output
    assert VALUE not in result.output


def test_secrets_delete(isolated_env: Path) -> None:
    runner.invoke(app, ["secrets", "set", "token", "--stdin"], input=VALUE)
    assert runner.invoke(app, ["secrets", "delete", "token"]).exit_code == 0
    assert runner.invoke(app, ["secrets", "delete", "token"]).exit_code == 1
    assert "(no secrets)" in runner.invoke(app, ["secrets", "list"]).output


def test_secrets_invalid_name() -> None:
    result = runner.invoke(app, ["secrets", "set", "Bad-Name", "--stdin"], input=VALUE)
    assert result.exit_code == 2
    assert VALUE not in result.output


def test_doctor_fails_when_env_not_loaded() -> None:
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "FAIL" in result.output


def test_doctor_passes_when_project_local(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project_local_env(isolated_env, monkeypatch)
    monkeypatch.setattr(cli.shutil, "which", lambda _name: None)
    monkeypatch.setattr(cli, "_webview2_version", lambda: None)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "nvidia-smi not found" in result.output  # system checks warn but never fail
    assert "WebView2" in result.output


def test_doctor_flags_var_outside_home(
    isolated_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project_local_env(isolated_env, monkeypatch)
    monkeypatch.setenv("HF_HOME", str(tmp_path / "outside"))
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "HF_HOME points outside" in result.output


def test_doctor_flags_python_outside_home(
    isolated_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project_local_env(isolated_env, monkeypatch)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "system" / "python.exe"))
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "executable is outside" in result.output
