"""The [search] settings: defaults, the toml table, MCRAR_SEARCH__* variables, validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from mcrar.cli import app
from mcrar.config import SearchSettings, get_settings


def test_defaults() -> None:
    search = get_settings().search
    assert (search.pool_size, search.max_per_artist, search.min_results) == (200, 2, 1)
    w = search.weights
    assert (w.semantic, w.tags, w.bpm, w.energy) == (0.6, 0.2, 0.1, 0.1)


def test_nested_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCRAR_SEARCH__POOL_SIZE", "50")
    monkeypatch.setenv("MCRAR_SEARCH__MAX_PER_ARTIST", "1")
    monkeypatch.setenv("MCRAR_SEARCH__MIN_RESULTS", "0")
    monkeypatch.setenv("MCRAR_SEARCH__WEIGHTS__SEMANTIC", "0.9")
    search = get_settings().search
    assert (search.pool_size, search.max_per_artist, search.min_results) == (50, 1, 0)
    assert search.weights.semantic == 0.9 and search.weights.tags == 0.2  # the rest keep defaults


def test_toml_table(isolated_env: Path) -> None:
    (isolated_env / "config").mkdir()
    (isolated_env / "config" / "settings.toml").write_text(
        "[search]\npool_size = 75\n[search.weights]\nbpm = 0.3\n", encoding="utf-8"
    )
    search = get_settings().search
    assert search.pool_size == 75 and search.max_per_artist == 2
    assert search.weights.bpm == 0.3 and search.weights.semantic == 0.6


def test_environment_beats_toml_and_init_beats_environment(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (isolated_env / "config").mkdir()
    (isolated_env / "config" / "settings.toml").write_text(
        "[search]\npool_size = 75\n", encoding="utf-8"
    )
    monkeypatch.setenv("MCRAR_SEARCH__POOL_SIZE", "60")
    assert get_settings().search.pool_size == 60
    assert get_settings(search={"pool_size": 10}).search.pool_size == 10


def test_unknown_search_keys_are_still_an_error(isolated_env: Path) -> None:
    (isolated_env / "config").mkdir()
    (isolated_env / "config" / "settings.toml").write_text(
        "[search]\npool_sise = 5\n", encoding="utf-8"
    )
    with pytest.raises(ValidationError):
        get_settings()
    (isolated_env / "config" / "settings.toml").write_text(
        "[search.weights]\nsemantics = 1\n", encoding="utf-8"
    )
    with pytest.raises(ValidationError):
        get_settings()
    (isolated_env / "config" / "settings.toml").write_text("typo = 1\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        get_settings()


@pytest.mark.parametrize(
    "override",
    [
        {"pool_size": 0},
        {"max_per_artist": 0},
        {"min_results": -1},
        {"weights": {"semantic": -0.1}},
        {"weights": {"semantic": 0, "tags": 0, "bpm": 0, "energy": 0}},
    ],
)
def test_invalid_values_are_rejected(override: dict) -> None:
    with pytest.raises(ValidationError):
        get_settings(search=override)


def test_other_mcrar_variables_still_work(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCRAR_API_PORT", "9001")
    monkeypatch.setenv("MCRAR_SECRET_JAMENDO_CLIENT_ID", "x")  # secrets use a single underscore
    assert get_settings().api_port == 9001


def test_config_show_includes_the_search_settings() -> None:
    result = CliRunner().invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert json.loads(result.output)["search"]["weights"]["semantic"] == 0.6


def test_the_example_settings_file_parses_and_matches_the_defaults(isolated_env: Path) -> None:
    example = Path(__file__).resolve().parents[3] / "config" / "settings.example.toml"
    (isolated_env / "config").mkdir()
    (isolated_env / "config" / "settings.toml").write_text(
        example.read_text(encoding="utf-8"), encoding="utf-8"
    )
    from_file = get_settings()
    assert from_file.search == SearchSettings()
    assert from_file.search.pool_size == 200 and from_file.search.weights.energy == 0.1
