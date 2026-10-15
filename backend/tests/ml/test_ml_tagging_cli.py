"""New CLI groups and stored-only catalog tagging work with lightweight fixtures."""

from __future__ import annotations

from tagging_support import register, synthetic
from typer.testing import CliRunner

from mcrar.catalog import TrackRecord, open_catalog
from mcrar.cli import app
from mcrar.config import get_settings
from mcrar.ml.tagging.registry import read_registry

runner = CliRunner()


def test_command_groups_and_clean_errors() -> None:
    for args in (["datasets", "--help"], ["tagging", "--help"], ["tag", "--help"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
    for args in (
        ["datasets", "download", "unknown"],
        ["tagging", "train", "unknown"],
    ):
        result = runner.invoke(app, args)
        assert result.exit_code == 1 and "error:" in result.output
        assert "Traceback" not in result.output


def test_catalog_tagging_and_selection_cli_use_stored_vectors() -> None:
    settings = get_settings()
    register(settings)
    x, _ = synthetic(3)
    with open_catalog(settings) as repo:
        tid = repo.upsert_track(TrackRecord(source="jamendo", source_id="1", title="Test"))
        repo.set_embedding(tid, "clap@195c3a3", x[0])
    result = runner.invoke(app, ["tag"])
    assert result.exit_code == 0, result.output
    assert "Tagged 1" in result.output
    result = runner.invoke(app, ["tag"])
    assert result.exit_code == 0 and "skipped 1" in result.output
    with open_catalog(settings) as repo:
        assert len(repo.get_tag_probs(tid, "genre")) == 3
    result = runner.invoke(app, ["tagging", "select"])
    assert result.exit_code == 0 and "genre: genre-logreg@" in result.output
    assert "mode" not in result.output.lower()
    selected = read_registry(settings)["selected"]
    assert list(selected) == ["genre"] and selected["genre"].startswith("genre-logreg@")


def test_tag_progress_survives_a_narrow_console_code_page() -> None:
    # Piped output on Windows uses the locale code page; GBK cannot encode "É".
    settings = get_settings()
    register(settings)
    x, _ = synthetic(3)
    with open_catalog(settings) as repo:
        tid = repo.upsert_track(TrackRecord(source="jamendo", source_id="1", title="Élan"))
        repo.set_embedding(tid, "clap@195c3a3", x[0])
    result = CliRunner(charset="gbk").invoke(app, ["tag"])
    assert result.exit_code == 0, result.output
    assert "?lan" in result.output and "Tagged 1" in result.output
