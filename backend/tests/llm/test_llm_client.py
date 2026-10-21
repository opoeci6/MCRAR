"""``LLMClient`` (status reasons, lazy key reads, overrides, the test call) and ``LLMSettings``."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mcrar.config import (
    Settings,
    env_overrides,
    get_settings,
    save_settings_update,
)
from mcrar.llm.base import (
    NOT_SUPPORTED_TEXT,
    LLMAuthError,
    LLMInvalidReply,
    LLMNotConfigured,
    LLMNotSupported,
    LLMProvider,
    LLMTimeout,
    ModelInfo,
)
from mcrar.llm.client import LLMClient, token_budget
from mcrar.llm.presets import Preset, get_preset
from mcrar.secrets import SecretStore

KEY = "sk-FAKE-KEY-0123456789"


class StubProvider:
    def __init__(self, preset: Preset, model: str, base_url: str, key: str | None) -> None:
        self.preset, self.model, self.base_url, self.key = preset, model, base_url, key
        self.label = preset.label
        self.closed = False
        self.error: Exception | None = None
        self.calls: list[dict[str, Any]] = []

    def complete_json(self, messages, schema, *, name, max_tokens, timeout_s):  # noqa: ANN001
        self.calls.append({"name": name, "max_tokens": max_tokens, "timeout_s": timeout_s})
        if self.error:
            raise self.error
        return {"ok": True}

    def close(self) -> None:
        self.closed = True


class Factory:
    def __init__(self) -> None:
        self.built: list[StubProvider] = []
        self.error: Exception | None = None

    def __call__(self, preset: Preset, model: str, base_url: str, key: str | None) -> LLMProvider:
        provider = StubProvider(preset, model, base_url, key)
        provider.error = self.error
        self.built.append(provider)
        return provider  # type: ignore[return-value]


def make(tmp_path: Path, **llm: Any) -> tuple[LLMClient, SecretStore, Factory, Settings]:
    settings = get_settings(secrets_dir=tmp_path / "secrets", llm=llm)
    store = SecretStore(settings)
    factory = Factory()
    return LLMClient(settings, store, provider_factory=factory), store, factory, settings


# -- status ----------------------------------------------------------------------------------


def test_status_reasons_in_order(tmp_path: Path) -> None:
    client, store, _, _ = make(tmp_path)
    status = client.status()
    assert (status.enabled, status.ready, status.reason) == (False, False, "disabled")
    assert status.preset == "openai" and status.model == "gpt-6-luna" and status.kind == "openai"

    client, store, _, _ = make(tmp_path, enabled=True)
    assert client.status().reason == "missing_key"
    store.set("llm_api_key_openai", KEY)
    status = client.status()
    assert status.ready and status.reason is None
    assert status.to_dict() == {
        "enabled": True,
        "ready": True,
        "preset": "openai",
        "label": "OpenAI",
        "kind": "openai",
        "model": "gpt-6-luna",
        "reason": None,
        "rerank_top_n": 20,
    }


def test_disabled_wins_over_a_missing_model_and_a_missing_model_over_a_missing_key(
    tmp_path: Path,
) -> None:
    client, *_ = make(tmp_path, preset="custom")
    assert client.status().reason == "disabled"
    client, *_ = make(tmp_path, preset="custom", enabled=True)
    assert client.status().reason == "missing_model"
    client, *_ = make(tmp_path, preset="custom", enabled=True, model="llama3")
    status = client.status()  # a key is not needed for this preset
    assert status.ready and status.model == "llama3"


def test_status_model_is_the_saved_one_when_set(tmp_path: Path) -> None:
    client, *_ = make(tmp_path, enabled=True, preset="anthropic", model="claude-x", rerank_top_n=7)
    status = client.status()
    assert (status.model, status.kind, status.label) == (
        "claude-x",
        "anthropic",
        "Anthropic (Claude)",
    )
    assert status.rerank_top_n == 7


# -- provider --------------------------------------------------------------------------------


def test_the_key_is_read_on_every_call(tmp_path: Path) -> None:
    client, store, factory, _ = make(tmp_path, enabled=True)
    with pytest.raises(LLMNotConfigured, match="No API key is set for OpenAI"):
        client.provider()
    store.set("llm_api_key_openai", KEY)
    assert client.provider().key == KEY  # type: ignore[attr-defined]
    store.delete("llm_api_key_openai")
    with pytest.raises(LLMNotConfigured):
        client.provider()
    assert len(factory.built) == 1


def test_missing_model_for_custom(tmp_path: Path) -> None:
    client, *_ = make(tmp_path, preset="custom")
    with pytest.raises(LLMNotConfigured, match="No model is set"):
        client.provider()


def test_defaults_and_saved_values_reach_the_factory(tmp_path: Path) -> None:
    client, store, factory, _ = make(
        tmp_path, preset="deepseek", model="my-model", base_url="https://proxy.test/v1"
    )
    store.set("llm_api_key_deepseek", KEY)
    provider = client.provider()
    assert (provider.model, provider.base_url) == ("my-model", "https://proxy.test/v1")  # type: ignore[attr-defined]
    client, store, factory, _ = make(tmp_path, preset="deepseek")
    provider = client.provider()
    assert provider.model == "deepseek-flash"
    assert provider.base_url == get_preset("deepseek").base_url  # type: ignore[attr-defined]


def test_overrides_replace_the_saved_values(tmp_path: Path) -> None:
    client, store, _, _ = make(tmp_path, preset="deepseek", model="saved", enabled=False)
    store.set("llm_api_key_groq", KEY)
    provider = client.provider(preset="groq")  # works while disabled; own defaults
    assert (provider.model, provider.key) == ("openai/gpt-oss-20b", KEY)  # type: ignore[attr-defined]
    assert provider.base_url == get_preset("groq").base_url  # type: ignore[attr-defined]
    store.set("llm_api_key_deepseek", KEY)
    assert client.provider().model == "saved"
    assert client.provider(model="other").model == "other"
    assert client.provider(model="").model == "deepseek-flash"  # "" asks for the default
    assert client.provider(base_url="http://x.test").base_url == "http://x.test"  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="unknown LLM preset"):
        client.provider(preset="nope")


# -- the test call ---------------------------------------------------------------------------


def test_test_ok(tmp_path: Path) -> None:
    client, store, factory, _ = make(tmp_path, preset="deepseek")
    store.set("llm_api_key_deepseek", KEY)
    result = client.test()
    assert result["ok"] is True and result["model"] == "deepseek-flash"
    assert isinstance(result["elapsed_ms"], int | float)
    call = factory.built[0].calls[0]
    assert call["max_tokens"] == 200 and call["timeout_s"] == 10
    assert factory.built[0].closed


@pytest.mark.parametrize(
    "error",
    [
        LLMAuthError("Authentication failed (HTTP 401). Check the API key."),
        LLMTimeout("Timed out"),
        LLMInvalidReply("The model's reply was not valid JSON."),
    ],
)
def test_test_reports_llm_errors_as_safe_text(tmp_path: Path, error: Exception) -> None:
    client, store, factory, _ = make(tmp_path)
    store.set("llm_api_key_openai", KEY)
    factory.error = error
    assert client.test() == {"ok": False, "error": str(error)}
    assert factory.built[0].closed


def test_test_without_a_key(tmp_path: Path) -> None:
    client, *_ = make(tmp_path, preset="deepseek")
    assert client.test() == {"ok": False, "error": "No API key is set for DeepSeek."}


def test_the_key_never_appears_in_results_or_logs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    client, store, factory, _ = make(tmp_path)
    store.set("llm_api_key_openai", KEY)
    for result in (client.test(), client.status().to_dict()):
        assert KEY not in repr(result)
    assert KEY not in caplog.text and KEY not in repr(client)


# -- list_models -----------------------------------------------------------------------------


class ListingProvider(StubProvider):
    """A stub that can also list models."""

    models: list[ModelInfo]
    listing_error: Exception | None

    def list_models(self, *, timeout_s: float) -> list[ModelInfo]:
        self.calls.append({"timeout_s": timeout_s})
        if self.listing_error:
            raise self.listing_error
        return self.models


def listing_client(
    tmp_path: Path,
    models: list[ModelInfo] | None = None,
    error: Exception | None = None,
    **llm: Any,
) -> tuple[LLMClient, SecretStore, list[ListingProvider]]:
    settings = get_settings(secrets_dir=tmp_path / "secrets", llm=llm)
    store = SecretStore(settings)
    built: list[ListingProvider] = []

    def factory(preset: Preset, model: str, base_url: str, key: str | None) -> LLMProvider:
        provider = ListingProvider(preset, model, base_url, key)
        provider.models, provider.listing_error = models or [], error
        built.append(provider)
        return provider  # type: ignore[return-value]

    return LLMClient(settings, store, provider_factory=factory), store, built


def test_list_models_ok(tmp_path: Path) -> None:
    models = [ModelInfo("a", "Model A"), ModelInfo("b")]
    client, store, built = listing_client(tmp_path, models, preset="deepseek")
    store.set("llm_api_key_deepseek", KEY)
    assert client.list_models() == {  # the LLM is disabled: listing still works
        "ok": True,
        "preset": "deepseek",
        "models": [{"id": "a", "label": "Model A"}, {"id": "b", "label": None}],
        "default_model": "deepseek-flash",
    }
    assert built[0].calls == [{"timeout_s": 10}] and built[0].closed


def test_list_models_overrides_and_no_server_side_cache(tmp_path: Path) -> None:
    client, store, built = listing_client(tmp_path, [ModelInfo("a")], preset="deepseek")
    store.set("llm_api_key_groq", KEY)
    result = client.list_models(preset="groq", base_url="http://x.test/v1")
    assert result["ok"] and result["preset"] == "groq"
    assert (built[0].base_url, built[0].key) == ("http://x.test/v1", KEY)
    client.list_models(preset="groq")
    assert len(built) == 2


def test_list_models_without_a_key(tmp_path: Path) -> None:
    client, _, built = listing_client(tmp_path, [ModelInfo("a")])
    assert client.list_models() == {"ok": False, "error": "No API key is set for OpenAI."}
    assert built == []


def test_list_models_for_a_custom_preset_without_a_model(tmp_path: Path) -> None:
    client, _, built = listing_client(tmp_path, [ModelInfo("llama3")], preset="custom")
    result = client.list_models()
    assert result["ok"] and result["models"] == [{"id": "llama3", "label": None}]
    assert result["default_model"] == "" and built[0].model == "unset"


def test_list_models_with_a_provider_that_cannot_list(tmp_path: Path) -> None:
    client, _, factory, _ = make(tmp_path, preset="custom")
    assert client.list_models() == {"ok": False, "error": NOT_SUPPORTED_TEXT}
    assert factory.built[0].closed


@pytest.mark.parametrize(
    "error",
    [
        LLMAuthError("Authentication failed (HTTP 401). Check the API key."),
        LLMTimeout("Timed out"),
        LLMNotSupported(NOT_SUPPORTED_TEXT),
    ],
)
def test_list_models_reports_llm_errors_as_safe_text(tmp_path: Path, error: Exception) -> None:
    client, _, built = listing_client(tmp_path, error=error, preset="custom")
    assert client.list_models() == {"ok": False, "error": str(error)}
    assert built[0].closed


def test_list_models_never_shows_the_key(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    client, store, _ = listing_client(tmp_path)
    assert client.list_models()["error"] == "No API key is set for OpenAI."
    store.set("llm_api_key_openai", KEY)
    results = [client.list_models(), client.list_models(preset="custom")]
    assert all(KEY not in repr(r) for r in results) and KEY not in caplog.text


# -- settings --------------------------------------------------------------------------------


def test_llm_settings_defaults() -> None:
    llm = get_settings().llm
    assert (llm.enabled, llm.preset, llm.model, llm.base_url) == (False, "openai", "", "")
    assert (llm.parse_timeout_s, llm.rerank_timeout_s, llm.rerank_top_n) == (10, 45, 20)


@pytest.mark.parametrize(
    "bad",
    [
        {"preset": "nope"},
        {"base_url": "ftp://x"},
        {"base_url": "localhost:11434"},
        {"parse_timeout_s": 0.5},
        {"parse_timeout_s": 121},
        {"rerank_timeout_s": 0},
        {"rerank_top_n": 4},
        {"rerank_top_n": 51},
        {"model": "m" * 201},
        {"unknown": 1},
    ],
)
def test_llm_settings_validation(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        get_settings(llm=bad)


def test_llm_settings_strip_and_accept_valid_values() -> None:
    llm = get_settings(
        llm={
            "preset": "custom",
            "model": " llama3 ",
            "base_url": " http://h:1/v1 ",
            "rerank_top_n": 5,
        }
    ).llm
    assert (llm.model, llm.base_url, llm.rerank_top_n) == ("llama3", "http://h:1/v1", 5)


def test_llm_table_loads_from_toml(isolated_env: Path) -> None:
    (isolated_env / "config").mkdir()
    (isolated_env / "config" / "settings.toml").write_text(
        '[llm]\nenabled = true\npreset = "groq"\nmodel = "m"\nparse_timeout_s = 3\n',
        encoding="utf-8",
    )
    llm = get_settings().llm
    assert (llm.enabled, llm.preset, llm.model, llm.parse_timeout_s) == (True, "groq", "m", 3)


def test_llm_settings_can_be_saved_and_are_validated(isolated_env: Path) -> None:
    save_settings_update(isolated_env, {"llm": {"enabled": True, "preset": "zai"}})
    assert get_settings().llm.preset == "zai"
    with pytest.raises(ValueError, match="invalid settings"):
        save_settings_update(isolated_env, {"llm": {"preset": "nope"}})
    assert get_settings().llm.preset == "zai"


def test_env_variables_pin_llm_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCRAR_LLM__MODEL", "from-env")
    assert get_settings().llm.model == "from-env"
    assert env_overrides() == ["llm.model"]


def test_example_settings_file_loads(isolated_env: Path) -> None:
    example = Path(__file__).resolve().parents[3] / "config" / "settings.example.toml"
    (isolated_env / "config").mkdir()
    (isolated_env / "config" / "settings.toml").write_text(
        example.read_text(encoding="utf-8"), encoding="utf-8"
    )
    assert get_settings().llm.enabled is False


def test_token_budget_doubles_for_max_completion_tokens_presets() -> None:
    assert token_budget(get_preset("openai"), 600) == 1200
    assert token_budget(get_preset("groq"), 600) == 600
