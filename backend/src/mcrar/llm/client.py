"""``LLMClient``: the saved LLM settings plus the API key, turned into a ready provider.

The key is read from the secret store on every call, so a key saved on the settings page works
without a restart. ``status`` says whether the LLM is usable and, when not, why (``disabled``,
``missing_model``, ``missing_key``, in that order). ``provider`` builds a provider for one use
(the caller closes it); its arguments override the saved preset, model and base URL, which is how
the settings page tests a form before saving it. An empty model or base URL means the preset's.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Literal

from mcrar.llm.base import LLMError, LLMNotConfigured, LLMProvider
from mcrar.llm.presets import Preset, get_preset
from mcrar.secrets import SecretError

if TYPE_CHECKING:
    from mcrar.config import Settings
    from mcrar.secrets import SecretStore

ProviderFactory = Callable[[Preset, str, str, str | None], LLMProvider]
Reason = Literal["disabled", "missing_model", "missing_key"]
TEST_MAX_TOKENS = 200  # reasoning models spend some of the budget before they answer
TEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class LLMStatus:
    enabled: bool
    ready: bool
    preset: str
    label: str
    kind: str
    model: str  # the model actually used: the preset's default when none is set
    reason: Reason | None
    rerank_top_n: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Resolved:
    """The preset, model and base URL a call would use."""

    preset: Preset
    model: str
    base_url: str


def default_provider_factory(
    preset: Preset, model: str, base_url: str, api_key: str | None
) -> LLMProvider:
    if preset.kind == "anthropic":
        from mcrar.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(model=model, base_url=base_url, api_key=api_key or "")
    from mcrar.llm.openai_compat import OpenAICompatProvider

    return OpenAICompatProvider(preset, model=model, base_url=base_url, api_key=api_key)


class LLMClient:
    def __init__(
        self,
        settings: Settings,
        secrets: SecretStore | None,
        *,
        provider_factory: ProviderFactory | None = None,
    ) -> None:
        self._settings = settings
        self._secrets = secrets
        self._factory = provider_factory or default_provider_factory

    @property
    def settings(self) -> Settings:
        return self._settings

    def _key(self, preset: Preset) -> str | None:
        if self._secrets is None:
            return None
        try:
            return self._secrets.get(preset.key_secret) or None
        except SecretError:
            return None

    def resolve(
        self, *, preset: str | None = None, model: str | None = None, base_url: str | None = None
    ) -> Resolved:
        """The saved settings with the given overrides applied. Saved model and base URL belong
        to the saved preset, so another preset starts from its own defaults."""
        saved = self._settings.llm
        chosen = get_preset(preset or saved.preset)
        same = chosen.id == saved.preset
        use_model = model if model is not None else (saved.model if same else "")
        use_url = base_url if base_url is not None else (saved.base_url if same else "")
        return Resolved(
            chosen,
            use_model.strip() or chosen.default_model,
            use_url.strip() or chosen.base_url,
        )

    def status(self) -> LLMStatus:
        llm = self._settings.llm
        resolved = self.resolve()
        preset = resolved.preset
        reason: Reason | None = None
        if not llm.enabled:
            reason = "disabled"
        elif not resolved.model:
            reason = "missing_model"
        elif preset.key_required and self._key(preset) is None:
            reason = "missing_key"
        return LLMStatus(
            enabled=llm.enabled,
            ready=reason is None,
            preset=preset.id,
            label=preset.label,
            kind=preset.kind,
            model=resolved.model,
            reason=reason,
            rerank_top_n=llm.rerank_top_n,
        )

    def provider(
        self, *, preset: str | None = None, model: str | None = None, base_url: str | None = None
    ) -> LLMProvider:
        """A provider for one use (the caller closes it). Raises :class:`LLMNotConfigured` when
        the model or a required key is missing; the preset must be a known id (ValueError)."""
        resolved = self.resolve(preset=preset, model=model, base_url=base_url)
        chosen = resolved.preset
        if not resolved.model:
            raise LLMNotConfigured(f"No model is set for {chosen.label}. Choose one in Settings.")
        key = self._key(chosen)
        if chosen.key_required and key is None:
            raise LLMNotConfigured(f"No API key is set for {chosen.label}.")
        return self._factory(chosen, resolved.model, resolved.base_url, key)

    def test(
        self, *, preset: str | None = None, model: str | None = None, base_url: str | None = None
    ) -> dict[str, Any]:
        """Send a tiny request. ``{"ok": true, "model", "elapsed_ms"}`` or ``{"ok": false,
        "error"}`` (safe text). Works while the LLM is disabled."""
        started = time.perf_counter()
        try:
            provider = self.provider(preset=preset, model=model, base_url=base_url)
            try:
                provider.complete_json(
                    [
                        {"role": "system", "content": "You are a connection test."},
                        {"role": "user", "content": 'Reply with {"ok": true}'},
                    ],
                    TEST_SCHEMA,
                    name="connection_test",
                    max_tokens=TEST_MAX_TOKENS,
                    timeout_s=self._settings.llm.parse_timeout_s,
                )
            finally:
                provider.close()
        except LLMError as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "model": provider.model,
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0),
        }


def token_budget(preset: Preset, base: int) -> int:
    """``base`` output tokens, doubled for presets that bill reasoning inside the output limit
    (``max_completion_tokens``), which otherwise run out before the JSON starts."""
    return base * 2 if preset.token_param == "max_completion_tokens" else base
