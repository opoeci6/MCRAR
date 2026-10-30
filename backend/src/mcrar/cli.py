"""`mcrar` command line: config, secrets, doctor, analyze, ingest, catalog, embed, search, llm and
the scene tagger."""

from __future__ import annotations

import json
import os
import shutil
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import typer

from mcrar import __version__
from mcrar.config import ConfigError, Settings, get_settings
from mcrar.console import echo as _line
from mcrar.ml.datasets.cli import app as datasets_app
from mcrar.ml.tagging.cli import app as tagging_app
from mcrar.ml.tagging.cli import tag
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
app.add_typer(datasets_app, name="datasets")
app.add_typer(tagging_app, name="tagging")
app.command("tag")(tag)

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
    "PYTORCH_KERNEL_CACHE_PATH",
    "TORCHINDUCTOR_CACHE_DIR",
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


def _jamendo_client(settings: Settings, use_cache: bool):  # noqa: ANN202 - lazy import
    """Build the Jamendo client (a seam for tests)."""
    from mcrar.sources import JamendoClient

    return JamendoClient.from_settings(settings, use_cache=use_cache)


def _freesound_client(settings: Settings, use_cache: bool):  # noqa: ANN202 - lazy import
    """Build the Freesound client (a seam for tests)."""
    from mcrar.sources import FreesoundClient

    return FreesoundClient.from_settings(settings, use_cache=use_cache)


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
    embed: Annotated[
        str | None,
        typer.Option(
            "--embed",
            help="Embed with these models, e.g. clap,glap. Default: the default_embedder setting.",
        ),
    ] = None,
    no_embed: Annotated[
        bool, typer.Option("--no-embed", help="Analyse only; do not embed.")
    ] = False,
) -> None:
    """Fetch tracks from Jamendo, store their metadata and licences, analyse and embed the audio."""
    from contextlib import closing

    from mcrar.catalog import open_catalog
    from mcrar.ingest import JamendoQuery, ingest_jamendo
    from mcrar.ml import ModelError
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
    keys = _ingest_embed_keys(embed, no_embed, settings)
    try:
        client = _jamendo_client(settings, not no_cache)
    except (JamendoError, SecretError) as exc:
        raise _fail(str(exc), 1) from None
    with closing(client), open_catalog(settings) as repo:
        problem: str | None = None
        try:
            with _ingest_stages(keys, settings) as stages:
                report = ingest_jamendo(
                    client,
                    repo,
                    query=query,
                    limit=limit,
                    force=force,
                    stages=stages,
                    on_progress=_print_progress,
                )
        except (JamendoError, ModelError) as exc:
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


@ingest_app.command("freesound")
def ingest_freesound_cmd(
    query: Annotated[str, typer.Option(help="Free-text search.")] = "",
    tags: Annotated[
        list[str] | None,
        typer.Option("--tag", help="A tag every sound must have; repeat for several."),
    ] = None,
    licenses: Annotated[
        list[str] | None,
        typer.Option(
            "--license",
            help="Licence to accept: cc0, by, by-nc or sampling+; repeat for several. "
            "Default: cc0 and by.",
        ),
    ] = None,
    min_duration: Annotated[float, typer.Option(min=0, help="Shortest sound in seconds.")] = 10.0,
    max_duration: Annotated[float, typer.Option(min=0, help="Longest sound in seconds.")] = 600.0,
    sort: Annotated[str, typer.Option(help="Freesound sort, e.g. score or downloads_desc.")] = (
        "score"
    ),
    limit: Annotated[int, typer.Option(min=1, help="Maximum number of sounds.")] = 50,
    force: Annotated[bool, typer.Option("--force", help="Re-analyse up-to-date tracks.")] = False,
    no_cache: Annotated[
        bool, typer.Option("--no-cache", help="Bypass the Freesound response cache.")
    ] = False,
    embed: Annotated[
        str | None,
        typer.Option(
            "--embed",
            help="Embed with these models, e.g. clap,glap. Default: the default_embedder setting.",
        ),
    ] = None,
    no_embed: Annotated[
        bool, typer.Option("--no-embed", help="Analyse only; do not embed.")
    ] = False,
) -> None:
    """Fetch music-like sounds from Freesound (music, loops, ambience; 10 s or longer by default),
    store their metadata and licences, analyse and embed the mp3 preview."""
    from contextlib import closing

    from mcrar.catalog import open_catalog
    from mcrar.ingest import ingest_freesound
    from mcrar.ml import ModelError
    from mcrar.sources import FreesoundError
    from mcrar.sources.freesound import SORTS, build_filter

    tag_list = [t.strip() for t in tags or [] if t.strip()]
    licence_list = licenses or ["cc0", "by"]
    if not query.strip() and not tag_list:
        raise _fail("give --query or at least one --tag")
    try:  # bad tags, licences, sort or durations fail before anything is opened
        build_filter(
            tags=tag_list,
            licenses=licence_list,
            duration_min_s=min_duration,
            duration_max_s=max_duration,
        )
        if sort not in SORTS:
            raise ValueError(f"--sort must be one of: {', '.join(SORTS)}")
    except ValueError as exc:
        raise _fail(str(exc)) from None
    settings = _settings()
    keys = _ingest_embed_keys(embed, no_embed, settings)
    try:
        client = _freesound_client(settings, not no_cache)
    except (FreesoundError, SecretError) as exc:
        raise _fail(str(exc), 1) from None
    with closing(client), open_catalog(settings) as repo:
        problem: str | None = None
        try:
            with _ingest_stages(keys, settings) as stages:
                report = ingest_freesound(
                    client,
                    repo,
                    query=query,
                    tags=tag_list,
                    licenses=licence_list,
                    duration_min_s=min_duration,
                    duration_max_s=max_duration,
                    sort=sort,
                    limit=limit,
                    force=force,
                    stages=stages,
                    on_progress=_print_progress,
                )
        except (FreesoundError, ModelError) as exc:
            report, problem = getattr(exc, "report", None), str(exc)
        except Exception as exc:  # never show a traceback
            report, problem = getattr(exc, "report", None), f"ingest failed ({type(exc).__name__})"
        if report is not None:
            _print_summary(report)
        usage = client.usage()
        _line(f"Freesound API requests on {usage['day']}: {usage['requests']}")
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
    embed: Annotated[
        str | None,
        typer.Option(
            "--embed",
            help="Embed with these models, e.g. clap,glap. Default: the default_embedder setting.",
        ),
    ] = None,
    no_embed: Annotated[
        bool, typer.Option("--no-embed", help="Analyse only; do not embed.")
    ] = False,
) -> None:
    """Add a folder of audio files (licences from sidecar files); analyse and embed them."""
    from mcrar.catalog import open_catalog
    from mcrar.ingest import ingest_local
    from mcrar.ml import ModelError

    if not path.is_dir():
        raise _fail(f"folder not found: {path}", 1)
    settings = _settings()
    keys = _ingest_embed_keys(embed, no_embed, settings)
    with open_catalog(settings) as repo:
        try:
            with _ingest_stages(keys, settings) as stages:
                report = ingest_local(
                    path,
                    repo,
                    license_override=license,
                    force=force,
                    stages=stages,
                    on_progress=_print_progress,
                )
        except ValueError as exc:  # an unrecognised --license, raised before any work
            raise _fail(str(exc), 2) from None
        except ModelError as exc:
            raise _fail(str(exc), 1) from None
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


# -- embeddings and models -------------------------------------------------------------------

models_app = typer.Typer(help="Text-audio embedding models.", no_args_is_help=True)
app.add_typer(models_app, name="models")
SOURCES = ("jamendo", "freesound", "local")


def _load_embedder(
    key: str,
    settings: Settings,
    *,
    device: str = "auto",
    dtype: str = "auto",
    batch_size: int | None = None,
):  # noqa: ANN202
    """Load one embedder (a seam for tests). Imports torch, so only called when needed."""
    from mcrar.ml.embedders import load_embedder

    return load_embedder(key, settings=settings, device=device, dtype=dtype, batch_size=batch_size)


def _model_keys(value: str | None) -> list[str]:
    """Validate ``--models`` / ``--embed``: known keys. Without a value: every model."""
    from mcrar.ml import MODELS, ModelError, parse_model_keys

    if value is None:
        return list(MODELS)
    try:
        return parse_model_keys(value)
    except ModelError as exc:
        raise _fail(str(exc)) from None


@contextmanager
def _embedders(
    keys: list[str], settings: Settings, *, device: str = "auto", batch_size: int | None = None
) -> Iterator[list]:
    """Load the models once, tell what was chosen, and free them on exit.

    Raises ``ModelError`` (with a message fit for the user) if one cannot be loaded.
    """
    from mcrar.ml import ModelError

    loaded: list = []
    try:
        for key in keys:
            _line(f"Loading {key} ...")
            try:
                embedder = _load_embedder(key, settings, device=device, batch_size=batch_size)
            except ModelError:
                raise
            except Exception as exc:  # never show a traceback
                raise ModelError(f"could not load model '{key}' ({type(exc).__name__})") from None
            loaded.append(embedder)
            where = f"{getattr(embedder, 'device', '?')}, {getattr(embedder, 'dtype_note', '')}"
            took = getattr(embedder, "load_seconds", 0.0)
            _line(f"  {embedder.model_id}: {where}; loaded in {took:.1f}s")
        yield loaded
    finally:
        for embedder in loaded:
            close = getattr(embedder, "close", None)
            if close is not None:
                close()


def _torch_available() -> bool:
    """Whether the ``ml`` extra is installed (a seam for tests; does not import torch)."""
    import importlib.util

    return importlib.util.find_spec("torch") is not None


def _ingest_embed_keys(embed: str | None, no_embed: bool, settings: Settings) -> list[str]:
    """The models `ingest` embeds with: ``--embed``, else the default embedder, else none.

    Without the ``ml`` extra the default run warns and goes on with analysis only.
    """
    if embed and no_embed:
        raise _fail("--embed and --no-embed are mutually exclusive")
    if no_embed:
        return []
    if embed:
        return _model_keys(embed)
    if not _torch_available():
        _line(
            "warning: torch is not installed, so tracks are analysed but not embedded "
            "(install the ml extra: uv sync --extra ml)",
            err=True,
        )
        return []
    return _model_keys(settings.default_embedder)


def _tagging_stages(settings: Settings) -> list:
    """Tagging stages from M3b (tags from stored embeddings); none until that module exists."""
    from mcrar.ingest.stages import tagging_stages_for

    return tagging_stages_for(settings)


@contextmanager
def _ingest_stages(keys: list[str], settings: Settings) -> Iterator[list | None]:
    """The stages for `ingest`: analysis, one embedding stage per model, then tagging.

    Yields None (the pipeline's default, analysis only) when no models are asked for. Tagging
    reads the CLAP embedding, so its stages are added only when ``clap`` is among the models.
    """
    from mcrar.ingest.stages import build_stages

    if not keys:
        yield None
        return
    with _embedders(keys, settings) as embedders:
        yield build_stages(settings, embedders)


@app.command()
def embed(
    models: Annotated[
        str | None,
        typer.Option(
            help="Comma-separated models: clap, glap, muq-mulan. "
            "Default: the default_embedder setting (clap)."
        ),
    ] = None,
    source: Annotated[
        str | None, typer.Option(help="Only tracks of this source: jamendo, freesound or local.")
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Re-embed tracks that already have embeddings.")
    ] = False,
    limit: Annotated[
        int | None, typer.Option(min=1, help="Embed at most this many tracks.")
    ] = None,
    batch_size: Annotated[
        int | None,
        typer.Option(min=1, help="Audio windows per model forward pass (lower it to save VRAM)."),
    ] = None,
    device: Annotated[str, typer.Option(help="auto, cpu or cuda.")] = "auto",
) -> None:
    """Embed catalog tracks with text-audio models (loaded once, audio fetched once)."""

    from mcrar.catalog import open_catalog
    from mcrar.ingest import EmbeddingStage, reprocess_catalog
    from mcrar.ml import MODELS, ModelError
    from mcrar.sources import FreesoundError, JamendoError

    if source is not None and source not in SOURCES:
        raise _fail(f"--source must be one of: {', '.join(SOURCES)}")
    settings = _settings()
    keys = _model_keys(models or settings.default_embedder)
    with open_catalog(settings) as repo:
        model_ids = [MODELS[k].model_id for k in keys]
        todo = any(
            force or any(repo.get_embedding(t.id, m) is None for m in model_ids)
            for t in repo.iter_tracks(source)
        )
        if not todo:
            _line("Nothing to embed: every selected track already has these embeddings.")
            return
        client = freesound = None
        counts = repo.stats()["tracks_by_source"]
        if source in (None, "jamendo") and counts.get("jamendo", 0) > 0:
            try:
                client = _jamendo_client(settings, True)
            except (JamendoError, SecretError) as exc:
                raise _fail(f"{exc} (use --source local to skip Jamendo tracks)", 1) from None
        if source in (None, "freesound") and counts.get("freesound", 0) > 0:
            try:
                freesound = _freesound_client(settings, True)
            except (FreesoundError, SecretError) as exc:
                if source == "freesound":
                    raise _fail(str(exc), 1) from None
                # A whole-catalog run goes on: the Freesound tracks fail one by one.
                _line(f"warning: Freesound tracks will fail: {exc}", err=True)
        problem: str | None = None
        report = None
        try:
            with _embedders(keys, settings, device=device, batch_size=batch_size) as embedders:
                report = reprocess_catalog(
                    repo,
                    stages=[EmbeddingStage(e) for e in embedders],
                    client=client,
                    freesound_client=freesound,
                    source=source,
                    force=force,
                    limit=limit,
                    on_progress=_print_progress,
                )
        except (JamendoError, FreesoundError, ModelError) as exc:
            report, problem = getattr(exc, "report", None), str(exc)
        except Exception as exc:  # never show a traceback
            report, problem = getattr(exc, "report", None), f"embed failed ({type(exc).__name__})"
        finally:
            for opened in (client, freesound):
                if opened is not None:
                    opened.close()
        if report is not None:
            _print_summary(report)
    if problem is not None:
        raise _fail(problem, 1)
    if report is not None:
        _ingest_exit(report)


@models_app.command("list")
def models_list() -> None:
    """List the embedding models: licence and whether downloaded."""
    from mcrar.ml import MODELS
    from mcrar.ml.registry import is_downloaded

    settings = _settings()
    rows = [("KEY", "MODEL ID", "LICENSE", "COMMERCIAL", "DOWNLOADED")]
    for spec in MODELS.values():
        downloaded = is_downloaded(spec, settings)
        rows.append(
            (
                spec.key,
                spec.model_id,
                spec.license,
                _yes_no(spec.commercial_ok),
                "unknown (ML extra not installed)" if downloaded is None else _yes_no(downloaded),
            )
        )
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        _line("  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)).rstrip())


@models_app.command("benchmark")
def models_benchmark(
    models: Annotated[
        str | None,
        typer.Option(help="Comma-separated models. Default: every model."),
    ] = None,
    seconds: Annotated[
        float, typer.Option(min=1.0, help="Length of each synthetic test track.")
    ] = 60.0,
    device: Annotated[str, typer.Option(help="auto, cpu or cuda.")] = "auto",
    dtype: Annotated[str, typer.Option(help="auto, fp16 or fp32.")] = "auto",
    benchmark_json: Annotated[
        bool,
        typer.Option(
            "--benchmark-json",
            help="Also save the table as data/benchmarks/results/benchmark_<timestamp>.json "
            "(read by `mcrar bakeoff report`).",
        ),
    ] = False,
) -> None:
    """Load each model in turn and measure load time, VRAM and throughput on synthetic audio."""
    from dataclasses import asdict

    from mcrar.ml import ModelError
    from mcrar.ml.benchmark import benchmark_embedder

    settings = _settings()
    keys = _model_keys(models)

    def mb(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.0f}"

    header = (
        "model",
        "load s",
        "device",
        "dtype",
        "peak MB",
        "weights MB",
        "audio s/s",
        "text/s",
        "dim",
    )
    rows = [header]
    measured: list[dict] = []
    failed = 0
    for key in keys:
        _line(f"Benchmarking {key} ...")
        try:
            result = benchmark_embedder(
                lambda key=key: _load_embedder(key, settings, device=device, dtype=dtype),
                seconds=seconds,
            )
        except ModelError as exc:
            failed += 1
            _line(f"  failed: {exc}", err=True)
            continue
        except Exception as exc:  # never show a traceback
            failed += 1
            _line(f"  failed: {type(exc).__name__}: {str(exc)[:200]}", err=True)
            continue
        measured.append(asdict(result))
        rows.append(
            (
                result.model_id,
                f"{result.load_s:.1f}",
                result.device,
                result.dtype,
                mb(result.peak_vram_mb),
                mb(result.resident_vram_mb),
                f"{result.audio_s_per_s:.1f}",
                f"{result.texts_per_s:.1f}",
                str(result.dim),
            )
        )
    if len(rows) > 1:
        widths = [max(len(row[i]) for row in rows) for i in range(len(header))]
        _line("")
        for row in rows:
            _line(
                "  ".join(
                    cell.rjust(w) if i else cell.ljust(w)
                    for i, (cell, w) in enumerate(zip(row, widths, strict=True))
                )
            )
        _line(
            f"\naudio s/s: seconds of a {seconds:g} s track embedded per second (3 windows each)."
        )
    if benchmark_json and measured:
        from mcrar.ml.bakeoff.common import created_at, results_dir, timestamp, write_json

        path = write_json(
            results_dir(settings) / f"benchmark_{timestamp()}.json",
            {
                "kind": "benchmark",
                "created_at": created_at(),
                "seconds": seconds,
                "device": device,
                "dtype": dtype,
                "rows": measured,
                "failed_models": failed,
            },
        )
        _line(f"Saved {path}")
    if failed:
        raise _fail(f"{failed} model(s) failed", 1)


# -- embedder bake-off ---------------------------------------------------------------------------

bakeoff_app = typer.Typer(
    help="Embedder bake-off: Song Describer retrieval, genre tags, blind ratings, report.",
    no_args_is_help=True,
)
app.add_typer(bakeoff_app, name="bakeoff")

BAKEOFF_RESAMPLES = 1000
BAKEOFF_SEED = 0
SDD_PROGRESS_EVERY = 50

_MODELS_HELP = "Comma-separated models: clap, glap, muq-mulan. Default: every model."
_SDD_DIR_HELP = "Song Describer folder. Default: <data>/benchmarks/sdd."


@contextmanager
def _bakeoff_errors() -> Iterator[None]:
    """Turn bake-off and model errors into ``error: ...`` plus exit 1, never a traceback."""
    from mcrar.ml import ModelError
    from mcrar.ml.bakeoff import BakeoffError

    try:
        yield
    except typer.Exit:
        raise
    except (BakeoffError, ModelError) as exc:
        raise _fail(str(exc), 1) from None
    except KeyboardInterrupt:
        _line("Interrupted.", err=True)
        raise typer.Exit(EXIT_INTERRUPTED) from None
    except Exception as exc:
        raise _fail(f"bake-off failed ({type(exc).__name__}: {str(exc)[:200]})", 1) from None


def _print_rows(rows: list[tuple[str, ...]]) -> None:
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        _line(
            "  ".join(
                cell.rjust(w) if i else cell.ljust(w)
                for i, (cell, w) in enumerate(zip(row, widths, strict=True))
            )
        )


def _ci_text(ci: list[float]) -> str:
    return f"[{ci[0]:.3f}, {ci[1]:.3f}]"


def _print_pairwise(pairwise: list[dict]) -> None:
    if not pairwise:
        return
    _line("\nPaired bootstrap differences (first minus second; * = 95% CI excludes 0):")
    for p in pairwise:
        star = "*" if p["significant"] else " "
        _line(
            f"  {p['a']} - {p['b']}  {p['metric']:<12} {p['diff']:+.3f}  {_ci_text(p['ci'])} {star}"
        )


@bakeoff_app.command("sdd-embed")
def bakeoff_sdd_embed(
    models: Annotated[str | None, typer.Option(help=_MODELS_HELP)] = None,
    batch_size: Annotated[
        int | None,
        typer.Option(min=1, help="Audio windows per model forward pass (lower it to save VRAM)."),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Re-embed models that already have a saved result.")
    ] = False,
    device: Annotated[str, typer.Option(help="auto, cpu or cuda.")] = "auto",
    sdd_dir: Annotated[Path | None, typer.Option(help=_SDD_DIR_HELP)] = None,
) -> None:
    """Embed the Song Describer audio with each model and save embeddings/<model_id>.npz."""
    from mcrar.ml import MODELS
    from mcrar.ml.bakeoff import common, sdd

    settings = _settings()
    keys = _model_keys(models)
    root = sdd_dir or common.sdd_dir(settings)

    def progress(index: int, total: int, track_id: int, status: str, why: str | None) -> None:
        if status == "failed":
            _line(f"[{index}/{total}] failed: track {track_id} — {why}")
        elif index % SDD_PROGRESS_EVERY == 0 or index == total:
            _line(f"[{index}/{total}] ok")

    with _bakeoff_errors():
        data = sdd.load_sdd(root, all_captions=True)
        _line(f"SDD: {len(data.tracks)} audio files found, {len(data.missing)} missing")
        if not data.tracks:
            raise common.BakeoffError(f"no SDD audio files found under {root}")
        for key in keys:
            model_id = MODELS[key].model_id
            path = sdd.embeddings_path(root, model_id)
            if path.exists() and not force:
                _line(f"Skipping {model_id}: {path} exists (use --force to redo it)")
                continue
            with _embedders([key], settings, device=device, batch_size=batch_size) as loaded:
                report = sdd.embed_sdd(loaded[0], data, root, on_progress=progress)
            _line(
                f"{report.model_id}: embedded {report.embedded} tracks, "
                f"{len(report.failed)} decode failures, {report.missing} missing files, "
                f"in {report.elapsed_s:.1f}s -> {report.path}"
            )


@bakeoff_app.command("sdd-eval")
def bakeoff_sdd_eval(
    models: Annotated[str | None, typer.Option(help=_MODELS_HELP)] = None,
    all_captions: Annotated[
        bool,
        typer.Option("--all-captions", help="Use every caption, not just the validated subset."),
    ] = False,
    device: Annotated[str, typer.Option(help="auto, cpu or cuda.")] = "auto",
    sdd_dir: Annotated[Path | None, typer.Option(help=_SDD_DIR_HELP)] = None,
) -> None:
    """Text to audio retrieval on Song Describer: R@k, MRR, bootstrap CIs, model comparison."""
    from mcrar.ml import MODELS
    from mcrar.ml.bakeoff import common, sdd

    settings = _settings()
    keys = _model_keys(models)
    root = sdd_dir or common.sdd_dir(settings)
    model_ids = [MODELS[k].model_id for k in keys]
    with _bakeoff_errors():
        data = sdd.load_sdd(root, all_captions=all_captions)
        stored = {m: sdd.load_embeddings_file(sdd.embeddings_path(root, m)) for m in model_ids}
        gallery = sdd.common_gallery(stored, set(data.tracks))
        in_gallery = set(gallery.tolist())
        captions = [c for c in data.captions if c.track_id in in_gallery]
        if not captions:
            raise common.BakeoffError("no caption has an embedded track in every model")
        dropped = len(data.captions) - len(captions)
        note = (
            f" ({dropped} captions skipped: track not embedded by every model)" if dropped else ""
        )
        _line(f"{len(captions)} captions over {len(gallery)} tracks{note}")
        gallery_vectors = {m: common.align(*stored[m], gallery) for m in model_ids}
        caption_vectors = {}
        for key, model_id in zip(keys, model_ids, strict=True):
            with _embedders([key], settings, device=device) as loaded:
                _line(f"Embedding {len(captions)} captions with {model_id} ...")
                vectors = common.embed_texts(loaded[0], [c.text for c in captions])
            if vectors.shape[1] != gallery_vectors[model_id].shape[1]:
                raise common.BakeoffError(
                    f"{model_id}: text dim {vectors.shape[1]} does not match the saved audio "
                    f"embeddings ({gallery_vectors[model_id].shape[1]}); re-run sdd-embed --force"
                )
            caption_vectors[model_id] = vectors
        evaluation = sdd.evaluate_sdd(
            captions,
            gallery,
            gallery_vectors,
            caption_vectors,
            n_resamples=BAKEOFF_RESAMPLES,
            seed=BAKEOFF_SEED,
        )
        result = {
            "kind": "sdd",
            "created_at": common.created_at(),
            "subset": "all" if all_captions else "validated",
            "models": model_ids,
            "models_info": common.models_info(model_ids),
            "n_resamples": BAKEOFF_RESAMPLES,
            "seed": BAKEOFF_SEED,
            "captions_skipped": dropped,
            **evaluation,
        }
        path = common.write_json(
            common.results_dir(settings) / f"sdd_{common.timestamp()}.json", result
        )
    header = ("model", "R@1", "R@5", "R@10 (95% CI)", "med rank", "MRR (95% CI)", "A2T R@10")
    rows = [header]
    for model_id, r in evaluation["results"].items():
        t2a = r["t2a"]
        rows.append(
            (
                model_id,
                f"{t2a['R@1']:.3f}",
                f"{t2a['R@5']:.3f}",
                f"{t2a['R@10']:.3f} {_ci_text(t2a['R@10_ci'])}",
                f"{t2a['median_rank']:.1f}",
                f"{t2a['mrr']:.3f} {_ci_text(t2a['mrr_ci'])}",
                f"{r['a2t']['R@10']:.3f}",
            )
        )
    _line("")
    _print_rows(rows)
    _print_pairwise(evaluation["pairwise"])
    _line(f"\nSaved {path}")


def _catalog_embeddings(repo, model_ids: list[str]) -> dict:  # noqa: ANN001
    from mcrar.ml.bakeoff.common import BakeoffError

    stored = {}
    for model_id in model_ids:
        ids, matrix = repo.load_embeddings(model_id)
        if len(ids) == 0:
            raise BakeoffError(f"the catalog has no {model_id} embeddings; run: mcrar embed")
        stored[model_id] = (ids, matrix)
    return stored


@bakeoff_app.command("tag-eval")
def bakeoff_tag_eval(
    models: Annotated[str | None, typer.Option(help=_MODELS_HELP)] = None,
    min_tracks: Annotated[
        int, typer.Option(min=2, help="Only genre tags carried by at least this many tracks.")
    ] = 15,
    device: Annotated[str, typer.Option(help="auto, cpu or cuda.")] = "auto",
) -> None:
    """Rank the catalog by '<genre> music' and check it against the uploaders' genre tags."""
    from mcrar.ml import MODELS
    from mcrar.ml.bakeoff import common, tags

    settings = _settings()
    keys = _model_keys(models)
    model_ids = [MODELS[k].model_id for k in keys]
    with _bakeoff_errors():
        with _open_repo() as repo:
            stored = _catalog_embeddings(repo, model_ids)
            ids = common.intersect_ids([i for i, _ in stored.values()])
            genres = {t.id: tags.track_genres(t.source_tags) for t in repo.iter_tracks()}
        chosen = tags.select_tags(genres, ids, min_tracks)
        if not chosen:
            raise common.BakeoffError(
                f"no genre tag has {min_tracks}+ tracks among the {len(ids)} tracks "
                "embedded by every model"
            )
        _line(f"{len(chosen)} genre tags over {len(ids)} tracks embedded by every model")
        gallery_vectors = {m: common.align(*stored[m], ids) for m in model_ids}
        queries = [tags.query_text(tag) for tag, _ in chosen]
        query_vectors = {}
        for key, model_id in zip(keys, model_ids, strict=True):
            with _embedders([key], settings, device=device) as loaded:
                query_vectors[model_id] = common.embed_texts(loaded[0], queries)
        evaluation = tags.evaluate_tags(chosen, ids, genres, gallery_vectors, query_vectors)
        result = {
            "kind": "tags",
            "created_at": common.created_at(),
            "models": model_ids,
            "models_info": common.models_info(model_ids),
            "min_tracks": min_tracks,
            **evaluation,
        }
        path = common.write_json(
            common.results_dir(settings) / f"tags_{common.timestamp()}.json", result
        )
    _line(f"\nNote: {tags.LABEL_NOTE}\n")
    rows = [("model", "macro AP", "macro P@10")]
    for model_id, r in evaluation["results"].items():
        rows.append((model_id, f"{r['macro_AP']:.3f}", f"{r['macro_P@10']:.3f}"))
    _print_rows(rows)
    _line(f"\nSaved {path}")


@bakeoff_app.command("candidates")
def bakeoff_candidates(
    models: Annotated[str | None, typer.Option(help=_MODELS_HELP)] = None,
    per_model: Annotated[
        int, typer.Option(min=1, help="Top tracks taken from each model for each query.")
    ] = 3,
    queries: Annotated[
        Path | None, typer.Option(help="Text file with one query per line. Default: built in.")
    ] = None,
    device: Annotated[str, typer.Option(help="auto, cpu or cuda.")] = "auto",
) -> None:
    """Build the pooled, blind set of tracks to rate (no model names in the public file)."""
    import numpy as np

    from mcrar.ml import MODELS
    from mcrar.ml.bakeoff import candidates as cand
    from mcrar.ml.bakeoff import common
    from mcrar.ml.bakeoff.queries import load_queries

    settings = _settings()
    keys = _model_keys(models)
    model_ids = [MODELS[k].model_id for k in keys]
    with _bakeoff_errors():
        texts = load_queries(queries)
        with _open_repo() as repo:
            stored = _catalog_embeddings(repo, model_ids)
            common_ids = common.intersect_ids([i for i, _ in stored.values()])
            tracks = cand.eligible_tracks(repo, common_ids)
            if not tracks:
                raise common.BakeoffError(
                    "no track has embeddings for every model and a source_url"
                )
            ids = np.asarray([t.id for t in tracks], dtype=np.int64)
            items = {t.id: cand.item_for(t, repo.get_features(t.id)) for t in tracks}
            preferred = {t.id for t in tracks if t.download_url}
        gallery_vectors = {m: common.align(*stored[m], ids) for m in model_ids}
        query_vectors = {}
        for key, model_id in zip(keys, model_ids, strict=True):
            with _embedders([key], settings, device=device) as loaded:
                query_vectors[model_id] = common.embed_texts(loaded[0], texts)
        pooled, private = cand.build_candidates(
            texts, model_ids, ids, gallery_vectors, query_vectors, items, preferred, per_model
        )
        stamp = common.timestamp()
        out_dir = common.results_dir(settings)
        path = common.write_json(
            out_dir / f"candidates_{stamp}.json",
            {
                "queries": pooled,
                "models": model_ids,
                "per_model": per_model,
                "created_at": common.created_at(),
            },
        )
        private_path = common.write_json(out_dir / f"candidates_{stamp}.private.json", private)
    total = sum(len(q["items"]) for q in pooled)
    _line(
        f"{len(pooled)} queries, {total} tracks to rate "
        f"({len(tracks)} eligible tracks, {len(preferred)} downloadable)"
    )
    _line(f"Saved {path}")
    _line(f"Private model map (do not open before rating): {private_path}")


@bakeoff_app.command("score-ratings")
def bakeoff_score_ratings(
    ratings: Annotated[
        Path, typer.Argument(help='JSON: {"ratings": [{"query_id", "track_id", "score"}]}')
    ],
    candidates: Annotated[
        Path, typer.Option("--candidates", help="The candidates_<timestamp>.json that was rated.")
    ],
    k: Annotated[
        int | None,
        typer.Option(
            min=1, help="Score each model's top k. Default: the per_model of the candidates file."
        ),
    ] = None,
) -> None:
    """Score each model from your 0/1/2 ratings of the blind candidates."""
    from mcrar.ml.bakeoff import candidates as cand
    from mcrar.ml.bakeoff import common

    settings = _settings()
    with _bakeoff_errors():
        pool = common.read_json(candidates)
        private_file = candidates.with_name(candidates.name.removesuffix(".json") + ".private.json")
        private = common.read_json(private_file)
        parsed = cand.parse_ratings(common.read_json(ratings))
        scored = cand.score_ratings(
            pool,
            private,
            parsed,
            k=k or int(pool["per_model"]),
            n_resamples=BAKEOFF_RESAMPLES,
            seed=BAKEOFF_SEED,
        )
        result = {
            "kind": "ratings",
            "created_at": common.created_at(),
            "candidates_file": candidates.name,
            "models_info": common.models_info(scored["models"]),
            **scored,
        }
        path = common.write_json(
            common.results_dir(settings) / f"ratings_{common.timestamp()}.json", result
        )
    cov = scored["coverage"]
    _line(
        f"Rated {cov['pool_rated']} of {cov['pool_items']} pooled items "
        f"({cov['pool_fraction']:.0%}); {cov['unknown_ratings_ignored']} ratings for unknown "
        "items ignored."
    )
    k_used = scored["k"]
    rows = [("model", f"mean@{k_used}", f"nDCG@{k_used}", "rated>=1", "coverage", "queries")]
    for model_id, r in scored["results"].items():
        share = r["share_relevant"]
        rows.append(
            (
                model_id,
                "n/a" if r["mean_rating"] is None else f"{r['mean_rating']:.2f}",
                "n/a" if r["ndcg"] is None else f"{r['ndcg']:.3f}",
                "n/a" if share is None else f"{share:.0%}",
                f"{r['coverage']:.0%}",
                str(r["n_queries_scored"]),
            )
        )
    _line("")
    _print_rows(rows)
    _print_pairwise(scored["pairwise"])
    _line(f"\nSaved {path}")


@bakeoff_app.command("report")
def bakeoff_report(
    results_dir: Annotated[
        Path | None,
        typer.Option(help="Folder with the results files. Default: <data>/benchmarks/results."),
    ] = None,
    output: Annotated[
        Path | None, typer.Option(help="Where to write. Default: docs/embedder_bakeoff.md.")
    ] = None,
) -> None:
    """Write docs/embedder_bakeoff.md from the latest results, with the recommendation."""
    from mcrar.ml.bakeoff import common
    from mcrar.ml.bakeoff.report import build_report

    settings = _settings()
    source = results_dir or common.results_dir(settings)
    target = output or settings.home / "docs" / "embedder_bakeoff.md"
    with _bakeoff_errors():
        text, used = build_report(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
    for kind, name in used.items():
        _line(f"Used {kind}: {name}")
    _line(f"Wrote {target}")


# -- the optional LLM ------------------------------------------------------------------------------

llm_app = typer.Typer(help="The optional LLM that understands searches.", no_args_is_help=True)
app.add_typer(llm_app, name="llm")
LLM_REASONS = {
    "disabled": "disabled (turn it on in Settings, or set llm.enabled = true)",
    "missing_model": "no model is set (llm.model)",
    "missing_key": "no API key is stored",
}


def _llm_client(settings: Settings):  # noqa: ANN202 - lazy import; tests replace this
    from mcrar.llm.client import LLMClient

    try:
        secrets: SecretStore | None = SecretStore(settings)
    except SecretError:
        secrets = None
    return LLMClient(settings, secrets)


@llm_app.command("status")
def llm_status(
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    """Show which LLM is configured and whether it is ready (the key is never printed)."""
    client = _llm_client(_settings())
    status = client.status()
    if as_json:
        typer.echo(json.dumps(status.to_dict(), indent=2))
        return
    _line(f"Provider: {status.label} ({status.preset})")
    _line(f"Model: {status.model or '(none)'}")
    if status.ready:
        _line("Status: ready")
        return
    reason = LLM_REASONS[status.reason or "disabled"]
    if status.reason == "missing_key":
        reason += f"; set it with: mcrar secrets set {client.resolve().preset.key_secret}"
    _line(f"Status: not ready, {reason}")


@llm_app.command("test")
def llm_test() -> None:
    """Send a tiny request to the configured LLM (works while it is disabled)."""
    result = _llm_client(_settings()).test()
    if not result["ok"]:
        raise _fail(result["error"], 1)
    _line(f"OK: {result['model']} replied in {result['elapsed_ms']:.0f} ms")


@llm_app.command("models")
def llm_models(
    preset: Annotated[
        str | None, typer.Option("--preset", help="Provider preset (default: the saved one).")
    ] = None,
    base_url: Annotated[
        str | None, typer.Option("--base-url", help="Base URL (default: the preset's).")
    ] = None,
) -> None:
    """List the models the provider offers, one per line (works while the LLM is disabled)."""
    if preset is not None:
        from mcrar.llm.presets import PRESET_IDS

        if preset not in PRESET_IDS:
            raise _fail(f"unknown preset '{preset}'; choose from: {', '.join(PRESET_IDS)}")
    if base_url and not base_url.strip().startswith(("http://", "https://")):
        raise _fail("--base-url must start with http:// or https://")
    result = _llm_client(_settings()).list_models(preset=preset, base_url=base_url)
    if not result["ok"]:
        raise _fail(result["error"], 1)
    for model in result["models"]:
        _line(f"{model['id']} ({model['label']})" if model["label"] else model["id"])


def _llm_parser(settings: Settings):  # noqa: ANN202 - lazy import
    """The LLM query parser over the saved preset (it needs a key, not ``llm.enabled``)."""
    from mcrar.recommend.llm_parse import LLMParser

    return LLMParser(_llm_client(settings), settings.llm.parse_timeout_s)


# -- search ----------------------------------------------------------------------------------------

SEARCH_TITLE_WIDTH = 44


def _shorten(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 3] + "..."


def _like_file_reference(path: Path, weight: float, load_embedder, model_id: str):  # noqa: ANN001, ANN202
    """The reference song of ``--like-file``: ``path`` embedded with the model the catalog is
    searched with, by the recipe that embedded the catalog's tracks."""
    from mcrar.audio import AudioError
    from mcrar.ml.embedders import embed_audio_source
    from mcrar.recommend import ReferenceQuery, SearchError

    if not path.is_file():
        raise SearchError(f"audio file not found: {path}")
    embedder = load_embedder()
    if embedder.model_id != model_id:
        raise SearchError(
            f"the loaded embedder is {embedder.model_id}, "
            f"but the catalog is searched with {model_id}"
        )
    try:
        embedded = embed_audio_source(embedder, path)
    except AudioError as exc:
        raise SearchError(str(exc)) from None
    return ReferenceQuery(embedded.vector, path.name, "upload", weight=weight)


def _print_search_result(result, *, explain: bool, offset: int) -> None:  # noqa: ANN001
    if result.reference is not None:
        ref = result.reference
        _line(f"Reference song: {ref.label} (reference weight {ref.weight:g})")
    rows = [("#", "Title — Artist", "Score", "BPM", "Key", "Energy", "Licence", "URL")]
    for n, item in enumerate(result.items, start=offset + 1):
        who = item.title or "(untitled)"
        if item.artist:
            who += f" — {item.artist}"
        key = f"{item.key} {item.mode}" if item.key else "n/a"
        licence = f"[{item.risk}] {item.license_code}" if item.license_code else f"[{item.risk}]"
        rows.append(
            (
                str(n),
                _shorten(who, SEARCH_TITLE_WIDTH),
                f"{item.score:.3f}",
                _fmt(item.bpm, ".0f"),
                key,
                _fmt(item.energy, ".2f"),
                _shorten(licence, 24),
                item.source_url or "-",
            )
        )
    if result.items:
        left = {1, 4, 6, 7}  # text columns; the rest are numbers
        widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
        for row in rows:
            _line(
                "  ".join(
                    cell.ljust(w) if i in left else cell.rjust(w)
                    for i, (cell, w) in enumerate(zip(row, widths, strict=True))
                ).rstrip()
            )
        if explain:
            _line()
            for n, item in enumerate(result.items, start=offset + 1):
                if item.explanation:
                    _line(f"{n}. {item.explanation}")
    else:
        _line("(no results)")
    if result.parsed.notes:
        _line("\nUnderstood: " + "; ".join(result.parsed.notes))
    for note in result.relaxed:
        _line(note)
    for note in result.notes:
        _line(note)
    if result.llm is not None:
        if result.llm.used:
            cached = " (cached)" if result.llm.cached else ""
            _line(f"LLM: {result.llm.model} read the query{cached}")
        else:
            _line(f"LLM: not used ({result.llm.error})")
    _line(
        f"\n{len(result.items)} shown of {result.total_candidates} candidates "
        f"({result.elapsed_ms:.0f} ms, {result.model_id})"
    )


@app.command()
def search(
    text: Annotated[
        str,
        typer.Argument(
            help="What to look for, e.g. 'tense stealth level, no vocals'. "
            "May be empty when filters or a reference song are given."
        ),
    ] = "",
    like: Annotated[
        int | None,
        typer.Option("--like", help="Find tracks that sound like this catalog track (its id)."),
    ] = None,
    like_file: Annotated[
        Path | None,
        typer.Option(
            "--like-file", help="Find tracks that sound like this audio file (WAV, FLAC, OGG, MP3)."
        ),
    ] = None,
    ref_weight: Annotated[
        float,
        typer.Option(
            "--ref-weight",
            min=0.0,
            max=1.0,
            help="With a reference song and a text: the reference's share of the match (0-1).",
        ),
    ] = 0.5,
    genre: Annotated[str | None, typer.Option(help="Comma-separated genres to favour.")] = None,
    mood: Annotated[str | None, typer.Option(help="Comma-separated moods to favour.")] = None,
    scene: Annotated[
        str | None, typer.Option(help="Comma-separated game scenes to favour.")
    ] = None,
    intensity: Annotated[
        str | None, typer.Option(help="Energy to favour: low, mid or high (beats an energy word).")
    ] = None,
    bpm: Annotated[str | None, typer.Option(help="BPM range 80-100, or one value (±10).")] = None,
    instrumental: Annotated[
        bool, typer.Option("--instrumental", help="Only instrumental tracks.")
    ] = False,
    vocal: Annotated[bool, typer.Option("--vocal", help="Only vocal tracks.")] = False,
    max_risk: Annotated[
        str | None,
        typer.Option(help="Worst licence risk to allow: green, amber or red. Default: any."),
    ] = None,
    duration: Annotated[
        str | None, typer.Option(help="Duration in seconds: 0-30, or one value (maximum).")
    ] = None,
    source: Annotated[
        str | None, typer.Option(help="Only this source: jamendo, freesound or local.")
    ] = None,
    limit: Annotated[int, typer.Option(min=1, help="Results to show.")] = 10,
    offset: Annotated[int, typer.Option(min=0, help="Results to skip.")] = 0,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
    no_explain: Annotated[
        bool, typer.Option("--no-explain", help="Skip the explanation lines.")
    ] = False,
    use_llm: Annotated[
        bool,
        typer.Option(
            "--llm", help="Let the LLM read the query (needs its API key), even if it is disabled."
        ),
    ] = False,
) -> None:
    """Search the catalog by text, filters and/or a reference song; every result shows why it
    ranked where it did."""
    from contextlib import closing
    from dataclasses import replace

    from mcrar.catalog.db import CATALOG_FILENAME
    from mcrar.ml import ModelError
    from mcrar.recommend import SearchError, SearchFilters, SearchRequest, SearchService, Vocabulary
    from mcrar.recommend.request import build_filters, flag_name, parse_range

    if instrumental and vocal:
        raise _fail("--vocal and --instrumental are mutually exclusive")
    if like is not None and like_file is not None:
        raise _fail("--like and --like-file are mutually exclusive")
    has_reference = like is not None or like_file is not None
    settings = _settings()
    vocab = Vocabulary.load(settings)
    try:
        filters = build_filters(
            vocab,
            genres=(genre or "").split(","),
            moods=(mood or "").split(","),
            scenes=(scene or "").split(","),
            intensity=intensity,
            bpm=parse_range(bpm, "bpm", single_is_max=False),
            duration=parse_range(duration, "duration", single_is_max=True),
            max_risk=max_risk,
            vocal="instrumental" if instrumental else "vocal" if vocal else None,
            sources=(source,) if source is not None else None,
            arg=flag_name,
        )
    except ValueError as exc:
        raise _fail(str(exc)) from None
    if not text.strip() and filters == SearchFilters() and not has_reference:
        raise _fail("give a search text or at least one filter")
    if not (settings.data_dir / CATALOG_FILENAME).is_file():
        raise _fail(
            "the catalog is empty; add tracks first: mcrar ingest jamendo|freesound|local", 1
        )

    models: list = []  # the embedder, loaded once for the reference file and the text

    def load_embedder():  # noqa: ANN202 - called only when an embedding is needed
        if not models:
            _line(f"Loading {settings.default_embedder} ...", err=True)
            models.append(_load_embedder(settings.default_embedder, settings))
        return models[0]

    request = SearchRequest(
        text=text, filters=filters, limit=limit, offset=offset, explain=not no_explain
    )
    try:
        with (
            _open_repo() as repo,
            closing(
                SearchService(
                    repo,
                    settings,
                    embedder_loader=load_embedder,
                    vocab=vocab,
                    parser=_llm_parser(settings) if use_llm or settings.llm.enabled else None,
                )
            ) as service,
        ):
            try:
                if like is not None:
                    try:
                        reference = service.reference_for_track(like, ref_weight)
                    except LookupError as exc:
                        raise SearchError(str(exc.args[0])) from None
                    request = replace(request, reference=reference)
                elif like_file is not None:
                    reference = _like_file_reference(
                        like_file, ref_weight, load_embedder, service.model_id
                    )
                    request = replace(request, reference=reference)
                result = service.search(request)
            finally:
                if models and not service.embedder_loaded:  # else the service closes it
                    close = getattr(models[0], "close", None)
                    if close is not None:
                        close()
    except (SearchError, ModelError) as exc:
        raise _fail(str(exc), 1) from None
    except Exception as exc:  # never show a traceback
        from mcrar.api.jobs import redact

        raise _fail(f"search failed ({type(exc).__name__}: {redact(str(exc))[:200]})", 1) from None
    if as_json:
        typer.echo(json.dumps(result.to_dict(), indent=2))
        return
    _print_search_result(result, explain=not no_explain, offset=offset)


# -- scenes ----------------------------------------------------------------------------------------

scenes_app = typer.Typer(
    help="Game-scene tags: zero-shot from text prompts, standardised on your catalog.",
    no_args_is_help=True,
)
app.add_typer(scenes_app, name="scenes")


@scenes_app.command("build")
def scenes_build() -> None:
    """Build the two zero-shot scene taggers from the catalog's CLAP embeddings.

    Builds the plain and the centered variant (the centered one is selected until hand labels
    say otherwise). Run it again after the catalog grew. It only embeds the text prompts; tag the
    catalog with the result afterwards: mcrar tag --label-sets scene
    """
    from mcrar.ml import ModelError
    from mcrar.ml.tagging.registry import read_registry, select_entry
    from mcrar.ml.tagging.scenes import build_scene_entries, catalog_reference

    settings = _settings()
    try:
        with _open_repo() as repo:
            catalog_reference(repo)  # fail before loading the model when the catalog is too small
            with _embedders(["clap"], settings) as (embedder,):
                entries = build_scene_entries(settings, embedder, repo)
        chosen = select_entry(read_registry(settings)["label_sets"]["scene"])
    except (ModelError, ValueError) as exc:
        raise _fail(str(exc), 1) from None
    for entry in entries:
        _line(
            f"Built {entry['id']} (centering {entry['centering']}; "
            f"reference: {entry['reference_data']})"
        )
    _line(f"Selected: {chosen['id'] if chosen else 'none'}")
    _line("Next, tag the catalog with it: mcrar tag --label-sets scene")


def _pool_summary_lines(pool) -> list[str]:  # noqa: ANN001 - list[PoolEntry]
    from mcrar.ml.tagging.scene_pool import summarise_pool

    summary = summarise_pool(pool)
    lines = [f"Pool of {summary.size} tracks"]
    lines.append("  parts: " + ", ".join(f"{p} {n}" for p, n in summary.parts.items()))
    lines.append("  reasons:")
    lines += [f"    {reason}: {n}" for reason, n in summary.reasons.items()]
    return lines


@scenes_app.command("pool")
def scenes_pool(
    per_scene: Annotated[
        int, typer.Option("--per-scene", min=0, help="Top tracks per scene and zero-shot entry.")
    ] = 10,
    random: Annotated[
        int, typer.Option("--random", min=0, help="Random other tracks to add.")
    ] = 100,
    both: Annotated[
        int, typer.Option("--both", min=0, help="Tracks both people label (spread over the order).")
    ] = 30,
    seed: Annotated[
        int, typer.Option("--seed", help="Seed of the random picks and the order.")
    ] = 0,
    force: Annotated[
        bool, typer.Option("--force", help="Replace an existing pool (labels are kept).")
    ] = False,
) -> None:
    """Choose the tracks to hand-label: each zero-shot entry's top tracks per scene, plus random.

    The pool is shuffled, numbered, and split into parts A and B (plus the shared `both` tracks).
    Labels belong to tracks, so they survive replacing the pool with --force.
    """
    from mcrar.ml.tagging.scene_pool import build_pool, save_pool

    settings = _settings()
    try:
        with _open_repo() as repo:
            pool = build_pool(
                repo, settings, per_scene=per_scene, random_n=random, both_n=both, seed=seed
            )
            save_pool(repo, pool, force=force)
    except ValueError as exc:
        raise _fail(str(exc), 1) from None
    for line in _pool_summary_lines(pool):
        _line(line)
    _line("Next: start the app (mcrar serve) and label in the Labelling tab.")


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _fail(f"cannot read {path}: {type(exc).__name__}", 1) from None


@scenes_app.command("export-pack")
def scenes_export_pack(
    out: Annotated[Path, typer.Argument(help="Where to write the pack (JSON).")],
) -> None:
    """Write the pool as a pack to give to a collaborator (tracks named by source and id)."""
    from mcrar.ml.tagging.scene_share import export_pack

    try:
        with _open_repo() as repo:
            pack = export_pack(repo)
    except ValueError as exc:
        raise _fail(str(exc), 1) from None
    _write_json(out, pack)
    _line(f"Wrote {len(pack['tracks'])} tracks to {out}")


@scenes_app.command("import-pack")
def scenes_import_pack(
    pack: Annotated[Path, typer.Argument(help="A pack written by mcrar scenes export-pack.")],
    no_fetch: Annotated[
        bool, typer.Option("--no-fetch", help="Do not fetch missing tracks; map what exists.")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Replace an existing pool (labels are kept).")
    ] = False,
) -> None:
    """Make the pack's pool this catalog's pool, fetching missing Jamendo tracks (metadata only).

    Fetching uses your own Jamendo client id (mcrar secrets set jamendo_client_id). No audio is
    downloaded and no embedding is made: labelling only needs the tracks to stream.
    """
    from mcrar.ml.tagging.scene_share import import_pack
    from mcrar.sources import JamendoError

    data = _read_json(pack)
    settings = _settings()

    def open_client():  # noqa: ANN202
        try:
            return _jamendo_client(settings, True)
        except (JamendoError, SecretError) as exc:
            raise ValueError(str(exc)) from None

    try:
        with _open_repo() as repo:
            result = import_pack(
                repo,
                data,
                open_client=None if no_fetch else open_client,
                force=force,
                on_progress=_print_progress,
            )
    except (ValueError, JamendoError) as exc:
        raise _fail(str(exc), 1) from None
    _line(
        f"Pool of {result.pool_size} tracks: {result.present} were already here, "
        f"{result.fetched} fetched."
    )
    for item in result.missing:
        _line(
            f"  skipped {item['source']}:{item['source_id']} {item['title'] or ''}: "
            f"{item['reason']}"
        )
    if result.missing:
        _line(f"{len(result.missing)} track(s) of the pack are not in your pool.")


@scenes_app.command("export-labels")
def scenes_export_labels(
    out: Annotated[Path, typer.Argument(help="Where to write the labels (JSON).")],
    labeller: Annotated[
        str | None, typer.Option("--labeller", help="Only this labeller's labels.")
    ] = None,
) -> None:
    """Write the hand labels (every labeller, or one) to send to the other person."""
    from mcrar.ml.tagging.scene_share import export_labels

    try:
        with _open_repo() as repo:
            data = export_labels(repo, labeller)
    except ValueError as exc:
        raise _fail(str(exc), 1) from None
    _write_json(out, data)
    _line(f"Wrote {len(data['labels'])} labels to {out}")


@scenes_app.command("import-labels")
def scenes_import_labels(
    file: Annotated[Path, typer.Argument(help="A file written by mcrar scenes export-labels.")],
    as_labeller: Annotated[
        str | None, typer.Option("--as", help="Store every label under this name instead.")
    ] = None,
) -> None:
    """Add someone's labels (matched to your tracks by source and id); the newer label wins."""
    from mcrar.catalog import open_catalog
    from mcrar.ml.tagging.scene_share import import_labels
    from mcrar.recommend.vocab import Vocabulary

    data = _read_json(file)
    settings = _settings()
    try:
        with open_catalog(settings) as repo:
            result = import_labels(repo, data, Vocabulary.load(settings), as_labeller=as_labeller)
    except ValueError as exc:
        raise _fail(str(exc), 1) from None
    _line(
        f"Stored {result.stored} label(s) of {', '.join(result.labellers) or 'nobody'}; "
        f"{result.older} kept because yours were newer."
    )
    if result.unknown:
        shown = ", ".join(result.unknown[:10]) + (" ..." if len(result.unknown) > 10 else "")
        _line(f"Skipped {len(result.unknown)} track(s) that are not in this catalog: {shown}")


@scenes_app.command("eval")
def scenes_eval(
    k: Annotated[int, typer.Option("--k", min=1, help="List length for precision@k.")] = 10,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
    folds: Annotated[int, typer.Option("--folds", min=2, help="Cross-validation folds.")] = 5,
    seed: Annotated[int, typer.Option("--seed", help="Seed of the fold split.")] = 0,
) -> None:
    """Score every scene entry against your hand labels (and write the result under data/)."""
    from mcrar.ml.tagging.scene_eval import evaluate_scenes, format_report, write_results

    settings = _settings()
    try:
        with _open_repo() as repo:
            result = evaluate_scenes(repo, settings, k=k, folds=folds, seed=seed)
    except ValueError as exc:
        raise _fail(str(exc), 1) from None
    path = write_results(settings, result)
    if as_json:
        typer.echo(json.dumps(result, indent=2))
        return
    _line(format_report(result))
    _line(f"\nWrote {path}")


@scenes_app.command("train")
def scenes_train(
    folds: Annotated[int, typer.Option("--folds", min=2, help="Cross-validation folds.")] = 5,
    seed: Annotated[int, typer.Option("--seed", help="Seed of the folds and the fit.")] = 0,
) -> None:
    """Fit the optional scene head on your labels and select the best entry by mean P@10.

    Scenes with at least 5 positives and 5 negatives get a logistic regression; the others keep
    the best zero-shot entry's column. The head only wins if it scores higher in cross-validation.
    """
    from mcrar.ml.tagging.scene_head import train_scene_head

    settings = _settings()
    try:
        with _open_repo() as repo:
            result = train_scene_head(settings, repo, folds=folds, seed=seed)
    except ValueError as exc:
        raise _fail(str(exc), 1) from None
    _line(f"Trained on {result['n_tracks']} labelled tracks ({folds}-fold cross-validation).")
    for variant, score in result["scores"].items():
        mean = "n/a" if score is None else f"{score:.3f}"
        _line(f"  {variant}: mean P@10 {mean}")
    _line(
        f"Trained scenes: {', '.join(result['trained']) or 'none'}; "
        f"the rest use {result['fallback']}."
    )
    if result["head_won"]:
        _line(f"The head won and is selected: {result['selected']}")
    else:
        _line(f"The head did not win; selected: {result['selected']}")
    if result["selected"] != result["previous"]:
        _line("The selection changed: tag the catalog again: mcrar tag --label-sets scene")


# -- ratings ---------------------------------------------------------------------------------------

ratings_app = typer.Typer(
    help="Your ratings of search results: import listening-test files, measure ranking quality.",
    no_args_is_help=True,
)
app.add_typer(ratings_app, name="ratings")


def _query_texts(data: object) -> dict[str, str]:
    """``{query id: text}`` from a candidates file (``{"queries": [{"id", "text", ...}]}``)."""
    from mcrar.ml.bakeoff import BakeoffError

    entries = data.get("queries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise BakeoffError('queries file must look like {"queries": [{"id", "text", ...}]}')
    texts: dict[str, str] = {}
    for n, entry in enumerate(entries, start=1):
        try:
            texts[str(entry["id"])] = str(entry["text"])
        except (KeyError, TypeError):
            raise BakeoffError(f"query #{n} needs an id and a text") from None
    return texts


@ratings_app.command("import")
def ratings_import(
    ratings_file: Annotated[
        Path, typer.Argument(help='JSON: {"ratings": [{"query_id", "track_id", "score"}]}')
    ],
    queries: Annotated[
        Path,
        typer.Option(
            "--queries", help="The candidates_<timestamp>.json that holds the query texts."
        ),
    ],
    replace: Annotated[
        bool,
        typer.Option(
            "--replace",
            help="First delete the stored ratings of the queries in the file (default: merge).",
        ),
    ] = False,
) -> None:
    """Store the ratings of a listening-test file as ratings of the query texts (repeatable)."""
    from mcrar.ml.bakeoff import BakeoffError, common
    from mcrar.ml.bakeoff import candidates as cand
    from mcrar.recommend import SearchFilters
    from mcrar.recommend.ratings import filters_to_json, normalise_text, query_key

    try:
        parsed = cand.parse_ratings(common.read_json(ratings_file))
        texts = _query_texts(common.read_json(queries))
        unknown = sorted({q for q, _ in parsed} - set(texts))
        if unknown:
            raise BakeoffError(f"the queries file has no query {', '.join(unknown)}")
        keys = {q: query_key(texts[q], SearchFilters()) for q in {q for q, _ in parsed}}
    except (BakeoffError, ValueError) as exc:
        raise _fail(str(exc), 1) from None
    filters_json = filters_to_json(SearchFilters())
    stored = skipped = removed = 0
    with _open_repo() as repo:
        known = {t.id for t in repo.iter_tracks()}
        if replace:
            for rating in repo.iter_ratings():
                if rating.query_key in keys.values():
                    removed += repo.delete_rating(rating.query_key, rating.track_id)
        for (query_id, track_id), score in sorted(parsed.items()):
            if track_id not in known:
                skipped += 1
                continue
            repo.set_rating(
                keys[query_id],
                track_id,
                score,
                query_text=normalise_text(texts[query_id]),
                filters_json=filters_json,
            )
            stored += 1
    if removed:
        _line(f"Removed {removed} earlier rating(s) of these queries.")
    _line(f"Stored {stored} rating(s) for {len(set(keys.values()))} query text(s).")
    if skipped:
        _line(f"Skipped {skipped} rating(s) of tracks that are not in the catalog.")


def _mean(values: list[int]) -> float | None:
    return sum(values) / len(values) if values else None


def _eval_row(label: str, mean: float | None, rated: int, unrated: int) -> tuple[str, ...]:
    return (label, "n/a" if mean is None else f"{mean:.2f}", str(rated), str(unrated))


@ratings_app.command("eval")
def ratings_eval(
    k: Annotated[int, typer.Option("--k", min=1, help="Hits per query to look at.")] = 2,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
    use_llm: Annotated[
        bool,
        typer.Option("--llm", help="Parse the queries with the LLM instead of the rules."),
    ] = False,
) -> None:
    """Run every rated query through the current search and average your ratings of the top k.

    Hits you did not rate are left out and counted. The overall mean pools all rated hits. With
    `--llm` the LLM reads the queries (rules are the default), so two runs compare the parsers.
    """
    from contextlib import closing

    from mcrar.ml import ModelError
    from mcrar.recommend import SearchError, SearchRequest, SearchService
    from mcrar.recommend.ratings import filters_from_json

    settings = _settings()
    with _open_repo() as repo:
        queries = repo.rating_queries()
        if not queries:
            raise _fail("there are no ratings yet; rate results or run: mcrar ratings import", 1)
        if any(text for _, text, _, _ in queries) and not _torch_available():
            raise _fail(
                "text queries need the ml extra (torch is not installed): uv sync --extra ml", 1
            )

        def load_embedder():  # noqa: ANN202 - called once, on the first text query
            _line(f"Loading {settings.default_embedder} ...", err=True)
            return _load_embedder(settings.default_embedder, settings)

        report: list[dict] = []
        llm_queries = fell_back = 0
        parser = _llm_parser(settings) if use_llm else None
        try:
            with closing(
                SearchService(repo, settings, embedder_loader=load_embedder, parser=parser)
            ) as service:
                for key, text, filters_json, _ in queries:
                    request = SearchRequest(
                        text=text, filters=filters_from_json(filters_json), limit=k, explain=False
                    )
                    found = service.search(request)
                    items = found.items
                    if found.llm is not None:
                        llm_queries += 1
                        fell_back += not found.llm.used
                    given = repo.ratings_for(key, (i.track_id for i in items))
                    scores = [given[i.track_id] for i in items if i.track_id in given]
                    report.append(
                        {
                            "query_key": key,
                            "query_text": text,
                            "filters": json.loads(filters_json),
                            "mean": _mean(scores),
                            "rated": len(scores),
                            "unrated": len(items) - len(scores),
                            "hits": [
                                {"track_id": i.track_id, "rating": given.get(i.track_id)}
                                for i in items
                            ],
                        }
                    )
        except (SearchError, ModelError) as exc:
            raise _fail(str(exc), 1) from None
        except ValueError as exc:
            raise _fail(f"a stored query cannot be run ({exc})", 1) from None
        except Exception as exc:  # never show a traceback
            from mcrar.api.jobs import redact

            raise _fail(
                f"eval failed ({type(exc).__name__}: {redact(str(exc))[:200]})", 1
            ) from None
    pooled = [h["rating"] for q in report for h in q["hits"] if h["rating"] is not None]
    overall = {
        "mean": _mean(pooled),
        "rated": len(pooled),
        "unrated": sum(q["unrated"] for q in report),
    }
    llm_info = {"parser": "llm", "llm_queries": llm_queries, "llm_fell_back": fell_back}
    if as_json:
        data = {"k": k, "queries": report, "overall": overall, **(llm_info if use_llm else {})}
        typer.echo(json.dumps(data, indent=2))
        return
    if use_llm:
        _line(f"Parser: LLM; {fell_back} of {llm_queries} text queries fell back to the rules")
    rows = [("Query", f"Top-{k} mean", "Rated", "Unrated")]
    for q in report:
        label = q["query_text"] or q["query_key"].removeprefix("filters:")
        mean, rated, unrated = q["mean"], q["rated"], q["unrated"]
        rows.append(_eval_row(_shorten(label, SEARCH_TITLE_WIDTH), mean, rated, unrated))
    rows.append(_eval_row("Overall (rated hits pooled)", **overall))
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    for row in rows:
        _line(
            "  ".join(
                cell.ljust(w) if i == 0 else cell.rjust(w)
                for i, (cell, w) in enumerate(zip(row, widths, strict=True))
            )
        )


# -- serve -----------------------------------------------------------------------------------------


def _is_loopback(host: str) -> bool:
    import ipaddress

    name = host.strip().strip("[]").lower()
    if name == "localhost":
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def _browser_url(host: str, port: int) -> str:
    """The address a browser on this machine uses for a server listening on ``host``."""
    name = host.strip().strip("[]")
    if name in ("", "0.0.0.0", "localhost"):
        name = "127.0.0.1"
    elif name == "::":
        name = "::1"
    return f"http://[{name}]:{port}/" if ":" in name else f"http://{name}:{port}/"


def _looks_like_mcrar(response: Any) -> bool:
    """Whether an ``/api/health`` answer is the one of an MCRAR server."""
    try:
        body = response.json()
    except ValueError:
        return False
    return (
        response.status_code == 200
        and isinstance(body, dict)
        and body.get("status") == "ok"
        and "version" in body
    )


def _can_bind(host: str, port: int) -> bool:
    import socket

    name = host.strip().strip("[]")
    family = socket.AF_INET6 if ":" in name else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        if os.name != "nt":  # like uvicorn; on Windows it would let a second server in
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((name, port))
        except OSError:
            return False
    return True


def _probe_server(host: str, port: int) -> str:
    """What is on ``host``:``port``: ``mcrar`` (an MCRAR server), ``free`` or ``other``.

    Binding comes first: on Windows a refused connection to a closed port takes about 2 s,
    which would look like a timeout.
    """
    if _can_bind(host, port):
        return "free"
    import httpx

    try:
        # trust_env off: a proxy setting must not send this loopback request elsewhere
        answer = httpx.get(_browser_url(host, port) + "api/health", timeout=2.0, trust_env=False)
    except httpx.HTTPError:  # refused, timed out or not a web server: something holds the port
        return "other"
    return "mcrar" if _looks_like_mcrar(answer) else "other"


def _open_browser_when_ready(
    url: str, *, timeout_s: float = 60.0, interval_s: float = 0.25
) -> None:
    """Open ``url`` in the browser as soon as the server answers (in a daemon thread, so it
    never holds the process back; gives up after ``timeout_s``)."""
    import threading
    import time
    import webbrowser

    import httpx

    def wait_and_open() -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                answer = httpx.get(url + "api/health", timeout=2.0, trust_env=False)
                ready = _looks_like_mcrar(answer)
            except httpx.HTTPError:
                ready = False
            if ready:
                try:
                    webbrowser.open(url)
                except Exception:  # no browser available: the URL was printed already
                    pass
                return
            time.sleep(interval_s)

    threading.Thread(target=wait_and_open, name="open-browser", daemon=True).start()


@app.command()
def serve(
    host: Annotated[
        str | None, typer.Option(help="Address to listen on. Default: api_host from the settings.")
    ] = None,
    port: Annotated[
        int | None,
        typer.Option(
            min=1, max=65535, help="Port to listen on. Default: api_port from the settings."
        ),
    ] = None,
    warm: Annotated[
        bool, typer.Option("--warm", help="Load the text embedding model in the background.")
    ] = False,
    allow_remote: Annotated[
        bool,
        typer.Option(
            "--allow-remote", help="Listen on a non-loopback address (no login; careful)."
        ),
    ] = False,
    reload: Annotated[
        bool, typer.Option("--reload", help="Restart on code changes (development).")
    ] = False,
    open_browser: Annotated[
        bool,
        typer.Option(
            "--open/--no-open", help="Open the web UI in the browser once the server answers."
        ),
    ] = False,
) -> None:
    """Run the HTTP API, and the built frontend when frontend/dist exists, on this machine.

    When an MCRAR server already answers on the address, nothing new is started (the browser
    opens there with --open); another program on the port is an error.
    """
    settings = _settings()
    host = host or settings.api_host
    port = port or settings.api_port
    if not _is_loopback(host):
        if not allow_remote:
            raise _fail(
                f"refusing to listen on {host}: the API has no login, so it only listens on "
                "this machine; pass --allow-remote to listen on the network anyway"
            )
        _line(
            f"warning: listening on {host} without a login; anyone who can reach this "
            "address can use the API",
            err=True,
        )
    url = _browser_url(host, port)
    taken = _probe_server(host, port)
    if taken == "mcrar":
        _line(f"MCRAR is already running at {url}")
        if open_browser:
            import webbrowser

            webbrowser.open(url)
        return
    if taken == "other":
        raise _fail(
            f"port {port} on {host} is in use by another program; "
            "stop it or pick another port with --port"
        )
    # The app factory runs inside uvicorn (possibly a reload subprocess) and reads its
    # configuration from the environment, so hand the choices over that way.
    os.environ["MCRAR_API_HOST"] = host
    os.environ["MCRAR_API_PORT"] = str(port)
    if warm:
        os.environ["MCRAR_API_WARM"] = "1"
    if open_browser:
        _open_browser_when_ready(url)
    import uvicorn

    uvicorn.run("mcrar.api.app:create_app", factory=True, host=host, port=port, reload=reload)
