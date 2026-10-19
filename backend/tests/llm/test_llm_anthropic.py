"""The Anthropic provider over a mocked transport. The SDK is built on ``httpx2``, so the test
client and transport come from that package."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx2
import pytest

from mcrar.llm.anthropic_provider import AnthropicProvider
from mcrar.llm.base import (
    LLMAuthError,
    LLMInvalidReply,
    LLMRateLimited,
    LLMRequestError,
    LLMTimeout,
)

KEY = "sk-ant-FAKE-KEY-0123456789"
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


def message(text: str | None, *, stop: str = "end_turn") -> httpx2.Response:
    content = [] if text is None else [{"type": "text", "text": text}]
    return httpx2.Response(
        200,
        json={
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-haiku-5-5",
            "content": content,
            "stop_reason": stop,
            "stop_sequence": None,
            "usage": {"input_tokens": 3, "output_tokens": 4},
        },
    )


class Recorder:
    def __init__(self, response: httpx2.Response | Exception) -> None:
        self.response = response
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def make(rec: Recorder) -> AnthropicProvider:
    client = httpx2.Client(transport=httpx2.MockTransport(rec))
    return AnthropicProvider(
        model="claude-haiku-5-5",
        base_url="https://api.anthropic.com",
        api_key=KEY,
        http_client=client,
    )


def call(provider: AnthropicProvider) -> dict[str, Any]:
    return provider.complete_json(
        list(MESSAGES), SCHEMA, name="test", max_tokens=300, timeout_s=7.0
    )


def test_valid_reply_and_request_shape() -> None:
    rec = Recorder(message('{"ok": true}'))
    assert call(make(rec)) == {"ok": True}
    request = rec.requests[0]
    assert str(request.url) == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == KEY
    body = json.loads(request.content)
    assert body["model"] == "claude-haiku-5-5" and body["max_tokens"] == 300
    assert body["system"] == "You are a test."
    assert body["messages"] == [{"role": "user", "content": "hello"}]
    assert body["output_config"] == {
        "format": {"type": "json_schema", "schema": SCHEMA},
        "effort": "low",
    }


@pytest.mark.parametrize("text", ['```json\n{"ok": true}\n```', 'Here: {"ok": true} done'])
def test_fenced_and_wrapped_json(text: str) -> None:
    assert call(make(Recorder(message(text)))) == {"ok": True}


@pytest.mark.parametrize("text", ["nope", "[1]", None])
def test_unusable_reply(text: str | None) -> None:
    with pytest.raises(LLMInvalidReply):
        call(make(Recorder(message(text))))


def test_refusal_and_max_tokens_are_checked_before_the_text() -> None:
    with pytest.raises(LLMInvalidReply, match="refused"):
        call(make(Recorder(message('{"ok": true}', stop="refusal"))))
    with pytest.raises(LLMInvalidReply, match="cut off"):
        call(make(Recorder(message('{"ok": tr', stop="max_tokens"))))


@pytest.mark.parametrize(
    ("status", "error", "text"),
    [
        (401, LLMAuthError, "HTTP 401"),
        (403, LLMAuthError, "HTTP 403"),
        (404, LLMRequestError, "not found (HTTP 404)"),
        (429, LLMRateLimited, "429"),
        (500, LLMRequestError, "HTTP 500"),
        (400, LLMRequestError, "HTTP 400"),
    ],
)
def test_status_mapping_never_shows_the_body(status: int, error: type, text: str) -> None:
    body = {"type": "error", "error": {"type": "x", "message": f"secret detail {KEY}"}}
    with pytest.raises(error) as info:
        call(make(Recorder(httpx2.Response(status, json=body))))
    assert text in str(info.value)
    assert KEY not in str(info.value) and "secret detail" not in str(info.value)
    assert info.value.__cause__ is None and info.value.__context__ is None


def test_timeout_and_connection_failure() -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    with pytest.raises(LLMTimeout, match="Timed out after 7 s"):
        call(make(Recorder(httpx2.ReadTimeout("slow", request=request))))
    with pytest.raises(LLMRequestError, match="Could not reach Anthropic"):
        call(make(Recorder(httpx2.ConnectError("refused", request=request))))


def test_the_key_is_not_in_repr_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    provider = make(Recorder(httpx2.Response(401, json={"error": {"message": KEY}})))
    assert KEY not in repr(provider)
    with pytest.raises(LLMAuthError) as info:
        call(provider)
    provider.close()
    assert KEY not in str(info.value) and KEY not in caplog.text
