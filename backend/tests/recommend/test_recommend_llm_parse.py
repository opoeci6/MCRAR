"""The LLM query parser: validation, merging into the rule result, the cache, the fallback."""

from __future__ import annotations

from typing import Any

import pytest
from recommend_support import (
    QUERY_TEXTS,
    FakeProvider,
    MapEmbedder,
    fake_llm_client,
    llm_settings,
    parse_reply,
)

from mcrar.catalog import CatalogRepository
from mcrar.llm.base import (
    LLMAuthError,
    LLMInvalidReply,
    LLMNotConfigured,
    LLMRateLimited,
    LLMTimeout,
)
from mcrar.recommend import (
    ParsedQuery,
    SearchFilters,
    SearchRequest,
    SearchService,
    StoredTagScorer,
    Vocabulary,
)
from mcrar.recommend.llm_parse import (
    FAILURE_TTL_S,
    PROMPT_VERSION,
    LLMParser,
    reply_schema,
    validate_reply,
)

VOCAB = Vocabulary.default()


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def parser_for(provider: FakeProvider, clock: Clock | None = None, **llm: Any) -> LLMParser:
    return LLMParser(fake_llm_client(provider, **llm), 10.0, clock=clock or Clock())


def parse(
    reply: Any,
    text: str | None = "a query",
    filters: SearchFilters | None = None,
    **kw: Any,
) -> ParsedQuery:
    parser = parser_for(FakeProvider(reply))
    request = SearchRequest(text=text, filters=filters or SearchFilters(), **kw)
    return parser.parse(request, VOCAB)


# -- validation ------------------------------------------------------------------------------


def test_reply_is_cleaned_and_clamped() -> None:
    reply = validate_reply(
        parse_reply(
            semantic_text="  dark   brooding strings  ",
            genres=["Jazz", "jazz", "klingon", "rock", "pop", "blues"],
            moods=["dark", "nope"],
            energy=7,
            bpm_target=900,
            vocal="Instrumental",
            search_terms=["  Lo-Fi  ", "x" * 41, "", "jpop", "JPOP", "a", "b", "c", "d"],
        ),
        VOCAB,
    )
    assert reply.semantic_text == "dark brooding strings"
    assert reply.genres == ("jazz", "rock", "pop")  # unknown dropped, capped at 3
    assert reply.moods == ("dark",)
    assert (reply.energy, reply.bpm_target, reply.vocal) == (1.0, 250.0, "instrumental")
    assert reply.search_terms == ("lo-fi", "jpop", "a", "b", "c")  # capped at 5, too-long dropped


def test_low_values_are_clamped_and_text_is_capped() -> None:
    reply = validate_reply(parse_reply(semantic_text="w " * 400, energy=-3, bpm_target=1), VOCAB)
    assert reply.energy == 0.0 and reply.bpm_target == 40.0
    assert reply.semantic_text is not None and len(reply.semantic_text) <= 300


@pytest.mark.parametrize(
    ("low", "high", "expected"),
    [
        (-5, 60, (None, 60.0)),
        (30, 10, (None, None)),
        (None, 0, (None, None)),
        (10, 60, (10.0, 60.0)),
        (None, 90, (None, 90.0)),
        ("20", None, (20.0, None)),
    ],
)
def test_nonsensical_durations_are_dropped(low: Any, high: Any, expected: Any) -> None:
    reply = validate_reply(parse_reply(duration_min_s=low, duration_max_s=high), VOCAB)
    assert (reply.duration_min_s, reply.duration_max_s) == expected


def test_wrong_types_drop_only_that_field() -> None:
    reply = validate_reply(
        {
            "semantic_text": 5,
            "genres": "pop",
            "moods": {"a": 1},
            "energy": "high",
            "bpm_target": True,
            "vocal": "maybe",
            "duration_min_s": float("nan"),
            "search_terms": ["ok", 3, None],
            "extra": "ignored",
        },
        VOCAB,
    )
    assert reply.semantic_text is None and reply.genres == ("pop",) and reply.moods == ()
    assert reply.energy is None and reply.bpm_target is None and reply.vocal is None
    assert reply.duration_min_s is None and reply.search_terms == ("ok",)


def test_schema_is_strict_compatible() -> None:
    schema = reply_schema(VOCAB)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["properties"]["genres"]["items"]["enum"] == list(VOCAB.labels("genre"))
    assert schema["properties"]["moods"]["items"]["enum"] == list(VOCAB.labels("moodtheme"))
    text = repr(schema)
    for keyword in ("minItems", "maxItems", "minimum", "maximum", "maxLength"):
        assert keyword not in text


# -- merging ---------------------------------------------------------------------------------


def test_the_llm_result_is_merged_into_the_rules() -> None:
    parsed = parse(
        parse_reply(
            semantic_text="tense stealth music",
            genres=["electronic"],
            moods=["dark"],
            energy=0.8,
            bpm_target=120,
            vocal="instrumental",
            duration_max_s=100,
            search_terms=["stealth", "dark ambient"],
        ),
        text="something creepy",
    )
    assert parsed.source == "llm"
    assert parsed.semantic_text == "tense stealth music"
    assert parsed.preferences.genre_hints == ("electronic",)
    assert parsed.preferences.mood_hints == ("dark",)  # the rules found "creepy" -> dark, too
    assert parsed.preferences.energy_target == 0.8
    assert parsed.preferences.bpm_target == 120
    assert parsed.filters.vocal == "instrumental"
    assert (parsed.filters.duration_min_s, parsed.filters.duration_max_s) == (None, 100)
    assert parsed.search_terms == ("stealth", "dark ambient")
    assert 'understood as "tense stealth music"' in parsed.notes
    for note in (
        "genre: Electronic (LLM)",
        "mood: Dark (LLM)",
        "energy preference 0.80 (LLM)",
        "tempo preference ~120 BPM (LLM)",
        "instrumental only (LLM)",
        "duration ≤ 100 s (LLM)",
    ):
        assert note in parsed.notes


def test_rule_notes_come_first_and_hints_are_merged_rules_first() -> None:
    parsed = parse(
        parse_reply(semantic_text="calm piano", genres=["classical", "jazz"], moods=["calm"]),
        text="jazz at 90-100 bpm",
    )
    assert parsed.notes[0] == "BPM 90-100"
    assert "genre: jazz" in parsed.notes  # the rule parser's own note
    assert parsed.preferences.genre_hints == ("jazz", "classical")
    assert parsed.preferences.mood_hints == ("calm",)
    assert (parsed.filters.bpm_min, parsed.filters.bpm_max) == (90, 100)


def test_ui_filters_win_and_the_licence_is_never_changed() -> None:
    ui = SearchFilters(
        max_risk="green",
        vocal="vocal",
        bpm_min=80,
        bpm_max=100,
        duration_min_s=60,
        duration_max_s=120,
        sources=("jamendo",),
        genres=("rock",),
    )
    parsed = parse(
        parse_reply(
            semantic_text="x",
            vocal="instrumental",
            bpm_target=150,
            duration_min_s=5,
            duration_max_s=10,
        ),
        filters=ui,
    )
    assert parsed.filters == ui
    assert parsed.preferences.bpm_target is None  # a BPM filter is set


def test_rule_cues_win_over_the_llm() -> None:
    parsed = parse(
        parse_reply(semantic_text="x", energy=0.9, bpm_target=70),
        text="calm and slow music, no vocals, under 2 minutes",
    )
    assert parsed.preferences.energy_target == 0.3  # "calm" (rules)
    assert parsed.preferences.bpm_target == 75  # "slow" (rules)
    assert parsed.filters.vocal == "instrumental"
    assert parsed.filters.duration_max_s == 120


def test_a_bpm_filter_from_the_text_blocks_the_llm_target() -> None:
    parsed = parse(parse_reply(semantic_text="x", bpm_target=70), text="boss fight 140-160 bpm")
    assert parsed.preferences.bpm_target is None
    assert (parsed.filters.bpm_min, parsed.filters.bpm_max) == (140, 160)


def test_an_empty_semantic_text_keeps_the_rules_text() -> None:
    parsed = parse(parse_reply(genres=["pop"]), text="  some   upbeat tune ")
    assert parsed.semantic_text == "upbeat tune"
    assert not any(n.startswith("understood as") for n in parsed.notes)
    assert parsed.source == "llm" and parsed.preferences.genre_hints == ("pop",)


def test_the_request_without_text_makes_no_call() -> None:
    provider = FakeProvider(parse_reply(semantic_text="x"))
    parser = parser_for(provider)
    filters = SearchFilters(vocal="vocal")
    for text in (None, "", "   "):
        parsed, use = parser.parse_with_info(SearchRequest(text=text, filters=filters), VOCAB)
        assert use is None and parsed.source == "rules" and parsed.filters == filters
    assert provider.calls == []


def test_the_prompt() -> None:
    provider = FakeProvider(parse_reply())
    parser = parser_for(provider)
    parser.parse(
        SearchRequest(text="  Música TRISTE, 90-100 bpm ", filters=SearchFilters(genres=("pop",))),
        VOCAB,
    )
    (call,) = provider.calls
    system, user = call["messages"]
    assert system["role"] == "system" and "English" in system["content"]
    assert user["role"] == "user"
    assert user["content"].startswith("Search: Música TRISTE, 90-100 bpm\n")
    assert "BPM 90 to 100" in user["content"] and "genres Pop" in user["content"]
    assert call["name"] == "search_query" and call["timeout_s"] == 10.0
    assert 0 < call["max_tokens"] <= 2000


# -- cache -----------------------------------------------------------------------------------


def test_second_identical_search_is_cached_and_the_merge_uses_the_current_filters() -> None:
    provider = FakeProvider(parse_reply(semantic_text="tense", vocal="instrumental"))
    parser = parser_for(provider)
    request = SearchRequest(text="  Stealth ")
    first, use1 = parser.parse_with_info(request, VOCAB)
    again, use2 = parser.parse_with_info(SearchRequest(text="stealth", offset=40), VOCAB)
    assert len(provider.calls) == 1
    assert (use1.cached, use2.cached) == (False, True)  # type: ignore[union-attr]
    assert use2.used and use2.model == "fake-model"  # type: ignore[union-attr]
    assert first == again
    # other filters are another question for the model, so they are another cache entry
    other, _ = parser.parse_with_info(
        SearchRequest(text="stealth", filters=SearchFilters(vocal="vocal")), VOCAB
    )
    assert len(provider.calls) == 2 and other.filters.vocal == "vocal"
    assert PROMPT_VERSION >= 1


def test_the_cache_is_keyed_by_model() -> None:
    provider = FakeProvider(parse_reply(semantic_text="tense"))
    request = SearchRequest(text="stealth")
    client = fake_llm_client(provider)
    parser = LLMParser(client, 10.0)
    parser.parse(request, VOCAB)
    parser.parse(request, VOCAB)
    assert len(provider.calls) == 1
    client._settings = llm_settings(model="another")  # the saved model changed
    parser.parse(request, VOCAB)
    assert len(provider.calls) == 2


def test_a_failure_is_remembered_for_a_minute() -> None:
    clock = Clock()
    provider = FakeProvider(LLMTimeout("Timed out after 10 s."))
    parser = parser_for(provider, clock)
    request = SearchRequest(text="stealth")
    parsed, use = parser.parse_with_info(request, VOCAB)
    assert use is not None and not use.used
    clock.now += FAILURE_TTL_S - 1
    parser.parse(request, VOCAB)
    assert len(provider.calls) == 1
    clock.now += 2
    provider.reply = parse_reply(semantic_text="tense")
    parsed, use = parser.parse_with_info(request, VOCAB)
    assert len(provider.calls) == 2 and use is not None and use.used and not use.cached
    assert parsed.source == "llm"
    parser.parse(request, VOCAB)
    assert len(provider.calls) == 2  # the success is cached for good


def test_not_configured_is_not_remembered() -> None:
    provider = FakeProvider(parse_reply(semantic_text="tense"))
    client = fake_llm_client(provider, preset="openai", model="")  # no key, no secret store
    parser = LLMParser(client, 10.0)
    request = SearchRequest(text="stealth")
    parsed, use = parser.parse_with_info(request, VOCAB)
    assert use is not None and not use.used and "API key" in (use.error or "")
    assert parsed.notes == [
        "scene: stealth",  # the rules' own hint stays
        "LLM unavailable (not configured); used the rule parser.",
    ]
    assert provider.calls == []


def test_cache_is_bounded() -> None:
    provider = FakeProvider(parse_reply(semantic_text="tense"))
    parser = parser_for(provider)
    for n in range(300):
        parser.parse(SearchRequest(text=f"query {n}"), VOCAB)
    assert len(parser._cache) == 256
    parser.parse(SearchRequest(text="query 0"), VOCAB)  # evicted: asked again
    assert len(provider.calls) == 301


# -- fallback --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "note"),
    [
        (
            LLMAuthError("Authentication failed (HTTP 401). Check the API key."),
            "LLM: authentication failed; check the API key in Settings. Used the rule parser.",
        ),
        (LLMTimeout("Timed out after 10 s."), "LLM: timed out after 10 s; used the rule parser."),
        (
            LLMInvalidReply("The model's reply was empty."),
            "LLM unavailable (invalid reply); used the rule parser.",
        ),
        (
            LLMRateLimited("slow down (HTTP 429)."),
            "LLM unavailable (rate limited); used the rule parser.",
        ),
    ],
)
def test_failures_fall_back_to_the_rules_with_a_note(error: Exception, note: str) -> None:
    parser = parser_for(FakeProvider(error))
    request = SearchRequest(text="boss battle, no vocals")
    parsed, use = parser.parse_with_info(request, VOCAB)
    assert use is not None and not use.used and use.error == str(error) and not use.cached
    assert parsed.source == "rules" and parsed.search_terms == ()
    assert parsed.filters.vocal == "instrumental"  # the rule result is intact
    assert parsed.notes[-1] == note


def test_fallback_for_a_provider_that_cannot_be_built() -> None:
    from mcrar.llm.client import LLMClient

    def factory(*args: Any) -> Any:
        raise LLMNotConfigured("No API key is set for Fake.")

    client = LLMClient(llm_settings(), None, provider_factory=factory)
    parsed, use = LLMParser(client, 10).parse_with_info(SearchRequest(text="x y"), VOCAB)
    assert use is not None and use.error == "No API key is set for Fake."
    assert parsed.source == "rules"


def test_the_provider_is_closed_after_each_call() -> None:
    provider = FakeProvider(parse_reply())
    parser_for(provider).parse(SearchRequest(text="x y"), VOCAB)
    assert provider.closed == 1


# -- in the search service ---------------------------------------------------------------------


def llm_service(
    repo: CatalogRepository, provider: FakeProvider, embedder: MapEmbedder | None = None
) -> tuple[SearchService, MapEmbedder]:
    embedder = embedder or MapEmbedder(QUERY_TEXTS)
    client = fake_llm_client(provider)
    service = SearchService(
        repo,
        client.settings,
        embedder_loader=lambda: embedder,
        stored_tags=StoredTagScorer(repo),
        parser=LLMParser(client, 10.0),
    )
    return service, embedder


def test_a_non_english_query_is_embedded_as_the_llms_english_text(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    provider = FakeProvider(
        parse_reply(semantic_text="tense stealth level", search_terms=["stealth"])
    )
    service, embedder = llm_service(repo, provider)
    result = service.search(SearchRequest(text="niveau d'infiltration tendu", limit=3))
    assert ["tense stealth level"] in embedder.calls
    assert result.items[0].title in {"Shadow Walk", "Quiet Vents", "Night Heist"}
    assert result.parsed.source == "llm" and result.parsed.semantic_text == "tense stealth level"
    assert result.llm is not None and result.llm.used and not result.llm.cached
    assert result.to_dict()["llm"] == {
        "used": True,
        "model": "fake-model",
        "cached": False,
        "error": None,
    }
    assert result.to_dict()["parsed"]["search_terms"] == ("stealth",)
    assert result.to_dict()["rerank"] is None
    assert all(i.llm_rank is None and i.llm_explanation is None for i in result.items)
    # load more: same query, other offset, no second call
    more = service.search(SearchRequest(text="niveau d'infiltration tendu", limit=3, offset=3))
    assert len(provider.calls) == 1 and more.llm is not None and more.llm.cached


def test_a_failing_llm_still_returns_the_rule_search(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = llm_service(repo, FakeProvider(LLMTimeout("Timed out after 10 s.")))
    result = service.search(SearchRequest(text="tense stealth level", limit=3))
    assert result.items and result.parsed.source == "rules"
    assert result.llm is not None and not result.llm.used
    assert "LLM: timed out after 10 s; used the rule parser." in result.parsed.notes


def test_a_filter_only_search_has_no_llm_block(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    provider = FakeProvider(parse_reply())
    service, _ = llm_service(repo, provider)
    result = service.search(SearchRequest(filters=SearchFilters(vocal="vocal")))
    assert result.llm is None and provider.calls == []


def test_service_parse_carries_the_search_terms(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = llm_service(
        repo, FakeProvider(parse_reply(semantic_text="x", search_terms=["jpop"]))
    )
    assert service.parse(SearchRequest(text="anime opening")).search_terms == ("jpop",)
