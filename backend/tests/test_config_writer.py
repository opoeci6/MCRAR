"""Writing config/settings.toml (the settings page) and listing env-pinned fields."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from mcrar.config import env_overrides, get_settings, save_settings_update, settings_file


def read(home: Path) -> dict:
    return tomllib.loads(settings_file(home).read_text(encoding="utf-8"))


def test_creates_the_file_and_the_config_folder(isolated_env: Path) -> None:
    save_settings_update(isolated_env, {"default_embedder": "glap"})
    assert read(isolated_env) == {"default_embedder": "glap"}
    assert get_settings().default_embedder == "glap"


def test_merges_into_the_existing_file_and_keeps_other_keys(isolated_env: Path) -> None:
    path = settings_file(isolated_env)
    path.parent.mkdir()
    path.write_text(
        "api_port = 9001\n[search]\npool_size = 50\n[search.weights]\ntags = 0.5\nbpm = 0.2\n",
        encoding="utf-8",
    )
    save_settings_update(
        isolated_env,
        {"default_embedder": "glap", "search": {"max_per_artist": 3, "weights": {"bpm": 0.0}}},
    )
    assert read(isolated_env) == {
        "api_port": 9001,
        "default_embedder": "glap",
        "search": {
            "pool_size": 50,
            "max_per_artist": 3,
            "weights": {"tags": 0.5, "bpm": 0.0},
        },
    }
    settings = get_settings()
    assert (settings.api_port, settings.default_embedder) == (9001, "glap")
    assert (settings.search.pool_size, settings.search.weights.tags) == (50, 0.5)


def test_a_save_drops_the_legacy_commercial_mode_key(isolated_env: Path) -> None:
    path = settings_file(isolated_env)
    path.parent.mkdir()
    path.write_text("commercial_mode = false\napi_port = 9001\n", encoding="utf-8")
    save_settings_update(isolated_env, {"search": {"pool_size": 10}})
    assert read(isolated_env) == {"api_port": 9001, "search": {"pool_size": 10}}


def test_a_write_leaves_no_temporary_files(isolated_env: Path) -> None:
    save_settings_update(isolated_env, {"search": {"pool_size": 10}})
    save_settings_update(isolated_env, {"search": {"pool_size": 20}})
    assert [p.name for p in settings_file(isolated_env).parent.iterdir()] == ["settings.toml"]
    assert read(isolated_env) == {"search": {"pool_size": 20}}


@pytest.mark.parametrize(
    "update",
    [
        {"search": {"pool_size": 0}},
        {"search": {"weights": {"tags": -1}}},
        {"search": {"weights": {"semantic": 0, "tags": 0, "bpm": 0, "energy": 0}}},
        {"search": {"unknown": 1}},
        {"commercial_mode": False},  # removed setting: no longer editable
        {"default_embedder": ""},
        {"api_port": 1},
        {"secrets_backend": "env"},
    ],
)
def test_an_invalid_update_raises_and_leaves_the_file_untouched(
    isolated_env: Path, update: dict
) -> None:
    save_settings_update(isolated_env, {"search": {"pool_size": 10}})
    before = settings_file(isolated_env).read_bytes()
    with pytest.raises(ValueError):
        save_settings_update(isolated_env, update)
    assert settings_file(isolated_env).read_bytes() == before
    assert [p.name for p in settings_file(isolated_env).parent.iterdir()] == ["settings.toml"]


def test_an_invalid_update_does_not_create_a_file(isolated_env: Path) -> None:
    with pytest.raises(ValueError, match="pool_size"):
        save_settings_update(isolated_env, {"search": {"pool_size": 0}})
    assert not settings_file(isolated_env).exists()


def test_a_broken_existing_file_is_reported_not_overwritten(isolated_env: Path) -> None:
    path = settings_file(isolated_env)
    path.parent.mkdir()
    path.write_text("this is = = not toml", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot read"):
        save_settings_update(isolated_env, {"default_embedder": "glap"})
    assert path.read_text(encoding="utf-8") == "this is = = not toml"


def test_env_overrides_lists_dotted_field_names(monkeypatch: pytest.MonkeyPatch) -> None:
    assert env_overrides() == []
    monkeypatch.setenv("MCRAR_DEFAULT_EMBEDDER", "glap")
    monkeypatch.setenv("MCRAR_SEARCH__POOL_SIZE", "5")
    monkeypatch.setenv("MCRAR_SEARCH__WEIGHTS__TAGS", "1")
    monkeypatch.setenv("MCRAR_API_PORT", "1234")
    assert env_overrides() == [
        "api_port",
        "default_embedder",
        "search.pool_size",
        "search.weights.tags",
    ]


def test_env_overrides_ignores_home_secrets_and_unknown_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCRAR_SECRET_JAMENDO_CLIENT_ID", "x")
    monkeypatch.setenv("MCRAR_NOT_A_SETTING", "x")
    monkeypatch.setenv("MCRAR_SEARCH__NOPE", "x")
    monkeypatch.setenv("OTHER_API_PORT", "x")
    monkeypatch.setenv("MCRAR_API_HOST", "127.0.0.1")
    assert env_overrides() == ["api_host"]  # MCRAR_HOME is set by the fixture, not listed


def test_env_overrides_expands_a_whole_table_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCRAR_SEARCH__WEIGHTS", '{"tags": 1}')
    assert env_overrides() == [
        "search.weights.bpm",
        "search.weights.energy",
        "search.weights.semantic",
        "search.weights.tags",
    ]
