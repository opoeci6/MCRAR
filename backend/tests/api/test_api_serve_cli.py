"""`mcrar serve`: loopback by default, explicit opt-in for the network, uvicorn started lazily."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from mcrar import cli
from mcrar.cli import app
from mcrar.config import get_settings

runner = CliRunner()
REAL_PROBE = cli._probe_server  # `uvicorn_calls` replaces it with "the port is free"
REAL_CAN_BIND = cli._can_bind  # `probing` replaces it with "something holds the port"


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
    monkeypatch.setattr(cli, "_probe_server", lambda host, port: "free")  # no real port probe
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


# -- an MCRAR server that already runs, a foreign program on the port, --open -------------------


class FakeBrowser:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.urls: list[str] = []
        self.opened = threading.Event()
        monkeypatch.setattr("webbrowser.open", self.open)

    def open(self, url: str) -> bool:
        self.urls.append(url)
        self.opened.set()
        return True


@pytest.fixture
def browser(monkeypatch: pytest.MonkeyPatch) -> FakeBrowser:
    return FakeBrowser(monkeypatch)


def answering(monkeypatch: pytest.MonkeyPatch, body: Any, status: int = 200) -> list[str]:
    """Make every ``httpx.get`` answer with ``body`` as JSON; returns the requested URLs."""
    urls: list[str] = []

    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        urls.append(url)
        return httpx.Response(status, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    return urls


HEALTH = {"status": "ok", "version": "0.1.0", "models": []}


@pytest.fixture
def probing(monkeypatch: pytest.MonkeyPatch, uvicorn_calls: list[dict[str, Any]]) -> None:
    """Let `serve` probe the port for real (against the fake ``httpx.get`` of the test), with
    the port held by something, whatever really listens on this machine."""
    monkeypatch.setattr(cli, "_probe_server", REAL_PROBE)
    monkeypatch.setattr(cli, "_can_bind", lambda host, port: False)


def test_a_running_mcrar_is_reported_and_nothing_new_starts(
    monkeypatch: pytest.MonkeyPatch,
    uvicorn_calls: list[dict[str, Any]],
    probing: None,
    browser: FakeBrowser,
) -> None:
    urls = answering(monkeypatch, HEALTH)
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 0, result.output
    assert "MCRAR is already running at http://127.0.0.1:8000/" in result.output
    assert urls == ["http://127.0.0.1:8000/api/health"]
    assert uvicorn_calls == [] and browser.urls == []
    assert "MCRAR_API_PORT" not in os.environ


def test_a_running_mcrar_is_opened_with_the_open_flag(
    monkeypatch: pytest.MonkeyPatch,
    uvicorn_calls: list[dict[str, Any]],
    probing: None,
    browser: FakeBrowser,
) -> None:
    answering(monkeypatch, HEALTH)
    result = runner.invoke(app, ["serve", "--open", "--port", "9001"])
    assert result.exit_code == 0, result.output
    assert browser.urls == ["http://127.0.0.1:9001/"]
    assert uvicorn_calls == []


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"hello": "world"}, 200),
        ({"status": "ok"}, 200),  # no version: not MCRAR
        (["status", "ok"], 200),
        (HEALTH, 404),
    ],
)
def test_another_web_server_on_the_port_is_an_error(
    monkeypatch: pytest.MonkeyPatch,
    uvicorn_calls: list[dict[str, Any]],
    probing: None,
    browser: FakeBrowser,
    body: Any,
    status: int,
) -> None:
    answering(monkeypatch, body, status)
    result = runner.invoke(app, ["serve", "--open"])
    assert result.exit_code == 2
    assert result.stderr.startswith("error: port 8000 on 127.0.0.1 is in use by another program")
    assert "--port" in result.stderr
    assert uvicorn_calls == [] and browser.urls == []


def test_a_held_port_that_times_out_is_an_error(
    monkeypatch: pytest.MonkeyPatch, uvicorn_calls: list[dict[str, Any]], probing: None
) -> None:
    def slow(url: str, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(httpx, "get", slow)
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 2 and "--port" in result.stderr
    assert uvicorn_calls == []


def test_a_program_that_does_not_speak_http_on_the_port_is_an_error(
    monkeypatch: pytest.MonkeyPatch, uvicorn_calls: list[dict[str, Any]], probing: None
) -> None:
    def broken(url: str, **kwargs: Any) -> httpx.Response:
        raise httpx.RemoteProtocolError("not http")

    monkeypatch.setattr(httpx, "get", broken)
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 2 and "--port" in result.stderr
    assert uvicorn_calls == []


def refused(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", fake_get)


def test_a_port_nobody_answers_on_but_that_cannot_be_bound_is_an_error(
    monkeypatch: pytest.MonkeyPatch, uvicorn_calls: list[dict[str, Any]], probing: None
) -> None:
    refused(monkeypatch)
    monkeypatch.setattr(cli, "_can_bind", REAL_CAN_BIND)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        port = held.getsockname()[1]
        result = runner.invoke(app, ["serve", "--port", str(port)])
    assert result.exit_code == 2
    assert f"port {port} on 127.0.0.1 is in use by another program" in result.stderr
    assert uvicorn_calls == []


def test_a_free_port_starts_the_server_without_a_browser(
    monkeypatch: pytest.MonkeyPatch,
    uvicorn_calls: list[dict[str, Any]],
    probing: None,
    browser: FakeBrowser,
) -> None:
    def no_request(url: str, **kwargs: Any) -> httpx.Response:
        raise AssertionError("a port that can be bound needs no request")

    monkeypatch.setattr(httpx, "get", no_request)
    monkeypatch.setattr(cli, "_can_bind", REAL_CAN_BIND)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    result = runner.invoke(app, ["serve", "--port", str(port)])
    assert result.exit_code == 0, result.output
    assert [c["port"] for c in uvicorn_calls] == [port]
    assert browser.urls == []


def test_open_waits_for_the_health_answer_then_opens_the_browser_once(
    monkeypatch: pytest.MonkeyPatch, uvicorn_calls: list[dict[str, Any]], browser: FakeBrowser
) -> None:
    answers = iter([httpx.ConnectError("starting"), httpx.ConnectError("starting"), HEALTH])
    urls: list[str] = []

    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        urls.append(url)
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(200, json=answer, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr("time.sleep", lambda s: None)
    result = runner.invoke(app, ["serve", "--open", "--host", "localhost", "--port", "9002"])
    assert result.exit_code == 0, result.output
    assert uvicorn_calls[0]["port"] == 9002
    assert browser.opened.wait(5.0)
    assert browser.urls == ["http://127.0.0.1:9002/"]
    assert urls == ["http://127.0.0.1:9002/api/health"] * 3


def test_open_gives_up_quietly_when_the_server_never_answers(
    monkeypatch: pytest.MonkeyPatch, browser: FakeBrowser
) -> None:
    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr("time.sleep", lambda s: None)
    cli._open_browser_when_ready("http://127.0.0.1:1/", timeout_s=0.05)
    assert not browser.opened.wait(0.3) and browser.urls == []


@pytest.mark.parametrize(
    ("host", "url"),
    [
        ("127.0.0.1", "http://127.0.0.1:8000/"),
        ("localhost", "http://127.0.0.1:8000/"),
        ("0.0.0.0", "http://127.0.0.1:8000/"),
        ("::", "http://[::1]:8000/"),
        ("::1", "http://[::1]:8000/"),
        ("[::1]", "http://[::1]:8000/"),
        ("192.168.1.20", "http://192.168.1.20:8000/"),
    ],
)
def test_the_browser_url(host: str, url: str) -> None:
    assert cli._browser_url(host, 8000) == url


def test_python_dash_m_mcrar_runs_the_cli() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mcrar", "serve", "--help"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "--open" in result.stdout and "Usage: mcrar serve" in result.stdout


def test_python_dash_m_mcrar_does_not_import_torch() -> None:
    code = "\n".join(
        [
            "import runpy, sys",
            "sys.argv = ['mcrar', '--help']",
            "try:",
            "    runpy.run_module('mcrar', run_name='__main__')",
            "except SystemExit:",
            "    pass",
            "bad = [m for m in ('torch', 'transformers', 'huggingface_hub') if m in sys.modules]",
            "assert not bad, bad",
        ]
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False, timeout=60
    )
    assert result.returncode == 0, result.stderr
