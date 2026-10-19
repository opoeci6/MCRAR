"""The provider seam of the optional LLM (M7): messages in, one JSON object out.

An :class:`LLMProvider` answers one request with a JSON object that follows a schema. Every
error is an :class:`LLMError` whose text is fixed, safe wording plus at most an HTTP status: it
never holds the provider's response body, headers, URL query or the API key, so it can be shown
in the UI and the CLI as it is.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, TypedDict


class Message(TypedDict):
    role: Literal["system", "user"]
    content: str


class LLMError(RuntimeError):
    """An LLM call failed. The message is safe to show."""


class LLMNotConfigured(LLMError):
    """No key or no model is set for the chosen provider."""


class LLMTimeout(LLMError):
    """The provider did not answer in time."""


class LLMAuthError(LLMError):
    """The provider rejected the API key (HTTP 401/403)."""


class LLMRateLimited(LLMError):
    """The provider answered HTTP 429."""


class LLMInvalidReply(LLMError):
    """The reply was empty, cut off, refused or not the expected JSON object."""


class LLMRequestError(LLMError):
    """Any other HTTP or connection failure."""


class LLMProvider(Protocol):
    model: str
    label: str

    def complete_json(
        self,
        messages: list[Message],
        schema: dict[str, Any],
        *,
        name: str,
        max_tokens: int,
        timeout_s: float,
    ) -> dict[str, Any]:
        """The model's reply to ``messages`` as a JSON object (``schema`` describes it)."""
        ...

    def close(self) -> None: ...


NOT_FOUND_TEXT = "Model or endpoint not found (HTTP 404). Check the model name and base URL."


def auth_text(status: int) -> str:
    return f"Authentication failed (HTTP {status}). Check the API key."


def timeout_text(timeout_s: float) -> str:
    return f"Timed out after {timeout_s:g} s."


def status_text(status: int) -> str:
    return f"The LLM service answered HTTP {status}."
