from pathlib import Path

import pytest
from pydantic import ValidationError

from mcrar.config import ConfigError, find_repo_root, get_settings


def test_defaults_resolve_under_home(isolated_env: Path) -> None:
    s = get_settings()
    assert s.home == isolated_env.resolve()
    assert s.data_dir == s.home / "data"
    assert s.models_dir == s.home / "models"
    assert s.cache_dir == s.home / ".cache"
    assert s.secrets_dir == s.home / ".secrets"
    assert s.commercial_mode is True
    assert s.secrets_backend == "file"
    assert s.api_host == "127.0.0.1"
    assert s.api_port == 8000


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCRAR_COMMERCIAL_MODE", "false")
    monkeypatch.setenv("MCRAR_API_PORT", "9001")
    monkeypatch.setenv("MCRAR_SECRETS_BACKEND", "env")
    s = get_settings()
    assert s.commercial_mode is False
    assert s.api_port == 9001
    assert s.secrets_backend == "env"


def test_relative_env_path_resolved_under_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCRAR_DATA_DIR", "somewhere/else")
    s = get_settings()
    assert s.data_dir == s.home / "somewhere" / "else"


def test_absolute_path_kept(tmp_path: Path) -> None:
    target = (tmp_path / "elsewhere").resolve()
    assert get_settings(data_dir=target).data_dir == target


def test_toml_override(isolated_env: Path) -> None:
    (isolated_env / "config").mkdir()
    (isolated_env / "config" / "settings.toml").write_text(
        'commercial_mode = false\napi_port = 8123\nmodels_dir = "weights"\n', encoding="utf-8"
    )
    s = get_settings()
    assert s.commercial_mode is False
    assert s.api_port == 8123
    assert s.models_dir == s.home / "weights"


def test_precedence_init_over_env_over_toml(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (isolated_env / "config").mkdir()
    (isolated_env / "config" / "settings.toml").write_text(
        "api_port = 1111\napi_host = '10.0.0.1'\n", encoding="utf-8"
    )
    monkeypatch.setenv("MCRAR_API_PORT", "2222")
    assert get_settings().api_port == 2222
    assert get_settings().api_host == "10.0.0.1"
    assert get_settings(api_port=3333).api_port == 3333


def test_toml_cannot_relocate_home(isolated_env: Path, tmp_path: Path) -> None:
    other = (tmp_path / "other").as_posix()
    (isolated_env / "config").mkdir()
    (isolated_env / "config" / "settings.toml").write_text(f"home = '{other}'\n", encoding="utf-8")
    assert get_settings().home == isolated_env.resolve()


def test_unknown_toml_key_is_an_error(isolated_env: Path) -> None:
    (isolated_env / "config").mkdir()
    (isolated_env / "config" / "settings.toml").write_text("typo_setting = 1\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        get_settings()


def test_missing_toml_is_fine(isolated_env: Path) -> None:
    assert not (isolated_env / "config").exists()
    assert get_settings().commercial_mode is True


def test_find_repo_root_from_package_location(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCRAR_HOME")
    root = find_repo_root()
    assert (root / "backend" / "pyproject.toml").is_file()


def test_find_repo_root_clear_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MCRAR_HOME")
    with pytest.raises(ConfigError, match="MCRAR_HOME"):
        find_repo_root(tmp_path / "nowhere" / "x.py")
