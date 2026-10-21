"""The OpenAI-compatible provider over a mocked transport: requests, replies, errors, JSON modes."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from mcrar.llm import openai_compat
from mcrar.llm.base import (
    LLMAuthError,
    LLMInvalidReply,
    LLMNotSupported,
    LLMRateLimited,
    LLMRequestError,
    LLMTimeout,
)
from mcrar.llm.openai_compat import OpenAICompatProvider
from mcrar.llm.presets import get_preset

KEY = "sk-FAKE-KEY-0123456789"
SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}
MESSAGES: list[Any] = [
    {"role": "system", "content": "You are a test."},
    {"role": "user", "content": "hello"},
]


@pytest.fixture(autouse=True)
def _forget_modes() -> None:
    openai_compat._modes.clear()


def chat(content: str | None, *, finish: str = "stop", **message: Any) -> httpx.Response:
    body = {
        "choices": [
            {
                "message": {"role": "assistant", "content": content, **message},
                "finish_reason": finish,
            }
        ]
    }
    return httpx.Response(200, json=body)


class Recorder:
    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def body(self, n: int = 0) -> dict[str, Any]:
        return json.loads(self.requests[n].content)


def make(
    handler: Callable[[httpx.Request], httpx.Response],
    preset_id: str = "openai",
    *,
    model: str | None = None,
    key: str | None = KEY,
    base_url: str | None = None,
) -> OpenAICompatProvider:
    preset = get_preset(preset_id)
    return OpenAICompatProvider(
        preset,
        model=preset.default_model if model is None else model,
        base_url=base_url or preset.base_url,
        api_key=key,
        transport=httpx.MockTransport(handler),
    )


def call(provider: OpenAICompatProvider, **kw: Any) -> dict[str, Any]:
    kw.setdefault("name", "test")
    kw.setdefault("max_tokens", 100)
    kw.setdefault("timeout_s", 5.0)
    return provider.complete_json(list(MESSAGES), SCHEMA, **kw)


def test_valid_reply_and_request_shape() -> None:
    rec = Recorder(chat('{"ok": true}'))
    assert call(make(rec)) == {"ok": True}
    request = rec.requests[0]
    assert str(request.url) == "https://api.openai.com/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert request.headers["content-type"] == "application/json"
    body = rec.body()
    assert body["model"] == "gpt-6-luna"
    assert body["max_completion_tokens"] == 100 and "max_tokens" not in body
    assert body["reasoning_effort"] == "none"
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "test", "strict": True, "schema": SCHEMA},
    }
    system = body["messages"][0]
    assert system["role"] == "system" and system["content"].startswith("You are a test.")
    assert "JSON schema" in system["content"] and '"ok":{"type":"boolean"}' in system["content"]
    assert body["messages"][1] == {"role": "user", "content": "hello"}
    assert MESSAGES[0]["content"] == "You are a test."  # the caller's messages are not changed


def test_trailing_slash_in_base_url_and_max_tokens_param() -> None:
    rec = Recorder(chat('{"ok": true}'))
    call(make(rec, "groq", base_url="https://example.test/v1/"))
    assert str(rec.requests[0].url) == "https://example.test/v1/chat/completions"
    assert rec.body()["max_tokens"] == 100


def test_json_object_mode_and_missing_system_message() -> None:
    rec = Recorder(chat('{"ok": true}'))
    provider = make(rec, "deepseek")
    provider.complete_json(
        [{"role": "user", "content": "hi"}], SCHEMA, name="t", max_tokens=9, timeout_s=3
    )
    body = rec.body()
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0]["role"] == "system" and "JSON" in body["messages"][0]["content"]
    assert body["thinking"] == {"type": "disabled"}


def test_no_authorization_header_without_a_key() -> None:
    rec = Recorder(chat('{"ok": true}'))
    call(make(rec, "custom", model="llama3", key=None))
    assert "authorization" not in rec.requests[0].headers
    assert str(rec.requests[0].url) == "http://localhost:11434/v1/chat/completions"


def test_extra_body_only_for_the_default_model() -> None:
    rec = Recorder(chat('{"ok": true}'))
    call(make(rec, "gemini"))
    assert rec.body()["reasoning_effort"] == "low"
    call(make(rec, "gemini", model="some-other-model"))
    assert "reasoning_effort" not in rec.body(1)


@pytest.mark.parametrize(
    "content",
    [
        '```json\n{"ok": true}\n```',
        'Sure! Here you go: {"ok": true} Hope it helps.',
        ' {"ok": true}\n',
    ],
)
def test_fenced_and_prose_wrapped_json(content: str) -> None:
    assert call(make(Recorder(chat(content)))) == {"ok": True}


@pytest.mark.parametrize(
    "content", ["not json at all", '{"ok": ', "[1, 2]", '"text"', "", None, "   "]
)
def test_unusable_reply_is_invalid(content: str | None) -> None:
    with pytest.raises(LLMInvalidReply):
        call(make(Recorder(chat(content))))


def test_cut_off_reply() -> None:
    with pytest.raises(LLMInvalidReply, match="cut off"):
        call(make(Recorder(chat('{"ok": tr', finish="length"))))


def test_refusal() -> None:
    with pytest.raises(LLMInvalidReply, match="refused"):
        call(make(Recorder(chat(None, refusal="I cannot help with that."))))


def test_unexpected_reply_shapes() -> None:
    for response in (
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"error": "x"}),
        httpx.Response(200, text="<html>"),
    ):
        with pytest.raises(LLMInvalidReply):
            call(make(Recorder(response)))


@pytest.mark.parametrize(
    ("status", "error", "text"),
    [
        (401, LLMAuthError, "HTTP 401"),
        (403, LLMAuthError, "HTTP 403"),
        (404, LLMRequestError, "not found (HTTP 404)"),
        (429, LLMRateLimited, "429"),
        (500, LLMRequestError, "HTTP 500"),
        (302, LLMRequestError, "HTTP 302"),
    ],
)
def test_status_mapping_never_shows_the_body(status: int, error: type, text: str) -> None:
    body = f"upstream said: key {KEY} is bad; request id abc"
    with pytest.raises(error) as info:
        call(make(Recorder(httpx.Response(status, text=body))))
    assert text in str(info.value)
    assert KEY not in str(info.value) and "upstream" not in str(info.value)


def test_timeout_and_connection_failures() -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions?key=" + KEY)
    with pytest.raises(LLMTimeout, match="Timed out after 5 s") as info:
        call(make(Recorder(httpx.ReadTimeout("slow", request=request))))
    assert info.value.__cause__ is None and info.value.__context__ is None
    with pytest.raises(LLMRequestError, match="Could not reach OpenAI") as info:
        call(make(Recorder(httpx.ConnectError("refused", request=request))))
    assert info.value.__cause__ is None and info.value.__context__ is None
    assert KEY not in str(info.value)


def test_a_400_about_the_format_steps_down_and_is_remembered() -> None:
    complaint = httpx.Response(400, json={"error": {"message": "response_format not supported"}})
    rec = Recorder(complaint, chat('{"ok": true}'))
    provider = make(rec, "openrouter")
    assert call(provider) == {"ok": True}
    assert rec.body(0)["response_format"]["type"] == "json_schema"
    assert rec.body(1)["response_format"] == {"type": "json_object"}
    # the next call starts at the mode that worked
    rec.responses = [chat('{"ok": true}')]
    call(provider)
    assert len(rec.requests) == 3
    assert rec.body(2)["response_format"] == {"type": "json_object"}
    # ... also from a new provider for the same endpoint and model
    call(make(rec, "openrouter"))
    assert rec.body(3)["response_format"] == {"type": "json_object"}


def test_step_down_can_end_with_no_json_mode() -> None:
    complaint = httpx.Response(400, text="json_schema is not allowed")
    also = httpx.Response(400, text="unsupported response_format")
    rec = Recorder(complaint, also, chat('{"ok": true}'))
    assert call(make(rec, "openrouter")) == {"ok": True}
    assert "response_format" not in rec.body(2)


def test_other_400_is_not_retried() -> None:
    rec = Recorder(httpx.Response(400, text="context length exceeded"))
    with pytest.raises(LLMRequestError, match="HTTP 400"):
        call(make(rec))
    assert len(rec.requests) == 1


def test_a_400_with_no_mode_left_fails() -> None:
    rec = Recorder(httpx.Response(400, text="bad response_format"))
    provider = make(rec, "custom", model="m")
    with pytest.raises(LLMRequestError, match="HTTP 400"):
        call(provider)
    assert len(rec.requests) == 2  # json_object, then none


def test_the_key_is_not_in_repr_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    provider = make(Recorder(httpx.Response(401, text=KEY)))
    assert KEY not in repr(provider)
    with pytest.raises(LLMAuthError) as info:
        call(provider)
    provider.close()
    assert KEY not in str(info.value) and KEY not in repr(info.value)
    assert KEY not in caplog.text


# -- list_models -----------------------------------------------------------------------------


def models_reply(*ids: Any) -> httpx.Response:
    return httpx.Response(200, json={"object": "list", "data": [{"id": i} for i in ids]})


def listed(provider: OpenAICompatProvider) -> list[str]:
    return [m.id for m in provider.list_models(timeout_s=5.0)]


def test_models_are_parsed_deduped_and_sorted_case_insensitively() -> None:
    rec = Recorder(models_reply("gpt-b", "GPT-a", "gpt-b", "gpt-c", "o1"))
    provider = make(rec)
    assert listed(provider) == ["GPT-a", "gpt-b", "gpt-c", "o1"]
    assert all(m.label is None for m in provider.list_models(timeout_s=5.0))
    request = rec.requests[0]
    assert request.method == "GET" and str(request.url) == "https://api.openai.com/v1/models"


def test_models_trailing_slash_in_base_url() -> None:
    rec = Recorder(models_reply("m"))
    listed(make(rec, "custom", base_url="http://localhost:11434/v1/"))
    assert str(rec.requests[0].url) == "http://localhost:11434/v1/models"


def test_models_tolerate_odd_entries() -> None:
    body = {"data": ["x", None, {"id": 5}, {"name": "n"}, {"id": ""}, {"id": "ok"}, 7]}
    assert listed(make(Recorder(httpx.Response(200, json=body)))) == ["ok"]


def test_models_prefix_is_stripped() -> None:
    rec = Recorder(models_reply("models/gemini-3.8-flash", "models/gemini-3.8-pro"))
    assert listed(make(rec, "gemini")) == ["gemini-3.8-flash", "gemini-3.8-pro"]


def test_non_chat_models_are_hidden() -> None:
    ids = [
        "gpt-6-luna",
        "text-embedding-3-large",
        "whisper-1",
        "gpt-4o-mini-tts",
        "DALL-E-3",
        "omni-moderation-latest",
        "gpt-image-1",
        "gpt-4o-realtime-preview",
        "gpt-4o-transcribe",
        "gpt-4o-search-preview",  # a chat model: kept on purpose
    ]
    assert listed(make(Recorder(models_reply(*ids)))) == ["gpt-4o-search-preview", "gpt-6-luna"]


def test_openrouter_models_without_text_output_are_hidden() -> None:
    data = [
        {"id": "a/text", "architecture": {"output_modalities": ["text"]}},
        {"id": "b/both", "architecture": {"output_modalities": ["image", "text"]}},
        {"id": "c/pic", "architecture": {"output_modalities": ["image"]}},
        {"id": "d/none"},
        {"id": "e/odd", "architecture": "x"},
    ]
    rec = Recorder(httpx.Response(200, json={"data": data}))
    assert listed(make(rec, "openrouter")) == ["a/text", "b/both", "d/none", "e/odd"]


def test_models_are_capped_at_500() -> None:
    rec = Recorder(models_reply(*(f"m{n:04d}" for n in range(700))))
    result = listed(make(rec))
    assert len(result) == 500 and result[0] == "m0000" and result[-1] == "m0499"


def test_models_request_has_a_bearer_header_only_with_a_key() -> None:
    rec = Recorder(models_reply("m"))
    listed(make(rec))
    assert rec.requests[0].headers["authorization"] == f"Bearer {KEY}"
    rec = Recorder(models_reply("m"))
    listed(make(rec, "custom", key=None))
    assert "authorization" not in rec.requests[0].headers


@pytest.mark.parametrize(
    ("status", "error", "text"),
    [
        (401, LLMAuthError, "HTTP 401"),
        (403, LLMAuthError, "HTTP 403"),
        (429, LLMRateLimited, "429"),
        (500, LLMRequestError, "HTTP 500"),
        (404, LLMNotSupported, "does not list its models"),
        (405, LLMNotSupported, "does not list its models"),
    ],
)
def test_models_status_mapping_never_shows_the_body(status: int, error: type, text: str) -> None:
    with pytest.raises(error) as info:
        listed(make(Recorder(httpx.Response(status, text=f"secret detail {KEY}"))))
    assert text in str(info.value)
    assert KEY not in str(info.value) and "secret detail" not in str(info.value)


def test_models_timeout_and_connection_failure() -> None:
    with pytest.raises(LLMTimeout, match="Timed out after 5 s"):
        listed(make(Recorder(httpx.ReadTimeout("slow"))))
    with pytest.raises(LLMRequestError, match="Could not reach OpenAI"):
        listed(make(Recorder(httpx.ConnectError("refused"))))


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json=["gpt"]),
        httpx.Response(200, json={"models": []}),
        httpx.Response(200, json={"data": {"id": "x"}}),
    ],
)
def test_models_unexpected_reply_is_invalid(response: httpx.Response) -> None:
    with pytest.raises(LLMInvalidReply, match="unexpected format"):
        listed(make(Recorder(response)))
