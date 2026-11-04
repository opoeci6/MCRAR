"""`mcrar desktop`: the window, the server thread, closing, the browser fallback and the log file.

pywebview is not installed in CI, so a fake ``webview`` module stands in for it; the fake server
blocks in ``run()`` until ``should_exit`` is set, like uvicorn's.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import types
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from mcrar import cli, desktop
from mcrar.config import ConfigError, get_settings

runner = CliRunner()
PORT = 8123
URL = f"http://127.0.0.1:{PORT}/"
HEALTH = {"status": "ok", "version": "0.2.0", "models": []}


# -- fakes ------------------------------------------------------------------------------------


class FakeEvent:
    def __init__(self) -> None:
        self.handlers: list[Any] = []

    def __iadd__(self, handler: Any) -> FakeEvent:
        self.handlers.append(handler)
        return self


class FakeWindow:
    def __init__(self) -> None:
        self.events = types.SimpleNamespace(closing=FakeEvent())
        self.loaded_urls: list[str] = []
        self.loaded_html: list[str] = []
        self.dialogs: list[tuple[str, str]] = []
        self.dialog_answer: bool | None = True
        self.file_dialogs: list[tuple[int, str]] = []
        self.file_dialog_result: Any = None

    def load_url(self, url: str) -> None:
        self.loaded_urls.append(url)

    def load_html(self, html: str) -> None:
        self.loaded_html.append(html)

    def create_confirmation_dialog(self, title: str, message: str) -> bool | None:
        self.dialogs.append((title, message))
        return self.dialog_answer

    def create_file_dialog(self, dialog_type: int, directory: str = "") -> Any:
        self.file_dialogs.append((dialog_type, directory))
        return self.file_dialog_result

    def close(self) -> bool:
        """What the user does: run the closing handlers; True when the window really closes."""
        return not any(handler() is False for handler in self.events.closing.handlers)


class FakeWebview(types.ModuleType):
    """Stands in for pywebview. ``start`` runs the startup function, then ``on_start``."""

    class FileDialog:
        OPEN = 10
        FOLDER = 20
        SAVE = 30

    def __init__(self) -> None:
        super().__init__("webview")
        self.settings: dict[str, Any] = {
            "ALLOW_DOWNLOADS": False,
            "OPEN_EXTERNAL_LINKS_IN_BROWSER": False,
        }
        self.window = FakeWindow()
        self.window_args: dict[str, Any] = {}
        self.start_kwargs: dict[str, Any] = {}
        self.on_start: Any = None
        self.settings_at_start: dict[str, Any] = {}

    def create_window(self, title: str, **kwargs: Any) -> FakeWindow:
        self.window_args = {"title": title, **kwargs}
        return self.window

    def start(self, **kwargs: Any) -> None:
        self.start_kwargs = kwargs
        self.settings_at_start = dict(self.settings)
        kwargs["func"](*kwargs["args"])
        if self.on_start is not None:
            self.on_start(self)


class FakeServer:
    """``run()`` blocks until ``should_exit`` is set; ``block=False`` returns at once."""

    def __init__(self, port: int, to_file: bool, block: bool = True) -> None:
        self.port = port
        self.to_file = to_file
        self.block = block
        self.force_exit = False
        self.ran = threading.Event()
        self._exit = threading.Event()

    @property
    def should_exit(self) -> bool:
        return self._exit.is_set()

    @should_exit.setter
    def should_exit(self, value: bool) -> None:
        if value:
            self._exit.set()

    def run(self) -> None:
        self.ran.set()
        if self.block:
            self._exit.wait(10)


class Env:
    """Everything a test steers: the fake webview, the servers made, boxes shown, jobs."""

    def __init__(self) -> None:
        self.webview = FakeWebview()
        self.servers: list[FakeServer] = []
        self.server_blocks = True
        self.boxes: list[tuple[str, bool]] = []
        self.opened_in_browser: list[str] = []
        self.jobs: list[dict[str, Any]] = []
        self.requested: list[str] = []
        self.health_failures = 0
        self.health_down = False

    @property
    def window(self) -> FakeWindow:
        return self.webview.window

    def run(self, *, console_log: bool = False, warm: bool = False, port: int = PORT) -> int:
        return desktop.run_desktop(get_settings(), port=port, warm=warm, console_log=console_log)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, isolated_env: Path) -> Env:
    state = Env()
    monkeypatch.setitem(sys.modules, "webview", state.webview)
    monkeypatch.setattr(cli, "_probe_server", lambda host, port: "free")
    monkeypatch.setattr(cli, "_webview2_version", lambda: "130.0")
    monkeypatch.setattr(desktop, "HEALTH_INTERVAL_S", 0.001)
    monkeypatch.setattr(desktop, "SHUTDOWN_TIMEOUT_S", 5.0)
    monkeypatch.delenv(desktop.FORCE_BROWSER_ENV, raising=False)
    for name in ("MCRAR_API_HOST", "MCRAR_API_PORT", "MCRAR_API_WARM"):
        monkeypatch.setenv(name, "x")  # so monkeypatch removes what the code under test sets
        monkeypatch.delenv(name)

    def make_server(port: int, to_file: bool) -> FakeServer:
        server = FakeServer(port, to_file, state.server_blocks)
        state.servers.append(server)
        return server

    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        state.requested.append(url)
        request = httpx.Request("GET", url)
        if url.endswith("/api/health"):
            if state.health_down:
                raise httpx.ConnectError("down", request=request)
            if state.health_failures:
                state.health_failures -= 1
                raise httpx.ConnectError("not yet", request=request)
            return httpx.Response(200, json=HEALTH, request=request)
        if url.endswith("/api/jobs"):
            return httpx.Response(200, json={"jobs": state.jobs}, request=request)
        return httpx.Response(404, request=request)

    monkeypatch.setattr(desktop, "_make_server", make_server)
    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(
        desktop, "_message_box", lambda text, *, error=True: state.boxes.append((text, error))
    )
    monkeypatch.setattr(cli, "_open_browser_when_ready", state.opened_in_browser.append)
    monkeypatch.setattr(desktop.webbrowser, "open", state.opened_in_browser.append)
    return state


def _server_thread(env: Env) -> threading.Thread:
    return env.webview.start_kwargs["args"][2]


# -- the window -------------------------------------------------------------------------------


def test_the_window_opens_on_the_server_once_it_answers(env: Env, isolated_env: Path) -> None:
    env.health_failures = 3
    assert env.run(warm=True) == 0

    assert env.window.loaded_urls == [URL]
    assert env.window.loaded_html == []
    assert env.requested.count(URL + "api/health") == 4
    args = env.webview.window_args
    assert args["title"] == "MCRAR"
    assert args["html"] == desktop.LOADING_HTML
    assert (args["width"], args["height"]) == (1280, 820)
    assert args["min_size"] == (420, 560)
    assert isinstance(args["js_api"], desktop.DesktopApi)
    assert env.webview.settings_at_start["ALLOW_DOWNLOADS"] is True
    assert env.webview.settings_at_start["OPEN_EXTERNAL_LINKS_IN_BROWSER"] is True
    kwargs = env.webview.start_kwargs
    assert kwargs["private_mode"] is False
    assert Path(kwargs["storage_path"]) == isolated_env / ".cache" / "webview"
    assert kwargs["icon"] is None  # no favicon.ico in the temporary home
    assert [(s.port, s.to_file) for s in env.servers] == [(PORT, True)]
    assert (
        desktop.os.environ["MCRAR_API_HOST"],
        desktop.os.environ["MCRAR_API_PORT"],
        desktop.os.environ["MCRAR_API_WARM"],
    ) == ("127.0.0.1", str(PORT), "1")


def test_the_loading_page_follows_the_colour_scheme_and_loads_nothing_external() -> None:
    assert "prefers-color-scheme" in desktop.LOADING_HTML
    assert "Starting MCRAR" in desktop.LOADING_HTML
    assert "http" not in desktop.LOADING_HTML


def test_quitting_stops_the_server(env: Env) -> None:
    def user_closes(webview: FakeWebview) -> None:
        assert webview.window.close() is True
        assert not env.servers[0].should_exit  # only after the window loop ended

    env.webview.on_start = user_closes
    assert env.run() == 0
    server = env.servers[0]
    assert server.ran.is_set() and server.should_exit
    assert not _server_thread(env).is_alive()
    assert env.window.dialogs == []
    assert env.boxes == []


@pytest.mark.parametrize("answer", [False, True])
def test_closing_during_a_job_asks_first(env: Env, answer: bool) -> None:
    env.jobs = [
        {"id": "a", "status": "done"},
        {"id": "b", "status": "running"},
    ]
    env.window.dialog_answer = answer
    closed: list[bool] = []
    env.webview.on_start = lambda webview: closed.append(webview.window.close())

    assert env.run() == 0
    assert closed == [answer]
    assert [title for title, _ in env.window.dialogs] == ["Quit MCRAR?"]
    assert "import is still running" in env.window.dialogs[0][1]
    assert env.servers[0].should_exit  # the app stops either way once start() returns


def test_finished_jobs_do_not_stop_the_close(env: Env) -> None:
    env.jobs = [{"id": "a", "status": "done"}, {"id": "b", "status": "cancelled"}]
    env.webview.on_start = lambda webview: webview.window.close()
    env.run()
    assert env.window.dialogs == []


def test_an_unreachable_server_does_not_block_closing(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    handler_result: list[Any] = []

    def user_closes(webview: FakeWebview) -> None:
        monkeypatch.setattr(httpx, "get", _raising_get)
        handler_result.append(webview.window.events.closing.handlers[0]())

    env.webview.on_start = user_closes
    env.run()
    assert handler_result == [True] and env.window.dialogs == []


def _raising_get(url: str, **kwargs: Any) -> httpx.Response:
    raise httpx.ConnectError("down", request=httpx.Request("GET", url))


def test_an_already_running_mcrar_gets_a_window_and_no_second_server(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_probe_server", lambda host, port: "mcrar")
    env.jobs = [{"id": "b", "status": "running"}]
    closed: list[bool] = []
    env.webview.on_start = lambda webview: closed.append(webview.window.close())

    assert env.run() == 0
    assert env.servers == []
    assert env.window.loaded_urls == [URL]
    assert closed == [True]
    assert env.window.dialogs == []
    assert URL + "api/jobs" not in env.requested
    assert env.webview.start_kwargs["args"][2] is None  # no server thread of ours


def test_a_port_held_by_another_program_gets_another_port(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_probe_server", lambda host, port: "other")
    monkeypatch.setattr(desktop, "_free_port", lambda: 45678)

    assert env.run() == 0
    assert [s.port for s in env.servers] == [45678]
    assert env.window.loaded_urls == ["http://127.0.0.1:45678/"]
    assert desktop.os.environ["MCRAR_API_PORT"] == "45678"
    log_text = (get_settings().home / "logs" / "mcrar.log").read_text(encoding="utf-8")
    assert "port 8123 is in use by another program; using port 45678" in log_text


def test_a_free_port_is_a_real_loopback_port() -> None:
    port = desktop._free_port()
    assert 0 < port < 65536


def test_the_error_page_shows_when_the_server_dies_while_starting(env: Env) -> None:
    env.server_blocks = False  # run() returns at once: the thread is gone
    env.health_down = True
    assert env.run() == 0
    assert env.window.loaded_urls == []
    page = env.window.loaded_html[0]
    assert "MCRAR could not start" in page
    assert str(get_settings().home / "logs" / "mcrar.log") in page.replace("&amp;", "&")


def test_the_error_page_shows_when_the_server_never_answers(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(desktop, "STARTUP_TIMEOUT_S", 0.05)
    env.health_down = True
    assert env.run() == 0
    assert env.window.loaded_urls == []
    assert "did not answer in time" in env.window.loaded_html[0]


def test_the_error_page_escapes_its_text() -> None:
    page = desktop.error_html("<b>x</b>", Path("C:/a&b/mcrar.log"))
    assert "<b>x</b>" not in page and "&lt;b&gt;" in page
    assert "a&amp;b" in page


def test_a_favicon_ico_becomes_the_window_icon(tmp_path: Path) -> None:
    assert desktop._icon_path(tmp_path) is None
    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "favicon.ico").write_bytes(b"not an icon")
    assert desktop._icon_path(tmp_path) is None  # winforms would crash on it
    (dist / "favicon.ico").write_bytes(b"\x00\x00\x01\x00" + b"\x00" * 20)
    assert desktop._icon_path(tmp_path) == str(dist / "favicon.ico")


# -- the browser fallback ---------------------------------------------------------------------


def _no_webview2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_webview2_version", lambda: None)


def _no_webview_package(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "webview", None)  # `import webview` raises ImportError


def _forced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(desktop.FORCE_BROWSER_ENV, "1")


@pytest.mark.parametrize(
    ("cause", "wording"),
    [
        (_no_webview2, "no Microsoft Edge WebView2 runtime"),
        (_no_webview_package, "could not be loaded"),
        (_forced, "MCRAR_DESKTOP_FORCE_BROWSER"),
    ],
)
def test_without_a_window_mcrar_opens_in_the_browser(
    env: Env, monkeypatch: pytest.MonkeyPatch, cause: Any, wording: str
) -> None:
    cause(monkeypatch)
    assert env.run() == 0

    assert env.webview.start_kwargs == {}  # no window
    assert env.webview.window_args == {}
    text, error = env.boxes[0]
    assert text.startswith("MCRAR opens in your browser instead:") and wording in text
    assert error is False
    assert "Click OK to quit" in text  # the open message box is the way to stop MCRAR
    assert env.opened_in_browser == [URL]
    server = env.servers[0]
    assert server.ran.is_set() and server.should_exit  # stopped when the box was closed


def test_the_browser_fallback_on_a_console_runs_in_the_foreground(
    env: Env, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _no_webview2(monkeypatch)
    env.server_blocks = False
    assert env.run(console_log=True) == 0
    assert env.boxes == []
    assert "opens in your browser instead" in capsys.readouterr().err
    assert env.opened_in_browser == [URL]
    assert env.servers[0].ran.is_set()
    assert env.servers[0].to_file is False  # uvicorn's own console logging


def test_the_browser_fallback_for_a_running_mcrar_starts_nothing(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_webview2(monkeypatch)
    monkeypatch.setattr(cli, "_probe_server", lambda host, port: "mcrar")
    assert env.run() == 0
    assert env.servers == []
    assert env.opened_in_browser == [URL]
    assert "opens in your browser instead" in env.boxes[0][0]


# -- logging without a console ----------------------------------------------------------------


def test_without_a_console_output_goes_to_the_log_file(
    env: Env, monkeypatch: pytest.MonkeyPatch, isolated_env: Path
) -> None:
    monkeypatch.setattr(sys, "stdout", None)  # pythonw.exe
    monkeypatch.setattr(sys, "stderr", None)

    def server_talks(webview: FakeWebview) -> None:
        print("hello from stdout")
        print("hello from stderr", file=sys.stderr)
        desktop.log.warning("a log record")

    env.webview.on_start = server_talks
    assert env.run(console_log=True) == 0  # --console-log cannot help without a console

    assert sys.stdout is None and sys.stderr is None  # put back
    text = (isolated_env / "logs" / "mcrar.log").read_text(encoding="utf-8")
    assert "hello from stdout\n" in text
    assert "hello from stderr\n" in text
    assert "WARNING mcrar.desktop: a log record" in text
    assert "desktop starting" in text
    assert [s.to_file for s in env.servers] == [True]


def test_with_console_log_and_a_console_the_output_stays_on_the_console(
    env: Env, isolated_env: Path
) -> None:
    stdout = sys.stdout
    assert env.run(console_log=True) == 0
    assert sys.stdout is stdout
    assert not (isolated_env / "logs").exists()
    assert [s.to_file for s in env.servers] == [False]


def test_the_log_rotates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(desktop, "LOG_MAX_BYTES", 300)
    monkeypatch.setattr(desktop, "LOG_BACKUPS", 2)
    path = tmp_path / "logs" / "mcrar.log"
    restore = desktop._redirect_output(path)
    try:
        for i in range(60):
            print(f"line {i:03d} " + "x" * 20)
    finally:
        restore()
    assert path.is_file() and path.with_name("mcrar.log.1").is_file()
    assert path.with_name("mcrar.log.2").is_file()
    assert not path.with_name("mcrar.log.3").exists()
    assert "line 059" in path.read_text(encoding="utf-8")


def test_a_log_stream_keeps_partial_lines_until_the_newline(tmp_path: Path) -> None:
    path = tmp_path / "mcrar.log"
    restore = desktop._redirect_output(path)
    try:
        sys.stdout.write("half ")
        sys.stdout.write("a line\r\nnext")
        assert path.read_text(encoding="utf-8") == "half a line\n"
        sys.stdout.flush()
    finally:
        restore()
    assert path.read_text(encoding="utf-8") == "half a line\nnext\n"


# -- startup errors ---------------------------------------------------------------------------


def test_a_startup_error_shows_a_message_box_with_the_log_path(
    env: Env, monkeypatch: pytest.MonkeyPatch, isolated_env: Path
) -> None:
    def broken(port: int, to_file: bool) -> FakeServer:
        raise RuntimeError("boom")

    monkeypatch.setattr(desktop, "_make_server", broken)
    assert env.run() == 1
    text, error = env.boxes[0]
    log_path = isolated_env / "logs" / "mcrar.log"
    assert "boom" in text and str(log_path) in text and error is True
    assert "Traceback" in log_path.read_text(encoding="utf-8")
    assert env.webview.start_kwargs == {}


def test_a_startup_error_on_a_console_is_printed_not_boxed(
    env: Env, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(port: int, to_file: bool) -> FakeServer:
        raise RuntimeError("boom")

    monkeypatch.setattr(desktop, "_make_server", broken)
    assert env.run(console_log=True) == 1
    assert env.boxes == []
    assert "error: boom" in capsys.readouterr().err


def test_a_failing_window_still_stops_the_server(env: Env) -> None:
    def explode(webview: FakeWebview) -> None:
        raise RuntimeError("window broke")

    env.webview.on_start = explode
    assert env.run() == 1
    assert env.servers[0].should_exit
    assert "window broke" in env.boxes[0][0]


def test_a_log_file_that_cannot_be_created_is_a_startup_error(env: Env, isolated_env: Path) -> None:
    (isolated_env / "logs").write_text("a file where the folder should be")
    assert env.run() == 1
    assert "MCRAR could not start" in env.boxes[0][0]
    assert env.servers == []


# -- DesktopApi -------------------------------------------------------------------------------


def _api(env: Env, result: Any) -> desktop.DesktopApi:
    env.window.file_dialog_result = result
    api = desktop.DesktopApi()
    api._attach(env.window)
    return api


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (("D:\\Music",), "D:\\Music"),
        (["D:\\Music", "E:\\More"], "D:\\Music"),
        ("D:\\Music", "D:\\Music"),
        (None, None),
        ((), None),
        ([], None),
    ],
)
def test_pick_folder_returns_the_first_entry_or_none(
    env: Env, result: Any, expected: str | None
) -> None:
    assert _api(env, result).pick_folder() == expected


def test_pick_folder_opens_the_folder_dialog_at_the_start_folder(env: Env) -> None:
    api = _api(env, ("C:\\x",))
    api.pick_folder("C:\\Users\\me\\Music")
    api.pick_folder()
    assert env.window.file_dialogs == [
        (FakeWebview.FileDialog.FOLDER, "C:\\Users\\me\\Music"),
        (FakeWebview.FileDialog.FOLDER, ""),
    ]


def test_the_page_can_only_call_pick_folder() -> None:
    public = [name for name in dir(desktop.DesktopApi()) if not name.startswith("_")]
    assert public == ["pick_folder"]


# -- the command ------------------------------------------------------------------------------


def test_the_desktop_command_is_listed_with_its_options() -> None:
    result = runner.invoke(cli.app, ["desktop", "--help"])
    assert result.exit_code == 0, result.output
    for text in ("--port", "--warm", "--console-log", "own window"):
        assert text in result.output


def test_the_desktop_command_hands_its_options_to_the_window_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_run(settings: Any, **kwargs: Any) -> int:
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(desktop, "run_desktop", fake_run)
    assert runner.invoke(cli.app, ["desktop"]).exit_code == 0
    assert (
        runner.invoke(cli.app, ["desktop", "--port", "9001", "--warm", "--console-log"]).exit_code
        == 0
    )
    assert calls == [
        {"port": 8000, "warm": False, "console_log": False},
        {"port": 9001, "warm": True, "console_log": True},
    ]


def test_the_desktop_command_passes_on_a_failure_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(desktop, "run_desktop", lambda settings, **kwargs: 1)
    assert runner.invoke(cli.app, ["desktop"]).exit_code == 1


def test_a_broken_settings_file_is_boxed_when_there_is_no_console(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(**overrides: Any) -> Any:
        raise ConfigError("bad settings.toml")

    boxes: list[str] = []
    monkeypatch.setattr(cli, "get_settings", broken)
    monkeypatch.setattr(desktop, "_message_box", lambda text, *, error=True: boxes.append(text))
    assert runner.invoke(cli.app, ["desktop"]).exit_code == 2
    assert "bad settings.toml" in boxes[0]

    boxes.clear()  # with --console-log on a console the error is printed instead
    result = runner.invoke(cli.app, ["desktop", "--console-log"])
    assert result.exit_code == 2 and boxes == []
    assert "bad settings.toml" in result.output


# -- the real server object and imports -------------------------------------------------------


def test_the_real_server_listens_on_loopback_only_and_uses_the_log_file() -> None:
    server = desktop._make_server(PORT, True)
    config = server.config
    assert (config.host, config.port, config.factory) == ("127.0.0.1", PORT, True)
    assert config.app == "mcrar.api.app:create_app"
    assert config.log_config is None  # logging goes to the root logger, which is the file


def test_importing_the_cli_and_the_desktop_module_does_not_load_pywebview() -> None:
    code = """
import sys
import mcrar.cli
import mcrar.desktop

gui = {"webview", "clr", "pythonnet"}
loaded = sorted(name for name in sys.modules if name.split(".")[0] in gui)
assert not loaded, loaded
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False, timeout=60
    )
    assert result.returncode == 0, result.stderr
