"""Reading the JSON object out of a model's text reply (weaker models fence or wrap it)."""

from __future__ import annotations

import json
import re
from typing import Any

from mcrar.llm.base import LLMInvalidReply

_FENCE = re.compile(r"^```[a-zA-Z0-9_-]*\s*(.*?)\s*```$", re.DOTALL)
NOT_JSON = "The model's reply was not valid JSON."


def parse_json_reply(text: str | None) -> dict[str, Any]:
    """The top-level JSON object in ``text``: fences are stripped, and prose around a single
    object is tolerated (the outermost ``{...}`` is taken). Raises :class:`LLMInvalidReply`."""
    body = (text or "").strip()
    if not body:
        raise LLMInvalidReply("The model's reply was empty.")
    fenced = _FENCE.match(body)
    if fenced:
        body = fenced.group(1).strip()
    data: Any = None
    ok = False
    try:
        data, ok = json.loads(body), True
    except ValueError:
        start, end = body.find("{"), body.rfind("}")
        if 0 <= start < end:
            try:
                data, ok = json.loads(body[start : end + 1]), True
            except ValueError:
                pass
    if not ok:
        raise LLMInvalidReply(NOT_JSON)
    if not isinstance(data, dict):
        raise LLMInvalidReply("The model's reply was not a JSON object.")
    return data
