"""``POST /api/search``: the search service behind a JSON body.

The body mirrors the CLI: free text and/or structured filters. Filter values go through the same
validation as the CLI's options (:func:`mcrar.recommend.request.build_filters`). Text search loads
the embedding model on first use and answers 503 when the ``ml`` extra is missing; a search with
filters only never loads it. Each item carries the owner's ``rating`` (0-2, or null) for this
query (:mod:`mcrar.recommend.ratings`).
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from mcrar.api.state import StateDep
from mcrar.recommend import SearchError, SearchFilters, SearchRequest
from mcrar.recommend.ratings import query_key
from mcrar.recommend.request import build_filters
from mcrar.recommend.vocab import Vocabulary

router = APIRouter()


class FiltersBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_risk: Literal["green", "amber", "red", "unknown"] | None = None
    vocal: Literal["vocal", "instrumental"] | None = None
    bpm_min: float | None = Field(None, ge=0)
    bpm_max: float | None = Field(None, ge=0)
    duration_min_s: float | None = Field(None, ge=0)
    duration_max_s: float | None = Field(None, ge=0)
    sources: list[str] | None = None
    genres: list[str] = Field(default_factory=list)
    moods: list[str] = Field(default_factory=list)


class SearchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(None, max_length=1000)
    filters: FiltersBody = Field(default_factory=FiltersBody)
    limit: int = Field(20, ge=1, le=100)
    offset: int = Field(0, ge=0)
    explain: bool = True


def resolve_filters(f: FiltersBody, vocab: Vocabulary) -> SearchFilters:
    """The body's filters as ``SearchFilters``, validated like the CLI options (shared with the
    ratings routes, so a rating is filed under the same key as the search it came from)."""
    return build_filters(
        vocab,
        genres=f.genres,
        moods=f.moods,
        bpm=(f.bpm_min, f.bpm_max),
        duration=(f.duration_min_s, f.duration_max_s),
        max_risk=None if f.max_risk == "unknown" else f.max_risk,
        vocal=f.vocal,
        sources=f.sources,
        arg=lambda name: "sources" if name == "source" else name,  # the body field is plural
    )


@router.post("/api/search")
def search(body: SearchBody, state: StateDep) -> dict[str, Any]:
    filters = resolve_filters(body.filters, state.search.vocab)
    if not (body.text or "").strip() and filters == SearchFilters():
        raise SearchError("give a search text or at least one filter")
    request = SearchRequest(
        text=body.text, filters=filters, limit=body.limit, offset=body.offset, explain=body.explain
    )
    result = state.search.search(request).to_dict()
    ratings = state.repo.ratings_for(
        query_key(body.text, filters), (item["track_id"] for item in result["items"])
    )
    for item in result["items"]:
        item["rating"] = ratings.get(item["track_id"])
    return result
