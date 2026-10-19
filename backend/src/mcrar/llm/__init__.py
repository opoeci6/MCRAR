"""The optional LLM (M7): a provider seam, the built-in presets and a client over the settings.

This package ``__init__`` imports nothing from the rest of ``mcrar`` (and not the provider
modules, which import ``httpx`` or the Anthropic SDK), because :mod:`mcrar.config` validates
preset ids against :mod:`mcrar.llm.presets`. Import ``LLMClient`` from :mod:`mcrar.llm.client`.
"""

from mcrar.llm.base import (
    LLMAuthError,
    LLMError,
    LLMInvalidReply,
    LLMNotConfigured,
    LLMProvider,
    LLMRateLimited,
    LLMRequestError,
    LLMTimeout,
    Message,
)
from mcrar.llm.presets import PRESET_IDS, PRESETS, Preset, get_preset

__all__ = [
    "PRESETS",
    "PRESET_IDS",
    "LLMAuthError",
    "LLMError",
    "LLMInvalidReply",
    "LLMNotConfigured",
    "LLMProvider",
    "LLMRateLimited",
    "LLMRequestError",
    "LLMTimeout",
    "Message",
    "Preset",
    "get_preset",
]
