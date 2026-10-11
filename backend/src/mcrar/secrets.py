"""SecretStore: API keys and similar secrets, never exposed in repr, logs or exceptions.

Lookup order: environment variable ``MCRAR_SECRET_<NAME_UPPER>`` always wins, then the
configured backend (``file`` | ``keyring`` | ``env``).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import tomllib
from pathlib import Path
from typing import Any

import tomli_w

from mcrar.config import Settings, get_settings

ENV_PREFIX = "MCRAR_SECRET_"
KEYRING_SERVICE = "mcrar"
_KEYRING_INDEX = "@index"  # not a legal secret name, so it cannot collide
_NAME_RE = re.compile(r"^[a-z0-9_]+$")


class SecretError(RuntimeError):
    """A secret operation failed. Messages never contain secret values."""


def validate_name(name: str) -> str:
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        raise ValueError("Invalid secret name: use only lowercase letters, digits and underscores")
    return name


def env_var_for(name: str) -> str:
    return ENV_PREFIX + validate_name(name).upper()


def _env_names() -> list[str]:
    found = []
    for key, value in os.environ.items():
        if key.upper().startswith(ENV_PREFIX) and value:
            candidate = key[len(ENV_PREFIX) :].lower()
            if _NAME_RE.fullmatch(candidate):
                found.append(candidate)
    return found


class _FileBackend:
    label = "file"

    def __init__(self, path: Path) -> None:
        self.path = path

    def _read(self) -> dict[str, str]:
        if not self.path.is_file():
            return {}
        try:
            data = tomllib.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            reason = type(exc).__name__
            raise SecretError(f"Cannot read secrets file {self.path}: {reason}") from None
        return {k: v for k, v in data.items() if isinstance(v, str)}

    def _write(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".secrets-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as handle:
                tomli_w.dump(data, handle)
            if os.name == "posix":
                os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def get(self, name: str) -> str | None:
        return self._read().get(name)

    def set(self, name: str, value: str) -> None:
        data = self._read()
        data[name] = value
        self._write(data)

    def delete(self, name: str) -> bool:
        data = self._read()
        if name not in data:
            return False
        del data[name]
        self._write(data)
        return True

    def names(self) -> list[str]:
        return sorted(self._read())


class _KeyringBackend:
    label = "keyring"

    def __init__(self) -> None:
        try:
            import keyring  # noqa: PLC0415 - lazy on purpose: keyring is an optional extra
        except ImportError:
            raise SecretError(
                "The 'keyring' secrets backend needs the optional 'keyring' package. "
                "Install it with: uv sync --extra keyring (inside backend/). "
                "Note: it stores secrets in the OS credential store (Windows Credential Manager)."
            ) from None
        self._kr: Any = keyring

    def _names(self) -> set[str]:
        raw = self._kr.get_password(KEYRING_SERVICE, _KEYRING_INDEX)
        if not raw:
            return set()
        try:
            return {n for n in json.loads(raw) if isinstance(n, str)}
        except ValueError:
            return set()

    def _save_names(self, names: set[str]) -> None:
        self._kr.set_password(KEYRING_SERVICE, _KEYRING_INDEX, json.dumps(sorted(names)))

    def get(self, name: str) -> str | None:
        return self._kr.get_password(KEYRING_SERVICE, name)

    def set(self, name: str, value: str) -> None:
        self._kr.set_password(KEYRING_SERVICE, name, value)
        self._save_names(self._names() | {name})

    def delete(self, name: str) -> bool:
        if self._kr.get_password(KEYRING_SERVICE, name) is None:
            return False
        self._kr.delete_password(KEYRING_SERVICE, name)
        self._save_names(self._names() - {name})
        return True

    def names(self) -> list[str]:
        return sorted(self._names())


class _EnvBackend:
    """Read-only: values come only from MCRAR_SECRET_* (handled by SecretStore)."""

    label = "env"

    def get(self, name: str) -> str | None:
        return None

    def set(self, name: str, value: str) -> None:
        raise SecretError(
            "The 'env' secrets backend is read-only. Set the environment variable "
            f"{env_var_for(name)} instead."
        )

    def delete(self, name: str) -> bool:
        raise SecretError("The 'env' secrets backend is read-only. Unset the environment variable.")

    def names(self) -> list[str]:
        return []


class SecretStore:
    def __init__(self, settings: Settings | None = None, backend: str | None = None) -> None:
        self._settings = settings or get_settings()
        self.backend_name = backend or self._settings.secrets_backend
        if self.backend_name == "file":
            self._backend: Any = _FileBackend(self._settings.secrets_dir / "secrets.toml")
        elif self.backend_name == "keyring":
            self._backend = _KeyringBackend()
        elif self.backend_name == "env":
            self._backend = _EnvBackend()
        else:
            raise ValueError(f"Unknown secrets backend: {self.backend_name!r}")

    def __repr__(self) -> str:
        return f"SecretStore(backend={self.backend_name!r})"

    @staticmethod
    def _env_value(name: str) -> str | None:
        return os.environ.get(env_var_for(name)) or None

    def get(self, name: str) -> str | None:
        validate_name(name)
        env_value = self._env_value(name)
        if env_value is not None:
            return env_value
        return self._backend.get(name)

    def set(self, name: str, value: str) -> None:
        validate_name(name)
        if not isinstance(value, str) or not value:
            raise ValueError("Secret value must be a non-empty string")
        self._backend.set(name, value)

    def delete(self, name: str) -> bool:
        """Remove the secret from the backend. Returns False if it was not stored there."""
        validate_name(name)
        return bool(self._backend.delete(name))

    def names(self) -> list[str]:
        return sorted(set(self._backend.names()) | set(_env_names()))

    def source(self, name: str) -> str | None:
        """Where get(name) would read from: 'env', the backend label, or None if unset."""
        validate_name(name)
        if self._env_value(name) is not None:
            return "env"
        if self._backend.get(name) is not None:
            return self._backend.label
        return None
