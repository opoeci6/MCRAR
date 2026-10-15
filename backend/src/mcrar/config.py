"""Settings: init args > env (MCRAR_*) > <home>/config/settings.toml > defaults.

All paths are repo-relative by default and resolved against ``home``.
There is deliberately no import-time singleton: call :func:`get_settings` (tests can pass
overrides or set ``MCRAR_HOME`` and friends via ``monkeypatch``).

The settings page edits the file through :func:`save_settings_update`: only the keys in
:data:`EDITABLE_KEYS` can be changed, the merged result is validated before anything is written,
and the file is replaced atomically, so a rejected or interrupted update never leaves a broken
file behind. :func:`env_overrides` lists the fields an ``MCRAR_*`` variable currently pins (the
file value would lose against it).
"""

from __future__ import annotations

import copy
import logging
import os
import tempfile
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import tomli_w
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

HOME_ENV_VAR = "MCRAR_HOME"
SETTINGS_FILE = Path("config") / "settings.toml"
log = logging.getLogger(__name__)
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


# Removed settings that an old settings.toml may still hold.
_LEGACY_KEYS = frozenset({"commercial_mode"})
_legacy_noted = False


class _TomlSource(TomlConfigSettingsSource):
    """TOML source that cannot relocate ``home`` (the file path itself depends on it).

    It also drops the keys in :data:`_LEGACY_KEYS`, so a settings file written by an older
    version still loads (``Settings`` forbids unknown keys); the first one seen is logged.
    """

    def __call__(self) -> dict[str, Any]:
        global _legacy_noted
        data = dict(super().__call__())
        data.pop("home", None)
        for key in _LEGACY_KEYS & data.keys():
            del data[key]
            if not _legacy_noted:
                _legacy_noted = True
                log.info("settings.toml: %s is no longer used and is ignored; delete it", key)
        return data


class SearchWeights(BaseModel):
    """Relative weight of each ranking term. Only the terms a query activates count, and the
    active weights are renormalised to sum to 1 (see :mod:`mcrar.recommend.rank`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    semantic: float = Field(0.6, ge=0)
    tags: float = Field(0.2, ge=0)
    bpm: float = Field(0.1, ge=0)
    energy: float = Field(0.1, ge=0)

    @model_validator(mode="after")
    def _some_weight(self) -> SearchWeights:
        if self.semantic + self.tags + self.bpm + self.energy <= 0:
            raise ValueError("at least one search weight must be positive")
        return self


class SearchSettings(BaseModel):
    """Search and ranking knobs (``[search]`` in settings.toml, ``MCRAR_SEARCH__*`` in the env)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pool_size: int = Field(200, ge=1)  # candidates retrieved and ranked per query
    max_per_artist: int = Field(2, ge=1)  # results per artist in one result list
    min_results: int = Field(1, ge=0)  # fewer results than this relaxes the hard filters
    # Raw top-1 cosine below which a text search is a weak match (the UI then offers a Jamendo
    # import). None: the embedder's default, ``recommend.service.WEAK_COSINE_DEFAULTS``.
    weak_cosine: float | None = Field(None, ge=0, le=1)
    weights: SearchWeights = SearchWeights()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MCRAR_", env_nested_delimiter="__", extra="forbid"
    )

    home: Path = Field(default_factory=find_repo_root)
    data_dir: Path = Path("data")
    models_dir: Path = Path("models")
    cache_dir: Path = Path(".cache")
    secrets_dir: Path = Path(".secrets")

    # Text-audio model used by `mcrar embed` (and later by search). "clap" won the M3a bake-off on
    # the user's blind ratings of game-music searches; see docs/embedder_bakeoff.md.
    default_embedder: str = "clap"
    secrets_backend: Literal["file", "keyring", "env"] = "file"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    search: SearchSettings = SearchSettings()

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


# -- editing the settings file (the settings page) ----------------------------------------------

EDITABLE_KEYS = frozenset({"default_embedder", "search"})
_ENV_PREFIX = "MCRAR_"


class _EditableSettings(BaseModel):
    """The editable subset of :class:`Settings`, used to validate an update before it is saved."""

    model_config = ConfigDict(extra="forbid")

    default_embedder: str = Field("clap", min_length=1)
    search: SearchSettings = SearchSettings()


def settings_file(home: Path) -> Path:
    return home / SETTINGS_FILE


def _deep_merge(base: dict[str, Any], update: Mapping[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in update.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        elif isinstance(value, Mapping):
            merged[key] = _deep_merge({}, value)
        else:
            merged[key] = value
    return merged


def _describe(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in err['loc']) or 'settings'}: {err['msg']}"
        for err in exc.errors(include_input=False, include_url=False)
    )


def save_settings_update(home: Path, update: Mapping[str, Any]) -> None:
    """Merge ``update`` into ``<home>/config/settings.toml`` and write it atomically.

    ``update`` holds only editable keys (``default_embedder``, ``search`` with its nested
    ``weights``); nested tables are merged key by key and every other key already in the file is
    kept, except a legacy key (:data:`_LEGACY_KEYS`), which is dropped. Raises ``ValueError``
    (file untouched) for a key that is not editable or a value that does not validate.
    """
    unknown = sorted(set(update) - EDITABLE_KEYS)
    if unknown:
        raise ValueError(f"not an editable setting: {', '.join(unknown)}")
    path = settings_file(home)
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            existing = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ValueError(f"cannot read {path}: {type(exc).__name__}") from None
    merged = _deep_merge({k: v for k, v in existing.items() if k not in _LEGACY_KEYS}, update)
    try:
        _EditableSettings.model_validate({k: v for k, v in merged.items() if k in EDITABLE_KEYS})
    except ValidationError as exc:
        raise ValueError(f"invalid settings: {_describe(exc)}") from None
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            tomli_w.dump(merged, handle)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _leaves(model: type[BaseModel], prefix: str = "") -> list[str]:
    names: list[str] = []
    for name, field in model.model_fields.items():
        inner = field.annotation
        if isinstance(inner, type) and issubclass(inner, BaseModel):
            names.extend(_leaves(inner, f"{prefix}{name}."))
        else:
            names.append(f"{prefix}{name}")
    return names


def env_overrides() -> list[str]:
    """Dotted names of the settings fields an ``MCRAR_*`` environment variable currently sets
    (``default_embedder``, ``search.pool_size``, ``search.weights.tags``), sorted.

    ``MCRAR_HOME``, ``MCRAR_SECRET_*`` and variables that name no settings field are ignored. A
    variable that sets a whole table (``MCRAR_SEARCH='{...}'``) counts for every field in it.
    """
    found: set[str] = set()
    for key in os.environ:
        if not key.upper().startswith(_ENV_PREFIX):
            continue
        parts = key[len(_ENV_PREFIX) :].lower().split("__")
        if parts[0] == "home" or parts[0].startswith("secret_"):  # location; secrets
            continue
        model: type[BaseModel] = Settings
        path: list[str] = []
        for index, part in enumerate(parts):
            field = model.model_fields.get(part)
            if field is None:
                break
            path.append(part)
            inner = field.annotation
            if isinstance(inner, type) and issubclass(inner, BaseModel):
                model = inner
                if index == len(parts) - 1:
                    found.update(_leaves(inner, ".".join(path) + "."))
            else:
                if index == len(parts) - 1:
                    found.add(".".join(path))
                break
    return sorted(found)
