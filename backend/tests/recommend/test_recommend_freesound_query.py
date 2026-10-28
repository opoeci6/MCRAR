"""The Freesound searches built from a text query (no network)."""

from __future__ import annotations

from mcrar.ingest import FreesoundQuery
from mcrar.recommend import SearchFilters
from mcrar.recommend.freesound_query import freesound_queries


def _texts(queries: list[FreesoundQuery]) -> list[str]:
    return [q.query for q in queries]


def test_the_semantic_text_alone_is_one_music_like_query_with_the_default_licences() -> None:
    assert freesound_queries("tense  stealth level", SearchFilters()) == [
        FreesoundQuery(
            query="tense stealth level",
            licenses=("cc0", "by"),
            duration_min_s=10.0,
            duration_max_s=600.0,
            music_like=True,
        )
    ]


def test_keywords_come_first_then_the_semantic_text() -> None:
    queries = freesound_queries("tense stealth level", SearchFilters(), ["dark ambient", "drone"])
    assert _texts(queries) == ["dark ambient", "drone", "tense stealth level"]


def test_repeats_are_left_out_ignoring_case_and_spacing() -> None:
    queries = freesound_queries(
        "Dark  Cave", SearchFilters(), ["dark cave", "Drone", "drone ", "  ", ""]
    )
    assert _texts(queries) == ["Drone", "Dark Cave"]


def test_at_most_three_queries_and_the_semantic_text_keeps_its_slot() -> None:
    queries = freesound_queries("tense level", SearchFilters(), ["a", "b", "c", "d"])
    assert _texts(queries) == ["a", "b", "tense level"]
    assert len(freesound_queries("x", SearchFilters(), list("abcdef"), max_queries=2)) == 2
    assert _texts(freesound_queries("x", SearchFilters(), ["a"], max_queries=1)) == ["x"]


def test_no_text_means_no_queries() -> None:
    assert freesound_queries("  ", SearchFilters()) == []
    assert _texts(freesound_queries("", SearchFilters(), ["drone"])) == ["drone"]


def test_licences_add_non_commercial_only_when_red_is_allowed_explicitly() -> None:
    for risk in ("green", "amber", "unknown"):
        (query,) = freesound_queries("calm", SearchFilters(max_risk=risk))  # type: ignore[arg-type]
        assert tuple(query.licenses) == ("cc0", "by"), risk
    (query,) = freesound_queries("calm", SearchFilters(max_risk="red"))
    assert tuple(query.licenses) == ("cc0", "by", "by-nc")


def test_durations_follow_the_filter_but_never_start_below_ten_seconds() -> None:
    def bounds(**kwargs: float) -> tuple[float | None, float | None]:
        (query,) = freesound_queries("calm", SearchFilters(**kwargs))  # type: ignore[arg-type]
        return query.duration_min_s, query.duration_max_s

    assert bounds() == (10.0, 600.0)
    assert bounds(duration_min_s=60, duration_max_s=240) == (60.0, 240.0)
    assert bounds(duration_max_s=3) == (10.0, 10.0)  # below the floor: the floor
    assert bounds(duration_min_s=2, duration_max_s=120) == (10.0, 120.0)
    assert bounds(duration_min_s=120) == (120.0, 600.0)  # only a minimum: the default maximum
    assert bounds(duration_min_s=900) == (900.0, None)  # a minimum past it: open-ended
    assert bounds(duration_max_s=1800) == (10.0, 1800.0)
