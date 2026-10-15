"""Ratings of search results: ``PUT``, ``DELETE`` and ``GET /api/ratings``.

A rating (0 not a fit, 1 OK, 2 good fit) belongs to the query a result came from, identified by
:func:`mcrar.recommend.ratings.query_key`. The request names the query the same way the search
body does (``text`` and ``filters``, resolved with the search route's own filter handling so
genre and mood synonyms give the same key). ``PUT`` sets or replaces a rating and answers
``{query_key, track_id, rating}``; ``DELETE`` takes the same body without ``rating`` (a JSON body
on ``DELETE``, which ``fetch`` supports) and answers 204, or 404 when there is no such rating.
An empty query is a 422 and an unknown track a 404. Ratings stay in the local catalog; the
search route reports them on each result.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from mcrar.api.routes.search import FiltersBody, resolve_filters
from mcrar.api.state import AppState, StateDep
from mcrar.recommend.ratings import filters_to_json, normalise_text, query_key

router = APIRouter()


class RatingTarget(BaseModel):
    """Which result of which query."""

    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(None, max_length=1000)
    filters: FiltersBody = Field(default_factory=FiltersBody)
    track_id: int


class RatingBody(RatingTarget):
    rating: Literal[0, 1, 2]


def _key(state: AppState, target: RatingTarget) -> str:
    return query_key(target.text, resolve_filters(target.filters, state.search.vocab))


@router.put("/api/ratings")
def put_rating(body: RatingBody, state: StateDep) -> dict[str, Any]:
    filters = resolve_filters(body.filters, state.search.vocab)
    key = query_key(body.text, filters)
    stored = state.repo.set_rating(
        key,
        body.track_id,
        body.rating,
        query_text=normalise_text(body.text),
        filters_json=filters_to_json(filters),
    )
    return {"query_key": stored.query_key, "track_id": stored.track_id, "rating": stored.rating}


@router.delete("/api/ratings", status_code=204)
def delete_rating(body: RatingTarget, state: StateDep) -> Response:
    key = _key(state, body)
    if not state.repo.delete_rating(key, body.track_id):
        raise LookupError(f"track {body.track_id} has no rating for this query")
    return Response(status_code=204)


@router.get("/api/ratings")
def list_ratings(
    state: StateDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """The ratings, most recently changed first."""
    page, total = state.repo.list_ratings(limit=limit, offset=offset)
    tracks = state.repo.get_tracks(r.track_id for r in page)
    items = []
    for r in page:
        track = tracks.get(r.track_id)
        if track is None:  # cannot happen (rows cascade with their track), but never fail a list
            continue
        items.append(
            {
                "query_key": r.query_key,
                "query_text": r.query_text,
                "filters": json.loads(r.filters_json),
                "track": {"id": track.id, "title": track.title, "artist": track.artist},
                "rating": r.rating,
                "updated_at": r.updated_at,
            }
        )
    return {"items": items, "total": total}
