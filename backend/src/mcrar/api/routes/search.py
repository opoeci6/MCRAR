"""``POST /api/search``: the search service behind a JSON body.

The body mirrors the CLI: free text and/or structured filters. Filter values go through the same
validation as the CLI's options (:func:`mcrar.recommend.request.build_filters`). Text search loads
the embedding model on first use and answers 503 when the ``ml`` extra is missing; a search with
filters only never loads it. Each item carries the owner's ``rating`` (0-2, or null) for this
query (:mod:`mcrar.recommend.ratings`), except in a search with a reference song, which has none.

A search may take a reference song, ``reference: {track_id}`` (a catalog track) or
``{upload_id}`` (from ``POST /api/reference``, see :mod:`mcrar.api.routes.reference`), with
``reference_weight`` as its share of the semantic score; it needs no text or filter then. Results
are ranked by the audio-audio cosine, blended with the text when there is some. A reference needs
no torch (its embedding exists already), but a text does.

``POST /api/search/rerank`` runs the same search for the top ``llm.rerank_top_n`` results and asks
the LLM to reorder them (:mod:`mcrar.recommend.llm_rerank`). It answers 503 while the LLM is not
usable and 502 (with a safe message) when the LLM call fails. When the LLM is enabled but not
usable (no key), a normal search reports no ``llm`` block: ``GET /api/llm`` says why.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from mcrar.api.state import AppState, StateDep
from mcrar.llm.base import LLMError
from mcrar.llm.client import token_budget
from mcrar.recommend import (
    ReferenceQuery,
    SearchError,
    SearchFilters,
    SearchRequest,
    SearchResult,
)
from mcrar.recommend.llm_rerank import MAX_TOKENS, rerank
from mcrar.recommend.ratings import query_key
from mcrar.recommend.request import build_filters
from mcrar.recommend.vocab import Vocabulary

router = APIRouter()
NO_LLM_MESSAGE = "No LLM is configured. Set one up in Settings."


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


class ReferenceBody(BaseModel):
    """The reference song: a catalog track or an earlier upload (``POST /api/reference``)."""

    model_config = ConfigDict(extra="forbid")

    track_id: int | None = None
    upload_id: str | None = Field(None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def _exactly_one(self) -> ReferenceBody:
        if (self.track_id is None) == (self.upload_id is None):
            raise ValueError("give exactly one of track_id and upload_id")
        return self


class SearchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(None, max_length=1000)
    filters: FiltersBody = Field(default_factory=FiltersBody)
    limit: int = Field(20, ge=1, le=100)
    offset: int = Field(0, ge=0)
    explain: bool = True
    reference: ReferenceBody | None = None
    reference_weight: float = Field(0.5, ge=0, le=1)  # the reference's share of the semantic score


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


def resolve_reference(body: SearchBody, state: AppState) -> ReferenceQuery | None:
    """The body's reference song with its embedding: 404 for an unknown track or an upload that
    is gone, 422 for a track without an embedding, 409 when the upload was embedded with another
    model than the one searched."""
    ref = body.reference
    if ref is None:
        return None
    if ref.track_id is not None:
        return state.search.reference_for_track(ref.track_id, body.reference_weight)
    stored = state.references.get(ref.upload_id or "")
    if stored is None:
        raise LookupError("This uploaded song has expired. Upload it again.")
    if stored.model_id != state.search.model_id:
        raise HTTPException(409, "The embedding model changed since the upload. Upload it again.")
    return ReferenceQuery(stored.vector, stored.filename, "upload", weight=body.reference_weight)


@router.post("/api/search")
def search(body: SearchBody, state: StateDep) -> dict[str, Any]:
    filters = resolve_filters(body.filters, state.search.vocab)
    if body.reference is None and not (body.text or "").strip() and filters == SearchFilters():
        raise SearchError("give a search text or at least one filter")
    request = SearchRequest(
        text=body.text,
        filters=filters,
        limit=body.limit,
        offset=body.offset,
        explain=body.explain,
        reference=resolve_reference(body, state),
    )
    found = state.search.search(request)
    if found.llm is not None and not state.llm.status().ready:
        found = replace(found, llm=None)  # enabled, but no key or model: nothing was asked
    return with_ratings(state, found, body.text, filters)


def with_ratings(
    state: AppState, result: SearchResult, text: str | None, filters: SearchFilters
) -> dict[str, Any]:
    """The result as a dict with each item's ``rating`` for this query (shared with rerank).

    A search with a reference song has no ratings: a rating is filed under the text and filters,
    which do not say which song the results resembled."""
    data = result.to_dict()
    ratings = (
        {}
        if result.reference is not None
        else state.repo.ratings_for(
            query_key(text, filters), (item["track_id"] for item in data["items"])
        )
    )
    for item in data["items"]:
        item["rating"] = ratings.get(item["track_id"])
    return data


@router.post("/api/search/rerank")
def search_rerank(body: SearchBody, state: StateDep) -> dict[str, Any]:
    """Search for the top results of ``text`` and let the LLM reorder them."""
    if body.reference is not None:
        raise SearchError("LLM rerank doesn't use a reference song yet.")
    filters = resolve_filters(body.filters, state.search.vocab)
    if not (body.text or "").strip():
        raise SearchError("give a search text to rerank")
    if not state.llm.status().ready:
        raise HTTPException(503, NO_LLM_MESSAGE)
    cfg = state.settings.llm
    request = SearchRequest(
        text=body.text, filters=filters, limit=cfg.rerank_top_n, offset=0, explain=True
    )
    found = state.search.search(request)
    if not found.items:
        return with_ratings(state, found, body.text, filters)
    tracks = state.repo.get_tracks([item.track_id for item in found.items])
    budget = token_budget(state.llm.resolve().preset, MAX_TOKENS)
    try:
        provider = state.llm.provider()
        try:
            items, info = rerank(
                provider,
                text=body.text or "",
                parsed=found.parsed,
                items=found.items,
                timeout_s=cfg.rerank_timeout_s,
                tracks=tracks,
                max_tokens=budget,
            )
        finally:
            provider.close()
    except LLMError as exc:
        raise HTTPException(502, str(exc)) from None
    return with_ratings(state, replace(found, items=items, rerank=info), body.text, filters)
