"""The rating query key and the stored form of the filters."""

from __future__ import annotations

import pytest

from mcrar.recommend import SearchFilters, Vocabulary
from mcrar.recommend.ratings import (
    filters_from_json,
    filters_to_json,
    normalise_text,
    query_key,
)
from mcrar.recommend.request import build_filters

VOCAB = Vocabulary.default()


def test_text_keys_ignore_case_and_whitespace() -> None:
    expected = "text:tense stealth level, no vocals"
    for text in (
        "tense stealth level, no vocals",
        "  Tense   Stealth LEVEL,\tno vocals \n",
    ):
        assert query_key(text, SearchFilters()) == expected


def test_text_keys_ignore_the_filters() -> None:
    narrow = SearchFilters(max_risk="green", vocal="instrumental", bpm_min=80.0)
    assert query_key("epic battle", narrow) == query_key("epic battle", SearchFilters())


def test_different_words_are_different_queries() -> None:
    assert query_key("epic battle", SearchFilters()) != query_key("epic boss", SearchFilters())


def test_filter_only_keys_are_canonical_json_of_the_set_fields() -> None:
    filters = SearchFilters(max_risk="green", bpm_min=100.0, genres=("rock", "jazz"))
    key = query_key("   ", filters)
    assert key == 'filters:{"bpm_min":100,"genres":["jazz","rock"],"max_risk":"green"}'
    assert query_key(None, filters) == key
    reordered = SearchFilters(genres=("jazz", "rock"), bpm_min=100, max_risk="green")
    assert query_key(None, reordered) == key


def test_filter_only_keys_use_resolved_label_ids_so_synonyms_match() -> None:
    by_synonym = build_filters(VOCAB, genres=["rap"])
    by_id = build_filters(VOCAB, genres=["hip-hop"])
    assert by_synonym == by_id
    assert query_key(None, by_synonym) == query_key(None, by_id)
    assert query_key(None, build_filters(VOCAB, moods=["spooky"])) != query_key(None, by_id)


def test_an_empty_query_has_no_key() -> None:
    for text in (None, "", "  \n"):
        with pytest.raises(ValueError, match="search text or at least one filter"):
            query_key(text, SearchFilters())


def test_normalise_text() -> None:
    assert normalise_text("  A   b ") == "A b"
    assert normalise_text("   ") is None and normalise_text(None) is None


def test_filters_round_trip_through_json() -> None:
    assert filters_to_json(SearchFilters()) == "{}"
    filters = SearchFilters(
        max_risk="amber",
        vocal="vocal",
        bpm_min=80.5,
        bpm_max=120.0,
        duration_max_s=30.0,
        sources=("local", "jamendo"),
        genres=("rock",),
        moods=("dark", "calm"),
    )
    again = filters_from_json(filters_to_json(filters))
    assert again == SearchFilters(
        max_risk="amber",
        vocal="vocal",
        bpm_min=80.5,
        bpm_max=120.0,
        duration_max_s=30.0,
        sources=("jamendo", "local"),  # lists are stored sorted
        genres=("rock",),
        moods=("calm", "dark"),
    )
    assert filters_to_json(again) == filters_to_json(filters)


@pytest.mark.parametrize(
    "text", ["not json", "[]", '{"nope": 1}', '{"genres": "rock"}', '{"sources": null}']
)
def test_bad_stored_filters_are_value_errors(text: str) -> None:
    with pytest.raises(ValueError):
        filters_from_json(text)
