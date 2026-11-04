"""`mcrar desktop`: MCRAR in its own window (Windows, WebView2 through pywebview).

The API server runs in a background thread of this process, on 127.0.0.1 only, and the window
shows the web UI it serves. Closing the window stops the server; when a background job (an
import, an embedding run) is still going, the window asks first. When an MCRAR server already
answers on the port, no second one is started: the window opens on that one and closing it stops
nothing.

Without the WebView2 runtime, or when pywebview cannot be imported, MCRAR opens in the browser
instead, like ``mcrar serve --open``. ``MCRAR_DESKTOP_FORCE_BROWSER=1`` forces that fallback (for
tests and for trying it out on a PC that has the runtime).

Started without a console (``pythonw.exe``, as ``MCRAR.cmd`` does), stdout and stderr are
rewritten to ``<home>/logs/mcrar.log`` (rotated at about 1 MB, 3 old files kept), and startup
errors show in a Windows message box. pywebview keeps its browser data under ``<home>/.cache``:
nothing goes to the user profile.

Everything pywebview is imported inside functions: this module imports without it, so the CLI
and the tests do not need the ``desktop`` extra.
"""

from __future__ import annotations

import html
import io
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from mcrar import __version__, cli
from mcrar.config import Settings

HOST = "127.0.0.1"  # the window never needs more than loopback
FORCE_BROWSER_ENV = "MCRAR_DESKTOP_FORCE_BROWSER"
LOG_NAME = "mcrar.log"
LOG_MAX_BYTES = 1_000_000
LOG_BACKUPS = 3

STARTUP_TIMEOUT_S = 120.0  # how long the window waits for the server (first start is slow)
HEALTH_INTERVAL_S = 0.25
SHUTDOWN_TIMEOUT_S = 10.0  # for the server thread to stop after the window closed

QUIT_TITLE = "Quit MCRAR?"
QUIT_MESSAGE = (
    "An import is still running. Quitting stops it part-way.\n\n"
    "OK quits MCRAR, Cancel keeps it open."
)
WEBVIEW2_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"

log = logging.getLogger("mcrar.desktop")

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>MCRAR</title>
<meta name="color-scheme" content="light dark">
<style>
html,body{{height:100%;margin:0}}
body{{display:flex;align-items:center;justify-content:center;text-align:center;
font:16px/1.5 "Segoe UI",system-ui,sans-serif;background:#f5f6f8;color:#1a1d24}}
@media (prefers-color-scheme: dark){{body{{background:#101218;color:#e9ebf1}}}}
main{{max-width:34rem;padding:2rem}}
h1{{font-size:1.25rem;font-weight:600;margin:0 0 .5rem}}
p{{margin:.25rem 0;opacity:.8;overflow-wrap:anywhere}}
</style></head><body><main>{body}</main></body></html>"""

LOADING_HTML = _PAGE.format(body="<h1>Starting MCRAR...</h1><p>This takes a moment.</p>")


def error_html(message: str, log_path: Path | None) -> str:
    """The page shown in the window when the server does not come up."""
    where = (
        f"<p>Details are in the log file:<br>{html.escape(str(log_path))}</p>" if log_path else ""
    )
    body = f"<h1>MCRAR could not start</h1><p>{html.escape(message)}</p>{where}"
    return _PAGE.format(body=body)


# -- messages ---------------------------------------------------------------------------------


def _message_box(text: str, *, error: bool = True) -> None:
    """A native message box (the seam tests replace); other systems get stderr."""
    if sys.platform == "win32":
        import ctypes

        flags = 0x10 if error else 0x40  # MB_ICONERROR / MB_ICONINFORMATION
        ctypes.windll.user32.MessageBoxW(None, text, "MCRAR", flags)  # type: ignore[attr-defined]
    else:
        print(text, file=sys.stderr)


def uses_log_file(console_log: bool) -> bool:
    """Whether output goes to the log file: no console (``pythonw``), or no ``--console-log``."""
    return not console_log or sys.stdout is None or sys.stderr is None


def show_error(text: str) -> None:
    """Report a startup problem in a message box (used when there is no console to print to)."""
    _message_box(text, error=True)


def _notify(text: str, to_file: bool) -> None:
    if to_file:
        _message_box(text, error=False)
    else:
        cli._line(text, err=True)


# -- log file ---------------------------------------------------------------------------------


class _LogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if getattr(record, "raw", False):  # a line the program printed: no prefix
            return record.getMessage()
        return super().format(record)


class _LogStream(io.TextIOBase):
    """A ``sys.stdout`` / ``sys.stderr`` that sends complete lines to the log handler."""

    encoding = "utf-8"

    def __init__(self, handler: logging.Handler, name: str) -> None:
        self._handler = handler
        self._name = name
        self._pending = ""
        self._busy = threading.local()

    def writable(self) -> bool:
        return True

    def isatty(self) -> bool:
        return False

    def write(self, text: str) -> int:
        self._pending += text
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            self._emit(line.rstrip("\r"))
        return len(text)

    def flush(self) -> None:
        if self._pending:
            line, self._pending = self._pending, ""
            self._emit(line)

    def _emit(self, line: str) -> None:
        if getattr(self._busy, "active", False):  # the handler failing must not loop back here
            return
        self._busy.active = True
        try:
            record = logging.makeLogRecord({"msg": line, "name": self._name, "raw": True})
            self._handler.handle(record)
        finally:
            self._busy.active = False


def _redirect_output(log_path: Path) -> Callable[[], None]:
    """Send logging, stdout and stderr to ``log_path``; the returned function undoes it."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8"
    )
    handler.setFormatter(_LogFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    previous_level = root.level
    quiet = logging.getLogger("httpx")  # one INFO line per health poll would fill the log
    previous_quiet = quiet.level
    quiet.setLevel(logging.WARNING)
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    previous = sys.stdout, sys.stderr
    sys.stdout = _LogStream(handler, "stdout")  # type: ignore[assignment]
    sys.stderr = _LogStream(handler, "stderr")  # type: ignore[assignment]

    def restore() -> None:
        for stream in (sys.stdout, sys.stderr):
            if isinstance(stream, _LogStream):
                stream.flush()
        sys.stdout, sys.stderr = previous
        root.removeHandler(handler)
        root.setLevel(previous_level)
        quiet.setLevel(previous_quiet)
        handler.close()

    return restore


# -- server -----------------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def _choose_port(port: int) -> tuple[int, bool]:
    """``(port to use, whether this process starts the server)``."""
    taken = cli._probe_server(HOST, port)
    if taken == "mcrar":
        return port, False
    if taken == "free":
        return port, True
    chosen = _free_port()
    log.warning("port %s is in use by another program; using port %s instead", port, chosen)
    return chosen, True


def _make_server(port: int, to_file: bool) -> Any:
    """The uvicorn server (not started). Output goes to the root logger when it is the file."""
    import uvicorn
    from uvicorn.config import LOGGING_CONFIG

    config = uvicorn.Config(
        "mcrar.api.app:create_app",
        factory=True,
        host=HOST,
        port=port,
        log_config=None if to_file else LOGGING_CONFIG,
        timeout_graceful_shutdown=5,  # open event streams must not keep the quit waiting
    )
    return uvicorn.Server(config)


def _start_server(port: int, warm: bool, to_file: bool) -> tuple[Any, threading.Thread]:
    # The app factory runs inside uvicorn and reads its configuration from the environment.
    os.environ["MCRAR_API_HOST"] = HOST
    os.environ["MCRAR_API_PORT"] = str(port)
    if warm:
        os.environ["MCRAR_API_WARM"] = "1"
    server = _make_server(port, to_file)
    thread = threading.Thread(target=server.run, name="mcrar-server")
    thread.start()
    return server, thread


def _stop_server(server: Any, thread: threading.Thread) -> None:
    server.should_exit = True
    thread.join(timeout=SHUTDOWN_TIMEOUT_S)
    if thread.is_alive():
        server.force_exit = True
        thread.join(timeout=5.0)
    if thread.is_alive():
        log.warning("the server is still stopping (a job may be finishing); exit waits for it")


def _health_ok(url: str) -> bool:
    import httpx

    try:
        answer = httpx.get(url + "api/health", timeout=2.0, trust_env=False)
    except httpx.HTTPError:
        return False
    return cli._looks_like_mcrar(answer)


def _job_running(url: str) -> bool:
    """Whether the server at ``url`` has a running job; an unreachable server has none."""
    import httpx

    try:
        answer = httpx.get(url + "api/jobs", timeout=2.0, trust_env=False)
        jobs = answer.json()["jobs"]
        return any(job.get("status") == "running" for job in jobs)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        return False


# -- window -----------------------------------------------------------------------------------


class DesktopApi:
    """What the page can call as ``window.pywebview.api`` (pywebview exposes public names)."""

    def __init__(self) -> None:
        self._window: Any = None

    def _attach(self, window: Any) -> None:
        self._window = window

    def pick_folder(self, initial: str | None = None) -> str | None:
        """Ask for a folder with the native dialog; ``None`` when the dialog is cancelled."""
        import webview

        result = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=initial or "")
        if not result:
            return None
        if isinstance(result, str):
            return result
        return str(result[0])


def _background_color() -> str:
    """The app's background for the OS colour scheme, so the window does not flash."""
    light, dark = "#f5f6f8", "#101218"
    if sys.platform != "win32":
        return light
    try:
        import winreg

        key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            return light if winreg.QueryValueEx(handle, "AppsUseLightTheme")[0] else dark
    except OSError:
        return light


def _icon_path(home: Path) -> str | None:
    """The window icon when the frontend ships a real .ico; otherwise pywebview's default."""
    icon = home / "frontend" / "dist" / "favicon.ico"
    try:
        with icon.open("rb") as handle:
            return str(icon) if handle.read(4) == b"\x00\x00\x01\x00" else None
    except OSError:
        return None


def _closing_handler(window: Any, url: str, own_server: bool) -> Callable[[], bool]:
    """The window's ``closing`` handler: ask first when a job runs and closing stops it."""

    def on_closing() -> bool:
        if not own_server or not _job_running(url):
            return True
        return window.create_confirmation_dialog(QUIT_TITLE, QUIT_MESSAGE) is not False

    return on_closing


def _load_when_ready(
    window: Any, url: str, thread: threading.Thread | None, log_path: Path | None
) -> None:
    """Runs once the window is up: show the app when the server answers, else an error page."""
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while True:
        if _health_ok(url):
            window.load_url(url)
            return
        if thread is not None and not thread.is_alive():
            message = "The MCRAR server stopped while starting."
            break
        if time.monotonic() >= deadline:
            message = "The MCRAR server did not answer in time."
            break
        time.sleep(HEALTH_INTERVAL_S)
    log.error(message)
    window.load_html(error_html(message, log_path))


def _show_window(
    webview: Any,
    *,
    url: str,
    home: Path,
    own_server: bool,
    thread: threading.Thread | None,
    log_path: Path | None,
) -> None:
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    api = DesktopApi()
    window = webview.create_window(
        "MCRAR",
        html=LOADING_HTML,
        js_api=api,
        width=1280,
        height=820,
        min_size=(420, 560),
        background_color=_background_color(),
    )
    api._attach(window)
    window.events.closing += _closing_handler(window, url, own_server)
    webview.start(
        func=_load_when_ready,
        args=(window, url, thread, log_path),
        private_mode=False,  # keep the page's local storage (the first-run tour, preferences)
        storage_path=str(home / ".cache" / "webview"),  # inside the app folder, not the profile
        icon=_icon_path(home),
    )


# -- orchestration ----------------------------------------------------------------------------


def _load_webview() -> tuple[Any, str | None]:
    """``(the webview module, None)``, or ``(None, why MCRAR opens in the browser)``."""
    instead = "MCRAR opens in your browser instead: "
    if os.environ.get(FORCE_BROWSER_ENV) == "1":
        return None, f"{instead}{FORCE_BROWSER_ENV} is set."
    if cli._webview2_version() is None:
        return None, (
            f"{instead}this PC has no Microsoft Edge WebView2 runtime. "
            f"Install it from {WEBVIEW2_URL} to get MCRAR's own window."
        )
    try:
        import webview
    except Exception as exc:  # a missing package, or its .NET bridge failing to load
        log.exception("cannot import webview")
        return None, f"{instead}the window component could not be loaded ({exc})."
    return webview, None


def _run_in_browser(
    reason: str, *, url: str, port: int, warm: bool, own_server: bool, to_file: bool
) -> int:
    """The fallback: like ``mcrar serve --open``."""
    log.warning(reason)
    if not own_server:
        webbrowser.open(url)
        _notify(reason, to_file)
        return 0
    if not to_file:  # a console: run in the foreground, Ctrl+C stops it
        _notify(reason, to_file)
        _start_foreground(url, port, warm)
        return 0
    # No console to close: the message box that stays open is the way to quit.
    server, thread = _start_server(port, warm, to_file)
    try:
        cli._open_browser_when_ready(url)
        _message_box(
            f"{reason}\n\nMCRAR is running at {url}\n"
            "Leave this message open while you use MCRAR. Click OK to quit MCRAR.",
            error=False,
        )
    finally:
        _stop_server(server, thread)
    return 0


def _start_foreground(url: str, port: int, warm: bool) -> None:
    os.environ["MCRAR_API_HOST"] = HOST
    os.environ["MCRAR_API_PORT"] = str(port)
    if warm:
        os.environ["MCRAR_API_WARM"] = "1"
    cli._open_browser_when_ready(url)
    _make_server(port, to_file=False).run()


def _run(settings: Settings, port: int, warm: bool, to_file: bool, log_path: Path | None) -> int:
    port, own_server = _choose_port(port)
    url = cli._browser_url(HOST, port)
    webview, reason = _load_webview()
    if webview is None:
        return _run_in_browser(
            reason or "", url=url, port=port, warm=warm, own_server=own_server, to_file=to_file
        )
    server = thread = None
    if own_server:
        server, thread = _start_server(port, warm, to_file)
    else:
        log.info("MCRAR already runs at %s; the window opens there", url)
    try:
        _show_window(
            webview,
            url=url,
            home=settings.home,
            own_server=own_server,
            thread=thread,
            log_path=log_path,
        )
    finally:
        if server is not None and thread is not None:
            _stop_server(server, thread)
    return 0


def run_desktop(
    settings: Settings, *, port: int, warm: bool = False, console_log: bool = False
) -> int:
    """Run MCRAR in its own window until it is closed; returns the process exit code."""
    to_file = uses_log_file(console_log)
    log_path = settings.home / "logs" / LOG_NAME if to_file else None
    restore = None
    try:
        if log_path is not None:
            restore = _redirect_output(log_path)
        log.info("MCRAR %s desktop starting (home %s)", __version__, settings.home)
        return _run(settings, port, warm, to_file, log_path)
    except Exception as exc:
        log.exception("MCRAR desktop failed")
        if to_file:
            where = f"\n\nDetails are in the log file:\n{log_path}" if log_path else ""
            show_error(f"MCRAR could not start.\n\n{exc}{where}")
        else:
            cli._line(f"error: {exc}", err=True)
        return 1
    finally:
        if restore is not None:
            restore()
