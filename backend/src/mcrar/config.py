"""Settings: init args > env (MCRAR_*) > <home>/config/settings.toml > defaults.

All paths are repo-relative by default and resolved against ``home``.
There is deliberately no import-time singleton: call :func:`get_settings` (tests can pass
overrides or set ``MCRAR_HOME`` and friends via ``monkeypatch``).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

HOME_ENV_VAR = "MCRAR_HOME"
SETTINGS_FILE = Path("config") / "settings.toml"
_PATH_FIELDS = ("data_dir", "models_dir", "cache_dir", "secrets_dir")


class ConfigError(RuntimeError):
    """Raised when the configuration cannot be resolved."""


def find_repo_root(start: Path | None = None) -> Path:
    """Return MCRAR_HOME, else the nearest ancestor containing backend/pyproject.toml."""
    env_home = os.environ.get(HOME_ENV_VAR)
    if env_home:
        return Path(env_home).expanduser().resolve()
    here = (start or Path(__file__)).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "backend" / "pyproject.toml").is_file():
            return candidate
    raise ConfigError(
        f"Cannot locate the MCRAR repo root: {HOME_ENV_VAR} is not set and no ancestor of "
        f"{here} contains backend/pyproject.toml. Set {HOME_ENV_VAR} to the repository folder "
        "(scripts/dev-env.ps1 or scripts/dev-env.sh does this)."
    )


class _TomlSource(TomlConfigSettingsSource):
    """TOML source that cannot relocate ``home`` (the file path itself depends on it)."""

    def __call__(self) -> dict[str, Any]:
        data = dict(super().__call__())
        data.pop("home", None)
        return data


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MCRAR_", extra="forbid")

    home: Path = Field(default_factory=find_repo_root)
    data_dir: Path = Path("data")
    models_dir: Path = Path("models")
    cache_dir: Path = Path(".cache")
    secrets_dir: Path = Path(".secrets")

    # True: only commercially usable models and data are allowed; non-commercial parts are opt-in.
    commercial_mode: bool = True
    # Text-audio model used by `mcrar embed` (and later by search). "clap" won the M3a bake-off on
    # the user's blind ratings of game-music searches; see docs/embedder_bakeoff.md.
    default_embedder: str = "clap"
    secrets_backend: Literal["file", "keyring", "env"] = "file"
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        init_home = init_settings().get("home")
        home = Path(init_home).expanduser().resolve() if init_home else find_repo_root()
        toml_source = _TomlSource(settings_cls, toml_file=home / SETTINGS_FILE)
        return (init_settings, env_settings, toml_source)

    @model_validator(mode="after")
    def _resolve_paths(self) -> Settings:
        self.home = self.home.expanduser().resolve()
        for name in _PATH_FIELDS:
            path = getattr(self, name).expanduser()
            setattr(self, name, path if path.is_absolute() else self.home / path)
        return self


def get_settings(**overrides: Any) -> Settings:
    """Build a fresh Settings object (no caching, so tests and callers can override)."""
    return Settings(**overrides)
