"""`mcrar` command line: config, secrets, doctor, analyze."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Annotated

import typer

from mcrar import __version__
from mcrar.config import ConfigError, Settings, get_settings
from mcrar.secrets import SecretError, SecretStore, validate_name

app = typer.Typer(
    name="mcrar",
    help="MCRAR: ML music recommender for listeners and indie game devs.",
    no_args_is_help=True,
    add_completion=False,
)
config_app = typer.Typer(help="Inspect configuration.", no_args_is_help=True)
secrets_app = typer.Typer(help="Manage API keys and other secrets.", no_args_is_help=True)
app.add_typer(config_app, name="config")
app.add_typer(secrets_app, name="secrets")

# Variables that dev-env.ps1 / dev-env.sh point inside the repo (checked by `mcrar doctor`).
PROJECT_LOCAL_PATH_VARS = (
    "UV_INSTALL_DIR",
    "UV_PYTHON_INSTALL_DIR",
    "UV_PYTHON_BIN_DIR",
    "UV_CACHE_DIR",
    "UV_TOOL_DIR",
    "UV_TOOL_BIN_DIR",
    "npm_config_cache",
    "npm_config_prefix",
    "HF_HOME",
    "TORCH_HOME",
    "NUMBA_CACHE_DIR",
    "MPLCONFIGDIR",
    "XDG_CACHE_HOME",
)
_WEBVIEW2_CLIENT = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"mcrar {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Show version and exit."
    ),
) -> None:
    """MCRAR command line."""


def _fail(message: str, code: int = 2) -> typer.Exit:
    typer.echo(f"error: {message}", err=True)
    return typer.Exit(code)


def _settings() -> Settings:
    try:
        return get_settings()
    except ConfigError as exc:
        raise _fail(str(exc)) from None


def _store() -> SecretStore:
    try:
        return SecretStore(_settings())
    except SecretError as exc:
        raise _fail(str(exc)) from None


def _checked_name(name: str) -> str:
    try:
        return validate_name(name)
    except ValueError as exc:
        raise _fail(str(exc)) from None


@config_app.command("show")
def config_show() -> None:
    """Print the resolved settings as JSON (contains no secrets)."""
    typer.echo(json.dumps(_settings().model_dump(mode="json"), indent=2))


@secrets_app.command("set")
def secrets_set(
    name: str = typer.Argument(..., help="Secret name: lowercase letters, digits, underscores."),
    stdin: bool = typer.Option(False, "--stdin", help="Read the value from stdin."),
) -> None:
    """Store a secret. The value is prompted for (hidden) or read from stdin."""
    _checked_name(name)
    if stdin:
        value = sys.stdin.read().removesuffix("\n").removesuffix("\r")
    else:
        value = typer.prompt(f"Value for {name}", hide_input=True, confirmation_prompt=True)
    if not value:
        raise _fail("empty value; nothing stored")
    store = _store()
    try:
        store.set(name, value)
    except (SecretError, ValueError) as exc:
        raise _fail(str(exc), 1) from None
    typer.echo(f"stored '{name}' in the {store.backend_name} backend")
    if store.source(name) == "env":
        typer.echo("note: an environment variable currently overrides the stored value")


@secrets_app.command("list")
def secrets_list() -> None:
    """List secret names and where each comes from (never the values)."""
    store = _store()
    names = store.names()
    if not names:
        typer.echo("(no secrets)")
    for name in names:
        typer.echo(f"{name}\t{store.source(name)}")


@secrets_app.command("delete")
def secrets_delete(name: str = typer.Argument(...)) -> None:
    """Delete a secret from the configured backend."""
    _checked_name(name)
    store = _store()
    try:
        removed = store.delete(name)
    except SecretError as exc:
        raise _fail(str(exc), 1) from None
    if not removed:
        raise _fail(f"'{name}' is not stored in the {store.backend_name} backend", 1)
    typer.echo(f"deleted '{name}'")


def _inside(path: str | os.PathLike[str], root: str | os.PathLike[str]) -> bool:
    """Lexical containment check (symlinks are deliberately not followed)."""
    p = os.path.normcase(os.path.abspath(path))
    r = os.path.normcase(os.path.abspath(root))
    try:
        return os.path.commonpath([p, r]) == r
    except ValueError:  # e.g. different drives
        return False


def _webview2_version() -> str | None:
    """Read-only registry lookup of the WebView2 runtime version (Windows only)."""
    if sys.platform != "win32":
        return None
    import winreg

    clients = r"Microsoft\EdgeUpdate\Clients"
    locations = (
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\{clients}\{_WEBVIEW2_CLIENT}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\{clients}\{_WEBVIEW2_CLIENT}"),
        (winreg.HKEY_CURRENT_USER, rf"Software\{clients}\{_WEBVIEW2_CLIENT}"),
    )
    for hive, subkey in locations:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _ = winreg.QueryValueEx(key, "pv")
        except OSError:
            continue
        if value and value != "0.0.0.0":
            return str(value)
    return None


@app.command()
def doctor() -> None:
    """Check that the toolchain is project-local, and look for system prerequisites."""
    home = _settings().home
    failures = 0

    def report(status: str, message: str) -> None:
        typer.echo(f"[{status:>4}] {message}")

    typer.echo(f"MCRAR home: {home}")
    if os.environ.get("MCRAR_HOME"):
        report("ok", "MCRAR_HOME is set")
    else:
        failures += 1
        report("FAIL", "MCRAR_HOME is not set (dev env not loaded; home was inferred)")

    exe_ok = _inside(sys.executable, home)
    base_ok = _inside(sys.base_prefix, home)
    if exe_ok and base_ok:
        report("ok", f"Python is project-local: {sys.executable} (base: {sys.base_prefix})")
    else:
        failures += 1
        if not exe_ok:
            report("FAIL", f"Python executable is outside MCRAR_HOME: {sys.executable}")
        if not base_ok:
            report("FAIL", f"Base interpreter is outside MCRAR_HOME: {sys.base_prefix}")

    for var in PROJECT_LOCAL_PATH_VARS:
        value = os.environ.get(var)
        if not value:
            failures += 1
            report("FAIL", f"{var} is not set")
        elif not _inside(value, home):
            failures += 1
            report("FAIL", f"{var} points outside MCRAR_HOME: {value}")
        else:
            report("ok", f"{var} = {value}")

    if os.environ.get("PYTHONNOUSERSITE") == "1":
        report("ok", "PYTHONNOUSERSITE=1")
    else:
        failures += 1
        report("FAIL", "PYTHONNOUSERSITE is not 1 (user site-packages could leak in)")

    # Informational system checks: read-only, never fatal.
    if shutil.which("nvidia-smi"):
        report("ok", "NVIDIA driver found (nvidia-smi on PATH)")
    else:
        report("warn", "nvidia-smi not found: no NVIDIA driver detected; GPU features will use CPU")

    if sys.platform == "win32":
        webview = _webview2_version()
        if webview:
            report("ok", f"WebView2 runtime found (version {webview})")
        else:
            report("warn", "WebView2 runtime not found; the desktop app (M11) will need it")
    else:
        report("info", "WebView2 check skipped (not Windows)")

    if failures:
        typer.echo(
            f"\n{failures} problem(s): the toolchain is not project-local. "
            "Run through scripts/with-env.sh, or dot-source scripts/dev-env.ps1.",
            err=True,
        )
        raise typer.Exit(1)
    typer.echo("\nToolchain is project-local.")


def _fmt(value: object, spec: str = "", unit: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{value:{spec}}{unit}"


@app.command()
def analyze(
    path: Annotated[Path, typer.Argument(help="Audio file (WAV, FLAC, OGG, MP3).")],
    as_json: bool = typer.Option(False, "--json", help="Print JSON instead of a table."),
    max_seconds: float = typer.Option(
        240.0, "--max-seconds", min=0.1, help="Analyse only the first N seconds."
    ),
) -> None:
    """Extract DSP features (BPM, key, loudness, energy) from an audio file."""
    from mcrar.audio import AudioError, analyze_audio  # lazy: librosa/numba import is slow

    if not path.is_file():
        raise _fail(f"file not found: {path}", 1)
    try:
        features = analyze_audio(path, max_seconds=max_seconds)
    except AudioError as exc:
        raise _fail(str(exc), 1) from None
    except Exception as exc:  # never show a traceback for a bad input file
        raise _fail(f"analysis failed ({type(exc).__name__})", 1) from None
    if as_json:
        typer.echo(json.dumps(features.to_dict(), indent=2))
        return
    rows = [
        ("BPM", _fmt(features.bpm, ".1f")),
        ("BPM (raw)", _fmt(features.bpm_raw, ".1f")),
        ("BPM confidence", _fmt(features.bpm_confidence, ".2f")),
        ("Key", f"{features.key} {features.mode}" if features.key else "n/a"),
        ("Key confidence", _fmt(features.key_confidence, ".2f")),
        ("Loudness", _fmt(features.loudness_lufs, ".1f", " LUFS")),
        ("RMS", _fmt(features.rms_db, ".1f", " dBFS")),
        ("Energy", _fmt(features.energy, ".2f")),
        ("Duration", _fmt(features.duration_s, ".1f", " s")),
        ("Sample rate", f"{features.sample_rate} Hz"),
        ("Channels", str(features.channels)),
        ("Analysis version", features.analysis_version),
    ]
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        typer.echo(f"{label:<{width}}  {value}")
