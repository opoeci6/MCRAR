import os
import sys
from pathlib import Path

import pytest

from mcrar.config import get_settings
from mcrar.secrets import SecretError, SecretStore

VALUE = "s3cr3t-value-123"


def make_store(backend: str | None = None) -> SecretStore:
    return SecretStore(get_settings(), backend=backend)


def test_file_round_trip(isolated_env: Path) -> None:
    store = make_store()
    assert store.get("jamendo_client_id") is None
    store.set("jamendo_client_id", VALUE)
    assert store.get("jamendo_client_id") == VALUE
    assert store.names() == ["jamendo_client_id"]
    assert store.source("jamendo_client_id") == "file"
    assert (isolated_env / ".secrets" / "secrets.toml").is_file()
    # a new store instance reads the same file
    assert make_store().get("jamendo_client_id") == VALUE
    assert store.delete("jamendo_client_id") is True
    assert store.get("jamendo_client_id") is None
    assert store.delete("jamendo_client_id") is False


@pytest.mark.skipif(os.name != "posix", reason="chmod 600 is POSIX only")
def test_file_is_private_on_posix(isolated_env: Path) -> None:
    make_store().set("a", VALUE)
    mode = (isolated_env / ".secrets" / "secrets.toml").stat().st_mode & 0o777
    assert mode == 0o600


def test_env_wins_over_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    store = make_store()
    store.set("spotify_secret", "from-file")
    monkeypatch.setenv("MCRAR_SECRET_SPOTIFY_SECRET", "from-env")
    assert store.get("spotify_secret") == "from-env"
    assert store.source("spotify_secret") == "env"
    assert store.names() == ["spotify_secret"]


def test_env_only_secret_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCRAR_SECRET_OPENAI_API_KEY", VALUE)
    store = make_store()
    assert store.get("openai_api_key") == VALUE
    assert store.names() == ["openai_api_key"]


@pytest.mark.parametrize("bad", ["", "Upper", "with-dash", "has space", "dot.name", "../x", "é"])
def test_invalid_names_rejected(bad: str) -> None:
    store = make_store()
    for call in (
        lambda: store.get(bad),
        lambda: store.set(bad, VALUE),
        lambda: store.delete(bad),
    ):
        with pytest.raises(ValueError):
            call()


def test_env_backend_is_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    store = make_store("env")
    with pytest.raises(SecretError, match="MCRAR_SECRET_API_KEY"):
        store.set("api_key", VALUE)
    monkeypatch.setenv("MCRAR_SECRET_API_KEY", VALUE)
    assert store.get("api_key") == VALUE
    assert store.names() == ["api_key"]


def test_missing_keyring_gives_helpful_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "keyring", None)  # makes `import keyring` raise ImportError
    with pytest.raises(SecretError, match="keyring"):
        make_store("keyring")


def test_values_not_in_repr_names_or_errors(isolated_env: Path) -> None:
    store = make_store()
    store.set("token", VALUE)
    assert VALUE not in repr(store)
    assert VALUE not in str(store.names())
    assert VALUE not in repr(get_settings())
    (isolated_env / ".secrets" / "secrets.toml").write_text(f"broken = {VALUE}\n", encoding="utf-8")
    with pytest.raises(SecretError) as excinfo:
        store.get("token")
    assert VALUE not in str(excinfo.value)


def test_empty_value_rejected() -> None:
    with pytest.raises(ValueError):
        make_store().set("token", "")
