"""The built-in presets and the JSON reply reader."""

from __future__ import annotations

import pytest

from mcrar.llm import PRESET_IDS, PRESETS, get_preset
from mcrar.llm.base import LLMInvalidReply
from mcrar.llm.jsonutil import parse_json_reply
from mcrar.llm.presets import is_chat_model_id
from mcrar.secrets import validate_name


def test_ids_are_unique_and_in_display_order() -> None:
    assert PRESET_IDS == (
        "openai",
        "deepseek",
        "siliconflow",
        "zai",
        "openrouter",
        "gemini",
        "groq",
        "anthropic",
        "custom",
    )
    assert len(set(PRESET_IDS)) == len(PRESETS)


def test_every_preset_is_well_formed() -> None:
    for preset in PRESETS:
        assert preset.kind == ("anthropic" if preset.id == "anthropic" else "openai")
        assert preset.json_mode in ("json_schema", "json_object", "none")
        assert preset.token_param in ("max_tokens", "max_completion_tokens")
        assert preset.base_url.startswith(("http://", "https://"))
        assert preset.key_secret == f"llm_api_key_{preset.id}"
        validate_name(preset.key_secret)  # a legal secret name
        if preset.id != "custom":
            assert (
                preset.key_required
                and preset.default_model
                and preset.docs_url.startswith("https://")
            )


def test_custom_preset_needs_no_key_and_has_no_default_model() -> None:
    custom = get_preset("custom")
    assert not custom.key_required and custom.default_model == ""
    assert get_preset("openai").token_param == "max_completion_tokens"


@pytest.mark.parametrize(
    ("model_id", "openai_shows", "others_show"),
    [
        ("gpt-6-luna", True, True),
        ("gpt-4o-search-preview", True, True),
        ("text-embedding-3-small", False, False),
        ("gpt-4o-mini-tts", False, False),
        ("davinci-002", False, True),
        ("gpt-3.5-turbo-instruct", False, True),
        ("gpt-5.1-codex", False, True),
        ("gpt-5-pro", False, True),
        ("sora-2", False, True),
        ("Qwen/Qwen2.5-7B-Instruct", False, True),
        ("gemini-3.8-pro", False, True),
    ],
)
def test_model_list_filter(model_id: str, openai_shows: bool, others_show: bool) -> None:
    assert is_chat_model_id(model_id, get_preset("openai").hide_model_patterns) is openai_shows
    for other in ("siliconflow", "gemini", "openrouter"):
        assert is_chat_model_id(model_id, get_preset(other).hide_model_patterns) is others_show


def test_unknown_preset() -> None:
    with pytest.raises(ValueError, match="unknown LLM preset 'nope'"):
        get_preset("nope")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('```\n{"a": 1}\n```', {"a": 1}),
        ('  \n{"a": {"b": [1, 2]}}\n ', {"a": {"b": [1, 2]}}),
        ('Sure, here it is:\n{"a": {"b": 2}}\nAnything else?', {"a": {"b": 2}}),
    ],
)
def test_parse_json_reply(text: str, expected: dict) -> None:
    assert parse_json_reply(text) == expected


@pytest.mark.parametrize("text", [None, "", "   ", "no json", "{", '{"a": }', "[1]", "3", '"x"'])
def test_parse_json_reply_rejects(text: str | None) -> None:
    with pytest.raises(LLMInvalidReply):
        parse_json_reply(text)
