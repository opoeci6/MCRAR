"""`mcrar` command line: config, secrets, doctor, analyze, ingest, catalog."""

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


# -- ingest and catalog ----------------------------------------------------------------------

ingest_app = typer.Typer(help="Add tracks to the catalog.", no_args_is_help=True)
catalog_app = typer.Typer(help="Inspect the catalog.", no_args_is_help=True)
app.add_typer(ingest_app, name="ingest")
app.add_typer(catalog_app, name="catalog")

EXIT_INTERRUPTED = 130
MAX_FAILURES_SHOWN = 20


def _line(text: str = "", *, err: bool = False) -> None:
    """Echo text that may hold arbitrary titles without ever failing on a narrow console."""
    stream = sys.stderr if err else sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    typer.echo(text.encode(encoding, "replace").decode(encoding), err=err)


def _jamendo_client(settings: Settings, use_cache: bool):  # noqa: ANN202 - lazy import
    """Build the Jamendo client (a seam for tests)."""
    from mcrar.sources import JamendoClient

    return JamendoClient.from_settings(settings, use_cache=use_cache)


def _print_progress(event) -> None:  # noqa: ANN001 - IngestEvent, imported lazily
    if event.kind not in ("track_done", "track_skipped", "track_failed"):
        return
    total = event.total if event.total is not None else "?"
    prefix = f"[{event.index}/{total}]"
    if event.kind == "track_done":
        _line(f"{prefix} ok  {event.title} — {event.message}")
    elif event.kind == "track_skipped":
        _line(f"{prefix} skip  {event.title} — {event.message}")
    else:
        _line(f"{prefix} failed: {event.title} — {event.message}")


def _print_summary(report) -> None:  # noqa: ANN001 - IngestReport, imported lazily
    state = f" ({report.aborted})" if report.aborted else ""
    _line(
        f"\nFinished{state} in {report.elapsed_s:.1f}s: {report.seen} seen "
        f"({report.new} new, {report.updated} updated), {report.processed} processed, "
        f"{report.skipped} skipped, {report.failed} failed"
    )
    for failure in report.failures[:MAX_FAILURES_SHOWN]:
        where = f"{failure.title} ({failure.source_id})"
        _line(f"  failed [{failure.stage}] {where}: {failure.message}")
    hidden = len(report.failures) - MAX_FAILURES_SHOWN
    if hidden > 0:
        _line(f"  ... and {hidden} more; see: mcrar catalog failures")


def _ingest_exit(report) -> None:  # noqa: ANN001
    if report.aborted == "interrupted":
        _line("Interrupted; run the same command again to resume.", err=True)
        raise typer.Exit(EXIT_INTERRUPTED)


@ingest_app.command("jamendo")
def ingest_jamendo_cmd(
    tags: Annotated[str | None, typer.Option(help="Comma-separated tags; all must match.")] = None,
    fuzzytags: Annotated[
        str | None, typer.Option(help="Comma-separated tags; any may match.")
    ] = None,
    search: Annotated[str | None, typer.Option(help="Free-text search.")] = None,
    vocal: Annotated[bool, typer.Option("--vocal", help="Only vocal tracks.")] = False,
    instrumental: Annotated[
        bool, typer.Option("--instrumental", help="Only instrumental tracks.")
    ] = False,
    commercial_only: Annotated[
        bool, typer.Option("--commercial-only", help="Only licences allowing commercial use.")
    ] = False,
    order: Annotated[str | None, typer.Option(help="Jamendo order, e.g. popularity_month.")] = None,
    limit: Annotated[int, typer.Option(min=1, help="Maximum number of tracks.")] = 100,
    force: Annotated[bool, typer.Option("--force", help="Re-analyse up-to-date tracks.")] = False,
    no_cache: Annotated[
        bool, typer.Option("--no-cache", help="Bypass the Jamendo response cache.")
    ] = False,
) -> None:
    """Fetch tracks from Jamendo, store their metadata and licences, and analyse the audio."""
    from contextlib import closing

    from mcrar.catalog import open_catalog
    from mcrar.ingest import JamendoQuery, ingest_jamendo
    from mcrar.sources import JamendoError

    if vocal and instrumental:
        raise _fail("--vocal and --instrumental are mutually exclusive")

    def split(value: str | None) -> list[str] | None:
        return [t.strip() for t in value.split(",") if t.strip()] if value else None

    query = JamendoQuery(
        tags=split(tags),
        fuzzytags=split(fuzzytags),
        search=search,
        vocalinstrumental="vocal" if vocal else "instrumental" if instrumental else None,
        commercial_only=commercial_only,
        order=order,
    )
    settings = _settings()
    try:
        client = _jamendo_client(settings, not no_cache)
    except (JamendoError, SecretError) as exc:
        raise _fail(str(exc), 1) from None
    with closing(client), open_catalog(settings) as repo:
        problem: str | None = None
        try:
            report = ingest_jamendo(
                client, repo, query=query, limit=limit, force=force, on_progress=_print_progress
            )
        except JamendoError as exc:
            report, problem = getattr(exc, "report", None), str(exc)
        except Exception as exc:  # never show a traceback
            report, problem = getattr(exc, "report", None), f"ingest failed ({type(exc).__name__})"
        if report is not None:
            _print_summary(report)
        usage = client.usage()
        _line(f"Jamendo API requests in {usage['month']}: {usage['requests']}")
    if problem is not None:
        raise _fail(problem, 1)
    _ingest_exit(report)


@ingest_app.command("local")
def ingest_local_cmd(
    path: Annotated[Path, typer.Argument(help="Folder of audio files (searched recursively).")],
    license: Annotated[  # noqa: A002
        str | None,
        typer.Option("--license", help="Licence code or URL for every file, e.g. CC0."),
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Re-analyse up-to-date tracks.")] = False,
) -> None:
    """Add a folder of audio files; licences come from mcrar-license.toml sidecar files."""
    from mcrar.catalog import open_catalog
    from mcrar.ingest import ingest_local

    if not path.is_dir():
        raise _fail(f"folder not found: {path}", 1)
    settings = _settings()
    with open_catalog(settings) as repo:
        try:
            report = ingest_local(
                path, repo, license_override=license, force=force, on_progress=_print_progress
            )
        except ValueError as exc:  # an unrecognised --license, raised before any work
            raise _fail(str(exc), 2) from None
        except Exception as exc:  # never show a traceback
            partial = getattr(exc, "report", None)
            if partial is not None:
                _print_summary(partial)
            raise _fail(f"ingest failed ({type(exc).__name__})", 1) from None
        _print_summary(report)
    _ingest_exit(report)


def _open_repo():  # noqa: ANN202
    from mcrar.catalog import open_catalog

    return open_catalog(_settings())


@catalog_app.command("stats")
def catalog_stats(as_json: bool = typer.Option(False, "--json", help="Print JSON.")) -> None:
    """Counts of tracks, features, embeddings and ingest failures."""
    with _open_repo() as repo:
        stats = repo.stats()
    if as_json:
        typer.echo(json.dumps(stats, indent=2))
        return

    def pairs(mapping: dict[str, int]) -> str:
        return ", ".join(f"{k}={v}" for k, v in sorted(mapping.items())) or "none"

    features = stats["features"]
    _line(f"Tracks:           {stats['tracks']}")
    _line(f"  by source:      {pairs(stats['tracks_by_source'])}")
    _line(f"  by risk:        {pairs(stats['tracks_by_risk'])}")
    _line(
        f"With features:    {features['tracks_with_features']} ({features['coverage'] * 100:.0f}%)"
    )
    _line(f"Embeddings:       {pairs(stats['embeddings_by_model'])}")
    _line(f"Ingest failures:  {pairs(stats['ingest_failures_by_stage'])}")


def _yes_no(value: bool | None) -> str:
    return "n/a" if value is None else "yes" if value else "no"


@catalog_app.command("show")
def catalog_show(
    track_id: Annotated[int, typer.Argument(metavar="ID", help="Catalog track id.")],
    as_json: bool = typer.Option(False, "--json", help="Print JSON."),
) -> None:
    """Show a track with its licence, features and ingest status."""
    from dataclasses import asdict

    with _open_repo() as repo:
        track = repo.get_track(track_id)
        if track is None:
            raise _fail(f"no track with id {track_id}", 1)
        features = repo.get_features(track_id)
        ingest = repo.ingest_entries(track.source, track.source_id)
    if as_json:
        data = {
            "track": asdict(track),
            "features": features,
            "ingest": [asdict(e) for e in ingest],
        }
        typer.echo(json.dumps(data, indent=2, ensure_ascii=False))
        return
    _line(f"Track {track.id} ({track.source} {track.source_id})")
    for label, value in (
        ("Title", track.title),
        ("Artist", track.artist),
        ("Album", track.album),
        ("Duration", None if track.duration_s is None else f"{track.duration_s:.1f} s"),
        ("Page", track.source_url),
        ("File", track.local_path),
    ):
        if value is not None:
            _line(f"  {label + ':':<10}{value}")
    _line("License")
    _line(f"  Code:        {track.license_code or 'n/a'}  ({track.license_family or 'n/a'})")
    _line(f"  Risk:        {track.risk}")
    _line(f"  Commercial:  {_yes_no(track.commercial_ok)}")
    _line(f"  Derivatives: {_yes_no(track.derivatives_ok)}")
    _line(f"  Share-alike: {_yes_no(track.share_alike)}")
    _line(f"  Attribution: {_yes_no(track.attribution_required)}")
    if track.license_url:
        _line(f"  URL:         {track.license_url}")
    if track.commercial_license_url:
        _line(f"  Commercial license: {track.commercial_license_url}")
    if track.attribution_text:
        _line(f"  Credit:      {track.attribution_text}")
    _line("Features")
    if features is None:
        _line("  (not analysed)")
    else:
        key = f"{features['key']} {features['mode']}" if features["key"] else "n/a"
        _line(f"  BPM:         {_fmt(features['bpm'], '.1f')}")
        _line(f"  Key:         {key}")
        _line(f"  Loudness:    {_fmt(features['loudness_lufs'], '.1f', ' LUFS')}")
        _line(f"  Energy:      {_fmt(features['energy'], '.2f')}")
        _line(f"  Version:     {features['analysis_version']}")
    _line("Ingest")
    if not ingest:
        _line("  (no entries)")
    for entry in ingest:
        extra = f" - {entry.message}" if entry.message else ""
        _line(f"  {entry.stage}: {entry.status} (attempts {entry.attempts}){extra}")


@catalog_app.command("failures")
def catalog_failures(
    stage: Annotated[str | None, typer.Option(help="Only this stage, e.g. analysis.")] = None,
    as_json: bool = typer.Option(False, "--json", help="Print JSON."),
) -> None:
    """List tracks whose last ingest attempt failed."""
    from dataclasses import asdict

    with _open_repo() as repo:
        entries = repo.failed_items(stage)
    if as_json:
        typer.echo(json.dumps([asdict(e) for e in entries], indent=2, ensure_ascii=False))
        return
    if not entries:
        typer.echo("(no failures)")
    for entry in entries:
        _line(
            f"{entry.stage}\t{entry.source}/{entry.source_id}\tattempts={entry.attempts}"
            f"\t{entry.message or ''}"
        )
