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

LABEL = "Anthropic (Claude)"


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
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            failure = LLMAuthError(auth_text(exc.status_code))
        except anthropic.RateLimitError:
            failure = LLMRateLimited(
                "The LLM service is rate limiting requests (HTTP 429). Try again."
            )
        except anthropic.APITimeoutError:  # before APIConnectionError, its base class
            failure = LLMTimeout(timeout_text(timeout_s))
        except anthropic.NotFoundError:
            failure = LLMRequestError(NOT_FOUND_TEXT)
        except anthropic.APIStatusError as exc:
            failure = LLMRequestError(status_text(exc.status_code))
        except anthropic.APIConnectionError:
            failure = LLMRequestError(f"Could not reach {self.label}.")
        if failure is not None:
            raise failure
        return self._reply(response)

    def _reply(self, response: Any) -> dict[str, Any]:
        if response.stop_reason == "refusal":
            raise LLMInvalidReply("The model refused to answer.")
        if response.stop_reason == "max_tokens":
            raise LLMInvalidReply(
                "The reply was cut off (token limit reached). Try again or use another model."
            )
        text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
        return parse_json_reply(text)
