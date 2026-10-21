"""The Anthropic provider: the official SDK, with structured output (``output_config.format``).

The SDK's own retries are off (``max_retries=0``) and its errors are translated into fixed,
safe :class:`~mcrar.llm.base.LLMError` texts: ``e.message`` and the body are never used. The
failure is raised outside the ``except`` block so no chained SDK exception survives. The SDK is
built on ``httpx2``, so a test transport goes in as an ``httpx2.Client`` (``http_client``).
"""

from __future__ import annotations

from typing import Any

import anthropic

from mcrar.llm.base import (
    NOT_FOUND_TEXT,
    NOT_SUPPORTED_TEXT,
    LLMAuthError,
    LLMError,
    LLMInvalidReply,
    LLMNotSupported,
    LLMRateLimited,
    LLMRequestError,
    LLMTimeout,
    Message,
    ModelInfo,
    auth_text,
    status_text,
    timeout_text,
)
from mcrar.llm.jsonutil import parse_json_reply
from mcrar.llm.presets import is_chat_model_id

LABEL = "Anthropic (Claude)"
PAGE_SIZE = 100
MAX_LISTED_MODELS = 1000


class AnthropicProvider:
    def __init__(
        self, *, model: str, base_url: str, api_key: str, http_client: Any | None = None
    ) -> None:
        self.model = model
        self.label = LABEL
        self._client = anthropic.Anthropic(
            api_key=api_key, base_url=base_url or None, max_retries=0, http_client=http_client
        )

    def __repr__(self) -> str:
        return f"AnthropicProvider(model={self.model!r})"

    def close(self) -> None:
        self._client.close()

    def complete_json(
        self,
        messages: list[Message],
        schema: dict[str, Any],
        *,
        name: str,
        max_tokens: int,
        timeout_s: float,
    ) -> dict[str, Any]:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        turns = [{"role": "user", "content": m["content"]} for m in messages if m["role"] == "user"]
        failure: LLMError | None = None
        response: Any = None
        try:
            response = self._client.with_options(timeout=timeout_s).messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=turns,
                output_config={
                    "format": {"type": "json_schema", "schema": schema},
                    "effort": "low",
                },
            )
        except anthropic.APIError as exc:
            failure = self._failure(exc, timeout_s, listing=False)
        if failure is not None:
            raise failure
        return self._reply(response)

    def list_models(self, *, timeout_s: float) -> list[ModelInfo]:
        """The models the account can use (``GET /v1/models``, all pages), sorted by id, with
        the display name as the label. Ids that are not chat models are hidden."""
        found: dict[str, ModelInfo] = {}
        failure: LLMError | None = None
        try:
            page = self._client.with_options(timeout=timeout_s).models.list(limit=PAGE_SIZE)
            for item in page:  # the SDK fetches the next pages as the loop goes on
                model_id = getattr(item, "id", None)
                if isinstance(model_id, str) and is_chat_model_id(model_id):
                    name = getattr(item, "display_name", None)
                    found[model_id] = ModelInfo(model_id, name if isinstance(name, str) else None)
                if len(found) >= MAX_LISTED_MODELS:
                    break
        except anthropic.APIError as exc:
            failure = self._failure(exc, timeout_s, listing=True)
        if failure is not None:
            raise failure
        return sorted(found.values(), key=lambda m: (m.id.casefold(), m.id))

    def _failure(self, exc: anthropic.APIError, timeout_s: float, *, listing: bool) -> LLMError:
        """The safe :class:`LLMError` for an SDK error (never its message or body)."""
        if isinstance(exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
            return LLMAuthError(auth_text(exc.status_code))
        if isinstance(exc, anthropic.RateLimitError):
            return LLMRateLimited(
                "The LLM service is rate limiting requests (HTTP 429). Try again."
            )
        if isinstance(exc, anthropic.APITimeoutError):  # before APIConnectionError, its base class
            return LLMTimeout(timeout_text(timeout_s))
        if isinstance(exc, anthropic.NotFoundError):
            if listing:
                return LLMNotSupported(NOT_SUPPORTED_TEXT)
            return LLMRequestError(NOT_FOUND_TEXT)
        if isinstance(exc, anthropic.APIStatusError):
            return LLMRequestError(status_text(exc.status_code))
        if isinstance(exc, anthropic.APIConnectionError):
            return LLMRequestError(f"Could not reach {self.label}.")
        return LLMInvalidReply("The LLM service sent a reply in an unexpected format.")

    def _reply(self, response: Any) -> dict[str, Any]:
        if response.stop_reason == "refusal":
            raise LLMInvalidReply("The model refused to answer.")
        if response.stop_reason == "max_tokens":
            raise LLMInvalidReply(
                "The reply was cut off (token limit reached). Try again or use another model."
            )
        text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
        return parse_json_reply(text)
