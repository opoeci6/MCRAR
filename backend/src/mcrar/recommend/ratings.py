"""The key a rating is filed under: which question the owner was answering.

A rating says how well a track fits a *query*, so ratings are stored per query key and found
again whenever the same query is searched. The key is built from what the user asked, not from
how the engine understood it:

- With search text the key is ``text:`` plus the text lowercased and whitespace-collapsed. The
  filters are left out on purpose: the rating is about the intent in the words, so a narrower
  search for the same words still shows the earlier ratings.
- Without text the key is ``filters:`` plus a canonical JSON of the filter fields that are set.
  Genres and moods are label ids (synonyms are resolved before the key is built), lists are
  sorted and the JSON has sorted keys and no spaces, so equal filters always give equal keys.

``filters_to_json`` / ``filters_from_json`` store a query's filters next to its ratings so the
query can be run again (``mcrar ratings eval``). No SQL here; the repository stores the strings.
"""

from __future__ import annotations

import json
from dataclasses import fields
from typing import Any

from mcrar.recommend.query import SearchFilters

TEXT_PREFIX = "text:"
FILTERS_PREFIX = "filters:"

_DEFAULT = SearchFilters()
_LIST_FIELDS = ("sources", "genres", "moods")
_NUMBER_FIELDS = ("bpm_min", "bpm_max", "duration_min_s", "duration_max_s")


def normalise_text(text: str | None) -> str | None:
    """The text with whitespace collapsed (case kept), or None when nothing is left."""
    collapsed = " ".join((text or "").split())
    return collapsed or None


def _number(value: float) -> float | int:
    number = float(value)
    return int(number) if number.is_integer() else number


def _filter_fields(filters: SearchFilters) -> dict[str, Any]:
    """The fields that differ from the defaults, in canonical form (lists sorted, numbers plain)."""
    out: dict[str, Any] = {}
    for f in fields(SearchFilters):
        value = getattr(filters, f.name)
        if value == getattr(_DEFAULT, f.name):
            continue
        if f.name in _LIST_FIELDS:
            value = sorted(set(value))
        elif f.name in _NUMBER_FIELDS:
            value = _number(value)
        out[f.name] = value
    return out


def filters_to_json(filters: SearchFilters) -> str:
    """Canonical JSON of the non-default filter fields (``{}`` for the defaults)."""
    return json.dumps(_filter_fields(filters), sort_keys=True, separators=(",", ":"))


def filters_from_json(text: str) -> SearchFilters:
    """The inverse of :func:`filters_to_json`. Raises ``ValueError`` on anything else."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise ValueError("filters are not valid JSON") from None
    known = {f.name for f in fields(SearchFilters)}
    if not isinstance(data, dict) or not set(data) <= known:
        raise ValueError("filters must be a JSON object of search filter fields")
    if any(k in _LIST_FIELDS and not isinstance(v, list) for k, v in data.items()):
        raise ValueError("sources, genres and moods must be lists")
    values = {k: tuple(v) if k in _LIST_FIELDS else v for k, v in data.items()}
    return SearchFilters(**values)


def query_key(text: str | None, filters: SearchFilters) -> str:
    """The key ratings are stored under; ``ValueError`` for an empty query (no text, no filters)."""
    normalised = normalise_text(text)
    if normalised is not None:
        return TEXT_PREFIX + normalised.lower()
    if filters == _DEFAULT:
        raise ValueError("give a search text or at least one filter")
    return FILTERS_PREFIX + filters_to_json(filters)
