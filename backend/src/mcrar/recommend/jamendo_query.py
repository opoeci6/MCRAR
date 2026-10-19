"""Jamendo searches for a text query: what to ask Jamendo so it returns tracks worth ranking.

Jamendo's ``search=`` is a full-text search over track names and tags and works well for
descriptive text ("tense stealth", "8-bit boss battle"). Short hyphenated compounds are the
exception: "j-pop" returns generic pop while "jpop" returns J-pop, so they are joined first. There
is no usable lyrics-language filter, so none is sent.

:func:`jamendo_queries` returns up to three queries, tried in order until enough new tracks were
found (:func:`mcrar.ingest.pipeline.ingest_jamendo_queries`): the normalised text, the original
text (when it differs), then the content words as ``fuzzytags``. The hard filters that Jamendo
can apply (vocal/instrumental, duration, a commercial licence) go on every query; the rest of the
search filters (BPM, genre, mood) only exist in the catalog. Keywords from the LLM parser come
first, one query each.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from mcrar.ingest.pipeline import JamendoQuery

if TYPE_CHECKING:
    from mcrar.recommend.query import SearchFilters

ORDER = "relevance"
JOIN_MAX_CHARS = 4  # both halves of a hyphenated compound at most this long: "lo-fi", "j-pop"
MAX_DURATION_S = 3600  # the open end of a duration range for Jamendo's ``durationbetween``
MAX_FUZZYTAGS = 10
MIN_WORD_CHARS = 3
# Words that say nothing about the music (or are too generic to be a tag).
STOPWORDS = frozenset(
    "a an the and or for with of in on to my some music song songs track tracks sound sounds "
    "theme level game vibe vibes style like".split()
)
_WORD = re.compile(r"[a-z0-9]+")


def _join_hyphenated(token: str) -> str:
    parts = token.split("-")
    if len(parts) == 2 and all(0 < len(p) <= JOIN_MAX_CHARS for p in parts):
        return "".join(parts)
    return token


def normalise(text: str) -> str:
    """Lowercase, collapsed whitespace, "j-pop" and "j pop" as "jpop" (see the module docstring).

    A single letter is joined with the next word, except the article "a" ("a tense cue" stays).
    """
    tokens = [_join_hyphenated(t) for t in text.lower().split()]
    out: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if len(token) == 1 and token.isalpha() and token not in STOPWORDS and i + 1 < len(tokens):
            token += tokens[i + 1]
            i += 1
        out.append(token)
        i += 1
    return " ".join(out)


def content_words(normalised: str) -> list[str]:
    """The distinct words of ``normalised`` that can be tags: no stopwords, at least
    ``MIN_WORD_CHARS`` characters or a digit."""
    words: dict[str, None] = {}
    for word in _WORD.findall(normalised):
        if word not in STOPWORDS and (
            len(word) >= MIN_WORD_CHARS or any(c.isdigit() for c in word)
        ):
            words[word] = None
    return list(words)[:MAX_FUZZYTAGS]


def jamendo_queries(
    semantic_text: str, filters: SearchFilters, extra_terms: Sequence[str] = ()
) -> list[JamendoQuery]:
    """The Jamendo searches for ``semantic_text`` under ``filters``, most specific first.

    ``extra_terms`` (keywords the LLM parser suggests) each become their own ``search=`` query
    ahead of the others; one that repeats another query's search is left out.
    """
    original = " ".join(semantic_text.split())
    if not original:
        return []
    normalised = normalise(original)

    common: dict[str, Any] = {}
    if filters.vocal:
        common["vocalinstrumental"] = filters.vocal
    if filters.duration_min_s is not None or filters.duration_max_s is not None:
        low = 0 if filters.duration_min_s is None else math.floor(filters.duration_min_s)
        high = (
            MAX_DURATION_S if filters.duration_max_s is None else math.ceil(filters.duration_max_s)
        )
        common["duration_between"] = (low, max(high, low))
    if filters.max_risk == "green":
        common["commercial_only"] = True

    queries = [JamendoQuery(search=normalised, order=ORDER, **common)]
    if original.lower() != normalised:
        queries.append(JamendoQuery(search=original, order=ORDER, **common))
    words = content_words(normalised)
    if words:
        queries.append(JamendoQuery(fuzzytags=words, **common))
    seen = {q.search for q in queries if q.search}
    terms: list[JamendoQuery] = []
    for term in extra_terms:
        term = " ".join(term.split())
        if term and term not in seen:
            seen.add(term)
            terms.append(JamendoQuery(search=term, order=ORDER, **common))
    return terms + queries
