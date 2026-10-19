"""A provider for services that speak OpenAI's ``/chat/completions`` (OpenAI, DeepSeek, Gemini,
Groq, OpenRouter, Ollama, ...), over plain ``httpx``.

JSON mode differs between these services: ``json_schema`` (strict structured output),
``json_object`` or nothing. The request starts in the preset's mode and, when the service answers
HTTP 400 about ``response_format``/``json_schema``, steps down (``json_schema`` -> ``json_object``
-> none) and asks again; the mode that worked is remembered per ``(base_url, model)`` for the rest
of the process. The schema is always also written into the system message, so a model without
any JSON mode still knows the shape (and DeepSeek's "the prompt must say json" rule holds).

Errors follow :mod:`mcrar.llm.base`: fixed wording plus a status, never the response body. The
failure is raised outside the ``except`` block so no chained httpx exception (which holds the
URL and headers) survives. The key travels in the ``Authorization`` header only. There are no
automatic retries beyond the JSON-mode step-down.
"""

from __future__ import annotations

import json
import threading
from typing import Any

import httpx

from mcrar.llm.base import (
    NOT_FOUND_TEXT,
    LLMAuthError,
    LLMError,
    LLMInvalidReply,
    LLMRateLimited,
    LLMRequestError,
    LLMTimeout,
    Message,
    auth_text,
    status_text,
    timeout_text,
)
from mcrar.llm.jsonutil import parse_json_reply
from mcrar.llm.presets import JsonMode, Preset

STEP_DOWN: dict[JsonMode, JsonMode] = {"json_schema": "json_object", "json_object": "none"}
_FORMAT_WORDS = ("response_format", "json_schema")
_modes: dict[tuple[str, str], JsonMode] = {}
_modes_lock = threading.Lock()


def _remembered(base_url: str, model: str, default: JsonMode) -> JsonMode:
    with _modes_lock:
        return _modes.get((base_url, model), default)


def _remember(base_url: str, model: str, mode: JsonMode) -> None:
    with _modes_lock:
        _modes[(base_url, model)] = mode


def _with_schema_hint(messages: list[Message], schema: dict[str, Any]) -> list[Message]:
    """``messages`` with the JSON instruction appended to the system message (added if absent)."""
    hint = "Reply with one JSON object that matches this JSON schema: " + json.dumps(
        schema, separators=(",", ":")
    )
    out = [Message(role=m["role"], content=m["content"]) for m in messages]
    for message in out:
        if message["role"] == "system":
            message["content"] = f"{message['content']}\n\n{hint}"
            return out
    return [Message(role="system", content=hint), *out]


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # content parts: [{"type": "text", "text": "..."}]
        return "".join(
            part["text"] for part in content if isinstance(part, dict) and "text" in part
        )
    return ""


class OpenAICompatProvider:
    def __init__(
        self,
        preset: Preset,
        *,
        model: str,
        base_url: str,
        api_key: str | None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.preset = preset
        self.model = model
        self.label = preset.label
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.Client(transport=transport, follow_redirects=False)

    def __repr__(self) -> str:
        return f"OpenAICompatProvider(preset={self.preset.id!r}, model={self.model!r})"

    def close(self) -> None:
        self._client.close()

    # -- request ---------------------------------------------------------------------------

    def _body(
        self,
        messages: list[Message],
        mode: JsonMode,
        schema: dict[str, Any],
        name: str,
        tokens: int,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            self.preset.token_param: tokens,
        }
        if mode == "json_schema":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": name, "strict": True, "schema": schema},
            }
        elif mode == "json_object":
            body["response_format"] = {"type": "json_object"}
        if self.model == self.preset.default_model:  # these flags are model-specific
            body.update(self.preset.extra_body)
        return body

    def _post(self, body: dict[str, Any], timeout_s: float) -> httpx.Response:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        failure: LLMError | None = None
        try:
            return self._client.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json=body,
                timeout=timeout_s,
            )
        except httpx.TimeoutException:
            failure = LLMTimeout(timeout_text(timeout_s))
        except (httpx.HTTPError, httpx.InvalidURL):
            failure = LLMRequestError(f"Could not reach {self.label}.")
        raise failure

    def complete_json(
        self,
        messages: list[Message],
        schema: dict[str, Any],
        *,
        name: str,
        max_tokens: int,
        timeout_s: float,
    ) -> dict[str, Any]:
        prompt = _with_schema_hint(messages, schema)
        default_mode = self.preset.json_mode
        mode = _remembered(self._base_url, self.model, default_mode)
        while True:
            response = self._post(self._body(prompt, mode, schema, name, max_tokens), timeout_s)
            status = response.status_code
            if status == 400 and mode != "none" and any(w in response.text for w in _FORMAT_WORDS):
                mode = STEP_DOWN[mode]
                continue
            break
        self._check_status(status)
        if mode != default_mode:
            _remember(self._base_url, self.model, mode)
        return self._reply(response)

    # -- response --------------------------------------------------------------------------

    def _check_status(self, status: int) -> None:
        if 200 <= status < 300:
            return
        if status in (401, 403):
            raise LLMAuthError(auth_text(status))
        if status == 429:
            raise LLMRateLimited("The LLM service is rate limiting requests (HTTP 429). Try again.")
        if status == 404:
            raise LLMRequestError(NOT_FOUND_TEXT)
        raise LLMRequestError(status_text(status))

    def _reply(self, response: httpx.Response) -> dict[str, Any]:
        fields: tuple[Any, Any, Any] | None = None
        try:
            choice = response.json()["choices"][0]
            message = choice["message"]
            fields = (choice.get("finish_reason"), message.get("refusal"), message.get("content"))
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            pass
        if fields is None:
            raise LLMInvalidReply("The LLM service sent a reply in an unexpected format.")
        finish, refusal, content = fields
        if finish == "length":
            raise LLMInvalidReply(
                "The reply was cut off (token limit reached). Try again or use another model."
            )
        if refusal:
            raise LLMInvalidReply("The model refused to answer.")
        return parse_json_reply(_content_text(content))
