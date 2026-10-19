"""The built-in LLM providers: what the settings page offers and how each one is called.

Most services speak the OpenAI chat-completions dialect (``kind="openai"``); Anthropic has its
own SDK. The values were checked against each provider's documentation on 2026-10-19.
``extra_body`` holds model-specific flags that keep reasoning cheap (query parsing needs speed,
not thought); they are sent only for ``default_model`` because another model may reject them.
This module imports nothing from ``mcrar``, so the settings can validate preset ids.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

JsonMode = Literal["json_schema", "json_object", "none"]
TokenParam = Literal["max_tokens", "max_completion_tokens"]


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    kind: Literal["openai", "anthropic"]
    base_url: str
    default_model: str
    json_mode: JsonMode
    token_param: TokenParam
    key_required: bool
    docs_url: str
    extra_body: Mapping[str, object] = field(default_factory=dict)

    @property
    def key_secret(self) -> str:
        return f"llm_api_key_{self.id}"


def _openai(
    id: str,
    label: str,
    base_url: str,
    default_model: str,
    docs_url: str,
    *,
    json_mode: JsonMode,
    extra_body: Mapping[str, object],
    token_param: TokenParam = "max_tokens",
) -> Preset:
    return Preset(
        id=id,
        label=label,
        kind="openai",
        base_url=base_url,
        default_model=default_model,
        json_mode=json_mode,
        token_param=token_param,
        key_required=True,
        docs_url=docs_url,
        extra_body=extra_body,
    )


PRESETS: tuple[Preset, ...] = (
    _openai(
        "openai",
        "OpenAI",
        "https://api.openai.com/v1",
        "gpt-6-luna",  # the owner's choice (2026-10-19): cheap, and more capable than gpt-5-nano
        "https://platform.openai.com/api-keys",
        json_mode="json_schema",
        token_param="max_completion_tokens",
        extra_body={"reasoning_effort": "none"},  # gpt-6-luna has no "minimal"
    ),
    _openai(
        "deepseek",
        "DeepSeek",
        "https://api.deepseek.com",
        "deepseek-flash",
        "https://platform.deepseek.com/api_keys",
        json_mode="json_object",
        extra_body={"thinking": {"type": "disabled"}},
    ),
    _openai(
        "siliconflow",
        "SiliconFlow",
        "https://api.siliconflow.com/v1",
        "deepseek-ai/DeepSeek-V3.2",
        "https://cloud.siliconflow.com/account/ak",
        json_mode="json_object",
        extra_body={"enable_thinking": False},
    ),
    _openai(
        "zai",
        "Z.AI (GLM)",
        "https://api.z.ai/api/paas/v4",
        "glm-5.3-flash",  # the owner's choice (2026-10-19): cheaper than glm-5.2
        "https://z.ai/manage-apikey/apikey-list",
        json_mode="json_object",
        # GLM-5.3 models always think: sending thinking "disabled" is an error for them.
        extra_body={},
    ),
    _openai(
        "openrouter",
        "OpenRouter",
        "https://openrouter.ai/api/v1",
        "openai/gpt-5-nano",
        "https://openrouter.ai/keys",
        json_mode="json_schema",
        extra_body={},
    ),
    _openai(
        "gemini",
        "Google Gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "gemini-3.8-flash",
        "https://aistudio.google.com/apikey",
        json_mode="json_schema",
        extra_body={"reasoning_effort": "low"},
    ),
    _openai(
        "groq",
        "Groq",
        "https://api.groq.com/openai/v1",
        "openai/gpt-oss-20b",
        "https://console.groq.com/keys",
        json_mode="json_schema",
        extra_body={"reasoning_effort": "low"},
    ),
    Preset(
        id="anthropic",
        label="Anthropic (Claude)",
        kind="anthropic",
        base_url="https://api.anthropic.com",
        default_model="claude-haiku-5-5",
        json_mode="json_schema",
        token_param="max_tokens",
        key_required=True,
        docs_url="https://console.anthropic.com/settings/keys",
    ),
    Preset(
        id="custom",
        label="Other OpenAI-compatible (Ollama, LM Studio, …)",
        kind="openai",
        base_url="http://localhost:11434/v1",
        default_model="",  # the user must set a model
        json_mode="json_object",
        token_param="max_tokens",
        key_required=False,
        docs_url="",
    ),
)
PRESET_IDS = tuple(p.id for p in PRESETS)


def get_preset(preset_id: str) -> Preset:
    for preset in PRESETS:
        if preset.id == preset_id:
            return preset
    raise ValueError(f"unknown LLM preset '{preset_id}'; choose from: {', '.join(PRESET_IDS)}")
