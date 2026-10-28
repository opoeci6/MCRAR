"""Freesound searches for a text query: what to ask Freesound so it returns music worth ranking.

Freesound's ``query`` is a full-text search over names, tags and descriptions. Like
:mod:`mcrar.recommend.jamendo_query` this returns the searches in order of preference, tried until
enough new sounds were found (:func:`mcrar.ingest.pipeline.ingest_freesound_queries`): the keywords
from the LLM parser first (one query each), then the semantic text; repeats are left out (case
and spacing ignored) and at most :data:`MAX_QUERIES` are returned (when the keywords alone would
fill them, the last keyword makes room for the semantic text).

The search filters map like this. Every query is limited to music-like sounds
(``music_like=True``, the Music and Soundscapes categories). Licences are CC0 and CC BY, unless the
search explicitly allows the red risk level (``max_risk == "red"``): then CC BY-NC is added too
(the default ``unknown`` level filters nothing in the catalog, but does not pull in
non-commercial sounds). Durations follow the search's duration filter (never below
:data:`MIN_DURATION_S`, so loops and effects stay out); without one it is 10 to 600 seconds. The
other search filters (vocal, BPM, genre, mood) have no Freesound equivalent and only apply in
the catalog.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from mcrar.ingest.pipeline import FreesoundQuery

if TYPE_CHECKING:
    from mcrar.recommend.query import SearchFilters

MAX_QUERIES = 3
MIN_DURATION_S = 10.0
DEFAULT_MAX_DURATION_S = 600.0
LICENSES = ("cc0", "by")
LICENSES_WITH_NC = ("cc0", "by", "by-nc")


def freesound_queries(
    semantic_text: str,
    filters: SearchFilters,
    extra_terms: Sequence[str] = (),
    *,
    max_queries: int = MAX_QUERIES,
) -> list[FreesoundQuery]:
    """The Freesound searches for ``semantic_text`` under ``filters``, most specific first.

    ``extra_terms`` (keywords the LLM parser suggests) each become their own query ahead of the
    semantic text. Empty when there is no text at all.
    """
    texts: dict[str, str] = {}  # casefolded -> text, in order
    for text in extra_terms:
        text = " ".join(text.split())
        if text:
            texts.setdefault(text.casefold(), text)
    original = " ".join(semantic_text.split())
    if original:
        # The semantic text always gets its slot, even when the keywords alone fill the cap.
        keywords = [t for key, t in texts.items() if key != original.casefold()]
        texts = {t.casefold(): t for t in keywords[: max(max_queries - 1, 0)]}
        texts[original.casefold()] = original

    low = MIN_DURATION_S
    if filters.duration_min_s is not None:
        low = max(MIN_DURATION_S, float(filters.duration_min_s))
    if filters.duration_max_s is not None:
        high: float | None = max(float(filters.duration_max_s), low)
    else:
        high = DEFAULT_MAX_DURATION_S if low <= DEFAULT_MAX_DURATION_S else None
    licenses = LICENSES_WITH_NC if filters.max_risk == "red" else LICENSES

    return [
        FreesoundQuery(
            query=text,
            licenses=licenses,
            duration_min_s=low,
            duration_max_s=high,
            music_like=True,
        )
        for text in list(texts.values())[:max_queries]
    ]
