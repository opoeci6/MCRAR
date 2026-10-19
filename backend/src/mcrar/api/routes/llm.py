"""The optional LLM: ``GET /api/llm`` (is it usable, and if not why) and ``POST /api/llm/test``.

The test sends a tiny request with the saved settings, or with the preset, model and base URL of
the body (so the settings page can try a form before saving it). It works while the LLM is
disabled and always answers 200 with ``ok``: a failure is safe text (never a key or the provider's
reply body). The provider call is synchronous, so the route is a plain ``def`` that FastAPI runs
in its thread pool.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, field_validator

from mcrar.api.state import StateDep
from mcrar.llm.presets import PRESET_IDS

router = APIRouter()


class LLMTestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: str | None = None
    model: str | None = Field(None, max_length=200)
    base_url: str | None = Field(None, max_length=500)

    @field_validator("preset")
    @classmethod
    def _known_preset(cls, value: str | None) -> str | None:
        if value is not None and value not in PRESET_IDS:
            raise ValueError(f"unknown preset; choose from: {', '.join(PRESET_IDS)}")
        return value

    @field_validator("base_url")
    @classmethod
    def _http_url(cls, value: str | None) -> str | None:
        if value and not value.strip().startswith(("http://", "https://")):
            raise ValueError("must be empty or start with http:// or https://")
        return value


@router.get("/api/llm")
def llm_status(state: StateDep) -> dict[str, Any]:
    return state.llm.status().to_dict()


@router.post("/api/llm/test")
def llm_test(state: StateDep, body: LLMTestBody | None = None) -> dict[str, Any]:
    overrides = body.model_dump() if body else {}
    return state.llm.test(**overrides)
