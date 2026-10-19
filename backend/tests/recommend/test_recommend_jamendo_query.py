"""The Jamendo searches built from a text query (no network)."""

from __future__ import annotations

import pytest

from mcrar.ingest import JamendoQuery
from mcrar.recommend import SearchFilters
from mcrar.recommend.jamendo_query import content_words, jamendo_queries, normalise


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Tense   Stealth", "tense stealth"),
        ("j-pop", "jpop"),
        ("K-Pop vocals", "kpop vocals"),
        ("8-bit boss battle", "8bit boss battle"),
        ("lo-fi", "lofi"),
        ("hip-hop", "hiphop"),
        ("sci-fi", "scifi"),
        ("post-rock", "postrock"),
        ("high-energy", "high-energy"),  # a half is longer than 4 characters
        ("j pop", "jpop"),
        ("a dark cave", "a dark cave"),  # the article is not joined to the next word
        ("tense stealth j", "tense stealth j"),  # nothing follows the letter
        ("sci-fi-ish", "sci-fi-ish"),  # only two-part compounds are joined
        ("-", "-"),
    ],
)
def test_normalise(text: str, expected: str) -> None:
    assert normalise(text) == expected


def test_content_words_drop_stopwords_short_and_repeated_words() -> None:
    words = content_words(normalise("a tense stealth game level, 8-bit boss and the boss"))
    assert words == ["tense", "stealth", "8bit", "boss"]
    assert content_words("the music of a game") == []
    assert content_words("go on to 3d") == ["3d"]  # a digit keeps a short token


def test_text_gives_the_normalised_search_then_the_original_then_fuzzy_tags() -> None:
    assert jamendo_queries("j-pop dance", SearchFilters()) == [
        JamendoQuery(search="jpop dance", order="relevance"),
        JamendoQuery(search="j-pop dance", order="relevance"),
        JamendoQuery(fuzzytags=["jpop", "dance"]),
    ]


def test_an_unchanged_text_is_not_searched_twice() -> None:
    queries = jamendo_queries("Tense  stealth", SearchFilters())
    assert queries == [
        JamendoQuery(search="tense stealth", order="relevance"),
        JamendoQuery(fuzzytags=["tense", "stealth"]),
    ]


def test_without_content_words_there_is_no_fuzzytags_query() -> None:
    assert jamendo_queries("the music", SearchFilters()) == [
        JamendoQuery(search="the music", order="relevance")
    ]


def test_blank_text_gives_no_queries() -> None:
    assert jamendo_queries("   ", SearchFilters()) == []


def test_the_filters_jamendo_can_apply_go_on_every_query() -> None:
    filters = SearchFilters(
        vocal="instrumental", duration_min_s=60.5, duration_max_s=240.2, max_risk="green"
    )
    queries = jamendo_queries("lo-fi beats", filters)
    assert len(queries) == 3
    for query in queries:
        assert query.vocalinstrumental == "instrumental"
        assert query.duration_between == (60, 241)  # floored, ceiled
        assert query.commercial_only is True
    kwargs = queries[0].to_kwargs()
    assert kwargs == {
        "search": "lofi beats",
        "order": "relevance",
        "vocalinstrumental": "instrumental",
        "duration_between": (60, 241),
        "commercial_only": True,
    }


@pytest.mark.parametrize(
    ("low", "high", "expected"),
    [(120.0, None, (120, 3600)), (None, 90.0, (0, 90)), (None, None, None)],
)
def test_an_open_duration_end_is_filled_in(
    low: float | None, high: float | None, expected: tuple[int, int] | None
) -> None:
    filters = SearchFilters(duration_min_s=low, duration_max_s=high)
    assert jamendo_queries("calm", filters)[0].duration_between == expected


@pytest.mark.parametrize("risk", ["amber", "red", "unknown"])
def test_only_green_asks_for_commercial_licences(risk: str) -> None:
    queries = jamendo_queries("calm", SearchFilters(max_risk=risk))  # type: ignore[arg-type]
    assert all(not q.commercial_only for q in queries)
    assert "commercial_only" not in queries[0].to_kwargs()


def test_filters_without_a_jamendo_equivalent_are_ignored() -> None:
    filters = SearchFilters(bpm_min=100, bpm_max=120, genres=("rock",), sources=("local",))
    assert jamendo_queries("calm", filters) == jamendo_queries("calm", SearchFilters())


def test_extra_terms_are_their_own_searches_first_and_keep_the_filters() -> None:
    filters = SearchFilters(vocal="vocal", max_risk="green")
    queries = jamendo_queries("j-pop dance", filters, ["anime", "  J  Rock ", "jpop dance", ""])
    common = {"vocalinstrumental": "vocal", "commercial_only": True}
    assert queries == [
        JamendoQuery(search="anime", order="relevance", **common),
        JamendoQuery(search="J Rock", order="relevance", **common),
        JamendoQuery(search="jpop dance", order="relevance", **common),  # not repeated
        JamendoQuery(search="j-pop dance", order="relevance", **common),
        JamendoQuery(fuzzytags=["jpop", "dance"], **common),
    ]


def test_without_extra_terms_nothing_changes() -> None:
    assert jamendo_queries("calm", SearchFilters(), ()) == jamendo_queries("calm", SearchFilters())
