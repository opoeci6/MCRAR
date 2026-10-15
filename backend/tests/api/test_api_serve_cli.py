"""`mcrar serve`: loopback by default, explicit opt-in for the network, uvicorn started lazily."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

import pytest
from typer.testing import CliRunner

from mcrar.cli import app
from mcrar.config import get_settings

runner = CliRunner()


@pytest.fixture
def uvicorn_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace ``uvicorn.run`` so nothing listens; record the call and what the app would read."""
    calls: list[dict[str, Any]] = []
    # Registered first so the variables `serve` sets are removed again after the test.
    for name in ("MCRAR_API_HOST", "MCRAR_API_PORT", "MCRAR_API_WARM"):
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)

    def fake_run(target: str, **kwargs: Any) -> None:
        settings = get_settings()  # what the app factory would see inside uvicorn
        calls.append(
            {
                "target": target,
                **kwargs,
                "env_host": settings.api_host,
                "env_port": settings.api_port,
                "warm": os.environ.get("MCRAR_API_WARM"),
            }
        )

    monkeypatch.setattr("uvicorn.run", fake_run)
    return calls


def test_serve_defaults_to_the_settings_and_the_app_factory(
    uvicorn_calls: list[dict[str, Any]],
) -> None:
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 0, result.output
    assert uvicorn_calls == [
        {
            "target": "mcrar.api.app:create_app",
            "factory": True,
            "host": "127.0.0.1",
            "port": 8000,
            "reload": False,
            "env_host": "127.0.0.1",
            "env_port": 8000,
            "warm": None,
        }
    ]


def test_serve_passes_host_port_reload_and_warm(uvicorn_calls: list[dict[str, Any]]) -> None:
    result = runner.invoke(
        app, ["serve", "--host", "localhost", "--port", "9001", "--warm", "--reload"]
    )
    assert result.exit_code == 0, result.output
    call = uvicorn_calls[0]
    assert (call["host"], call["port"], call["reload"], call["factory"]) == (
        "localhost",
        9001,
        True,
        True,
    )
    assert (call["env_host"], call["env_port"], call["warm"]) == ("localhost", 9001, "1")


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.20", "example.com", "::"])
def test_serve_refuses_a_non_loopback_host_without_allow_remote(
    uvicorn_calls: list[dict[str, Any]], host: str
) -> None:
    result = runner.invoke(app, ["serve", "--host", host])
    assert result.exit_code == 2
    assert result.stderr.startswith(f"error: refusing to listen on {host}")
    assert "--allow-remote" in result.stderr
    assert uvicorn_calls == []


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2", "localhost", "::1", "[::1]"])
def test_serve_accepts_loopback_hosts(uvicorn_calls: list[dict[str, Any]], host: str) -> None:
    assert runner.invoke(app, ["serve", "--host", host]).exit_code == 0
    assert uvicorn_calls and uvicorn_calls[0]["host"] == host


def test_allow_remote_listens_with_a_warning(uvicorn_calls: list[dict[str, Any]]) -> None:
    result = runner.invoke(app, ["serve", "--host", "0.0.0.0", "--allow-remote"])
    assert result.exit_code == 0, result.output
    assert result.stderr.startswith("warning: listening on 0.0.0.0 without a login")
    assert uvicorn_calls[0]["host"] == "0.0.0.0"


def test_a_non_loopback_api_host_in_the_settings_is_refused_too(
    monkeypatch: pytest.MonkeyPatch, uvicorn_calls: list[dict[str, Any]]
) -> None:
    monkeypatch.setenv("MCRAR_API_HOST", "0.0.0.0")
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 2 and uvicorn_calls == []


def test_serve_rejects_a_bad_port(uvicorn_calls: list[dict[str, Any]]) -> None:
    assert runner.invoke(app, ["serve", "--port", "70000"]).exit_code != 0
    assert uvicorn_calls == []


def test_importing_the_cli_does_not_import_uvicorn() -> None:
    code = "import sys, mcrar.cli; assert 'uvicorn' not in sys.modules"
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False, timeout=30
    )
    assert result.returncode == 0, result.stderr
