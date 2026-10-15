"""The settings page: ``GET/PUT /api/settings`` and the secrets store under ``/api/secrets``.

Settings: only the keys the page may edit (licence mode, default embedder, search knobs) are
accepted, as a partial body. A change is checked (known embedder, no non-commercial embedder in
commercial mode, no field that an ``MCRAR_*`` variable pins, because the variable would win
anyway), merged into ``config/settings.toml`` with :func:`mcrar.config.save_settings_update`, and
then the settings are rebuilt from disk and environment and handed to the running
:class:`~mcrar.api.state.AppState`, so the change takes effect without a restart. One lock
serialises read-merge-write-reload.

Secrets: the list shows names and where each comes from, never a value, and there is no route that
reads one. The value-carrying ``PUT`` reads and checks the body by hand: FastAPI's own 422 body
and pydantic's error text both repeat the offending input, which here would be the secret.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, StrictBool

from mcrar.api.state import AppState, StateDep
from mcrar.config import Settings, env_overrides, get_settings, save_settings_update
from mcrar.ml import MODELS, ModelError, get_spec
from mcrar.ml.registry import is_allowed
from mcrar.secrets import SecretError, SecretStore, validate_name

router = APIRouter()

_settings_lock = threading.Lock()
READ_ONLY_FIELDS = (
    "home",
    "data_dir",
    "models_dir",
    "cache_dir",
    "secrets_dir",
    "secrets_backend",
    "api_host",
    "api_port",
)
SECRET_MAX_LENGTH = 4096
SECRET_BODY_MAX_BYTES = 64 * 1024
KNOWN_SECRETS = (
    {
        "name": "jamendo_client_id",
        "description": "Jamendo API client id: needed to search, add and stream Jamendo tracks.",
    },
)


# -- settings --------------------------------------------------------------------------------


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WeightsUpdate(_Body):
    semantic: float | None = None
    tags: float | None = None
    bpm: float | None = None
    energy: float | None = None


class SearchUpdate(_Body):
    pool_size: int | None = None
    max_per_artist: int | None = None
    min_results: int | None = None
    weights: WeightsUpdate | None = None


class SettingsUpdate(_Body):
    commercial_mode: StrictBool | None = None
    default_embedder: str | None = None
    search: SearchUpdate | None = None


def _flatten(value: dict[str, Any], prefix: str = "") -> list[str]:
    names: list[str] = []
    for key, item in value.items():
        if isinstance(item, dict):
            names.extend(_flatten(item, f"{prefix}{key}."))
        else:
            names.append(f"{prefix}{key}")
    return names


def _plain(value: Any) -> int | str:
    return value if isinstance(value, int | str) else str(value)


def settings_view(settings: Settings) -> dict[str, Any]:
    search = settings.search
    return {
        "editable": {
            "commercial_mode": settings.commercial_mode,
            "default_embedder": settings.default_embedder,
            "search": {
                "pool_size": search.pool_size,
                "max_per_artist": search.max_per_artist,
                "min_results": search.min_results,
                "weights": search.weights.model_dump(),
            },
        },
        "read_only": {name: _plain(getattr(settings, name)) for name in READ_ONLY_FIELDS},
        "overridden_by_env": env_overrides(),
        "embedders": [
            {
                "key": spec.key,
                "model_id": spec.model_id,
                "commercial_ok": spec.commercial_ok,
                "allowed": is_allowed(spec, settings),
            }
            for spec in MODELS.values()
        ],
    }


def _check_update(update: dict[str, Any], current: Settings) -> None:
    """Refuse what the file cannot change or the licence mode forbids (raises HTTPException)."""
    pinned = sorted(set(_flatten(update)) & set(env_overrides()))
    if pinned:
        raise HTTPException(
            409,
            f"{', '.join(pinned)} is set by an MCRAR_* environment variable, which overrides "
            "the settings file; unset the variable to change it here",
        )
    embedder = update.get("default_embedder", current.default_embedder)
    commercial = update.get("commercial_mode", current.commercial_mode)
    try:
        spec = get_spec(embedder)
    except ModelError as exc:
        raise HTTPException(422, str(exc)) from None
    if commercial and not spec.commercial_ok:
        if "default_embedder" in update:
            hint = "turn commercial mode off first, then select it"
        else:
            hint = "select a commercial embedder before turning commercial mode on"
        raise HTTPException(
            422,
            f"'{spec.key}' has a non-commercial licence ({spec.license}) and cannot be used "
            f"in commercial mode: {hint}",
        )


def _reload(state: AppState) -> None:
    """Rebuild the settings from disk and environment; paths and server options stay as they are
    for this run (they are read-only here and were fixed when the server started)."""
    old = state.settings
    fixed = {name: getattr(old, name) for name in READ_ONLY_FIELDS}
    state.reload_settings(get_settings(**fixed))


@router.get("/api/settings")
def read_settings(state: StateDep) -> dict[str, Any]:
    return settings_view(state.settings)


@router.put("/api/settings")
def update_settings(body: SettingsUpdate, state: StateDep) -> dict[str, Any]:
    update = body.model_dump(exclude_none=True)
    if not update:
        return settings_view(state.settings)
    with _settings_lock:
        _check_update(update, state.settings)
        save_settings_update(state.settings.home, update)  # ValueError -> 422, file untouched
        _reload(state)
        return settings_view(state.settings)


# -- secrets ---------------------------------------------------------------------------------


def _store(state: AppState) -> SecretStore:
    try:
        return SecretStore(state.settings)
    except SecretError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/api/secrets")
def list_secrets(state: StateDep) -> dict[str, Any]:
    store = _store(state)
    try:
        items = [{"name": name, "source": store.source(name)} for name in store.names()]
    except SecretError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"backend": store.backend_name, "items": items, "known": list(KNOWN_SECRETS)}


async def _read_secret_value(request: Request) -> str:
    """The ``value`` of the JSON body. Every failure message is fixed text: none repeats input."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > SECRET_BODY_MAX_BYTES:
        raise HTTPException(413, "request body too large")
    raw = await request.body()
    if len(raw) > SECRET_BODY_MAX_BYTES:
        raise HTTPException(413, "request body too large")
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if not isinstance(data, dict) or set(data) != {"value"} or not isinstance(data["value"], str):
        raise HTTPException(422, 'body must be a JSON object {"value": "<string>"}')
    value = data["value"].strip()
    if not value or len(data["value"]) > SECRET_MAX_LENGTH:
        raise HTTPException(422, f"value must be 1 to {SECRET_MAX_LENGTH} characters")
    return value


@router.put("/api/secrets/{name}", status_code=204)
async def set_secret(name: str, request: Request, state: StateDep) -> Response:
    validate_name(name)
    value = await _read_secret_value(request)
    store = _store(state)

    def save() -> None:
        try:
            store.set(name, value)
        except SecretError as exc:
            raise HTTPException(409, str(exc)) from None

    await run_in_threadpool(save)
    return Response(status_code=204)


@router.delete("/api/secrets/{name}", status_code=204)
def delete_secret(name: str, state: StateDep) -> Response:
    validate_name(name)
    store = _store(state)
    try:
        removed = store.delete(name)
    except SecretError as exc:
        raise HTTPException(409, str(exc)) from None
    if not removed:
        raise LookupError(f"secret '{name}' is not stored in the {store.backend_name} backend")
    return Response(status_code=204)
