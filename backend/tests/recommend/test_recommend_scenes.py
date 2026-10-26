"""Game scenes (M9): the label set, its synonyms, the parser hints, the UI intensity, the LLM
merge, the stored form of the filters and the tag scoring of scene labels."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from recommend_support import (
    MODEL_ID,
    FakeProvider,
    MapEmbedder,
    fake_llm_client,
    make_service,
    parse_reply,
)

from mcrar.catalog import CatalogRepository, NumpyVectorIndex
from mcrar.recommend import (
    SearchFilters,
    SearchRequest,
    Vocabulary,
    ZeroShotTagScorer,
    parse,
)
from mcrar.recommend.llm_parse import LLMParser, reply_schema, validate_reply
from mcrar.recommend.query import INTENSITY_ENERGY
from mcrar.recommend.ratings import filters_from_json, filters_to_json, query_key
from mcrar.recommend.request import build_filters
from mcrar.recommend.vocab import DEFAULT_SCENES, LABEL_SETS, SCENE

VOCAB = Vocabulary.default()


def run(text: str | None, **filters: object):  # noqa: ANN201
    return parse(SearchRequest(text=text, filters=SearchFilters(**filters)), VOCAB)  # type: ignore[arg-type]


# -- the label set ---------------------------------------------------------------------------


def test_the_scene_set_has_its_agreed_labels_and_display_names() -> None:
    assert SCENE in LABEL_SETS and len(DEFAULT_SCENES) == 14
    assert VOCAB.labels(SCENE) == tuple(DEFAULT_SCENES)
    assert VOCAB.display_name(SCENE, "boss") == "Boss fight"
    assert VOCAB.display_name(SCENE, "defeat") == "Defeat / game over"
    assert VOCAB.display_name(SCENE, "menu") == "Menu / title"
    assert VOCAB.display_name(SCENE, "combat") == "Combat"


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("battle", "combat"),
        ("fighting", "combat"),
        ("boss", "boss"),
        ("boss battle", "boss"),
        ("title screen", "menu"),
        ("main menu", "menu"),
        ("shop", "town"),
        ("village", "town"),
        ("puzzle", "puzzle"),
        ("sneaking", "stealth"),
        ("sneak", "stealth"),
        ("haunted", "horror"),
        ("triumph", "victory"),
        ("winning", "victory"),
        ("game over", "defeat"),
        ("losing", "defeat"),
        ("end credits", "credits"),
        ("cut scene", "cutscene"),
        ("cutscene", "cutscene"),
        ("escape", "chase"),
        ("escape sequence", "chase"),
        ("ambient", "ambient"),
        ("idle", "ambient"),
        ("explore", "exploration"),
        ("exploring", "exploration"),
        ("Menu / title", "menu"),
    ],
)
def test_scene_synonyms_resolve(text: str, label: str) -> None:
    assert label in VOCAB.match(text)[SCENE]
    assert VOCAB.resolve(SCENE, [text])[0] == label


def test_scary_words_point_at_a_mood_and_a_scene() -> None:
    for word in ("scary", "creepy"):
        found = VOCAB.match(word)
        assert found["moodtheme"] == ("dark",) and found[SCENE] == ("horror",)
    assert VOCAB.match("spooky")[SCENE] == ()  # spooky stays a mood only
    assert VOCAB.match("background music")[SCENE] == ()  # background is a mood label, not a scene
    assert VOCAB.match("adventure")[SCENE] == ()


def test_unknown_scene_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="unknown scene label 'karaoke'.*choose from: combat"):
        VOCAB.resolve(SCENE, ["karaoke"])


def _registry(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_a_registry_without_the_scene_set_keeps_the_default_scenes(tmp_path: Path) -> None:
    path = _registry(tmp_path, {"label_sets": {"genre": {"labels": ["jazz"]}}})
    vocab = Vocabulary.from_registry(path)
    assert vocab.labels(SCENE) == tuple(DEFAULT_SCENES)
    assert vocab.display_name(SCENE, "boss") == "Boss fight"
    assert vocab.match("boss fight")[SCENE][0] == "boss"


def test_a_registry_with_the_scene_set_wins(tmp_path: Path) -> None:
    scene = {"labels": ["boss", "lobby"], "display": {"lobby": "Lobby screen"}}
    vocab = Vocabulary.from_registry(_registry(tmp_path, {"label_sets": {SCENE: scene}}))
    assert vocab.labels(SCENE) == ("boss", "lobby")
    assert vocab.match("the lobby screen")[SCENE] == ("lobby",)
    assert vocab.match("a puzzle")[SCENE] == ()  # not in this registry's scene set


# -- the parser ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "scenes"),
    [
        ("boss fight", ("boss", "combat")),
        ("tense stealth level", ("stealth",)),
        ("victory jingle", ("victory",)),
        ("calm village theme", ("town",)),
        ("a creepy haunted hallway", ("horror",)),
        ("jazz cafe", ()),
    ],
)
def test_scene_hints(text: str, scenes: tuple[str, ...]) -> None:
    q = run(text)
    assert q.preferences.scene_hints == scenes
    if scenes:
        assert "scene: " + ", ".join(scenes) in q.notes


def test_a_victory_jingle_is_a_short_victory_track() -> None:
    q = run("victory jingle")
    assert q.preferences.scene_hints == ("victory",)
    assert q.filters.duration_max_s == 20.0
    assert q.semantic_text == "victory"


def test_scene_hints_are_requested_labels() -> None:
    q = run("boss fight", scenes=("menu",))
    assert q.requested_labels() == [(SCENE, "menu"), (SCENE, "boss"), (SCENE, "combat")]
    assert q.filters.scenes == ("menu",)  # the UI's scenes pass through the parser


# -- the intensity ---------------------------------------------------------------------------


@pytest.mark.parametrize(("intensity", "energy"), [("low", 0.25), ("mid", 0.5), ("high", 0.8)])
def test_the_intensity_sets_the_energy_target_and_beats_an_energy_word(
    intensity: str, energy: float
) -> None:
    assert INTENSITY_ENERGY[intensity] == energy
    q = run("calm piano", intensity=intensity)  # "calm" alone would say 0.3
    assert q.preferences.energy_target == pytest.approx(energy)
    assert q.filters.intensity == intensity
    assert any(intensity in note for note in q.notes if note.startswith("energy"))


def test_the_intensity_works_without_text() -> None:
    q = run(None, intensity="high")
    assert q.semantic_text is None and q.preferences.energy_target == pytest.approx(0.8)
    assert run("calm piano").preferences.energy_target == pytest.approx(0.3)  # no intensity


def test_the_intensity_ranks_by_energy_and_stays_in_the_parsed_filters(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = make_service(repo)
    loud = service.search(SearchRequest("", SearchFilters(intensity="high", max_risk="green")))
    quiet = service.search(SearchRequest("", SearchFilters(intensity="low", max_risk="green")))
    assert loud.items[0].energy is not None and quiet.items[0].energy is not None
    assert loud.items[0].energy > 0.6 > 0.35 > quiet.items[0].energy
    assert loud.parsed.filters.intensity == "high"


# -- building and storing filters ------------------------------------------------------------


def test_build_filters_resolves_scenes_and_checks_the_intensity() -> None:
    filters = build_filters(VOCAB, scenes=["Boss fight", "sneaking", "boss"], intensity="mid")
    assert filters == SearchFilters(scenes=("boss", "stealth"), intensity="mid")
    with pytest.raises(ValueError, match="unknown scene label 'karaoke'"):
        build_filters(VOCAB, scenes=["karaoke"])
    with pytest.raises(ValueError, match="intensity must be one of: low, mid, high"):
        build_filters(VOCAB, intensity="extreme")
    with pytest.raises(ValueError, match="--intensity must be one of"):
        build_filters(VOCAB, intensity="extreme", arg=lambda name: "--" + name)


def test_scenes_and_intensity_round_trip_through_the_stored_filters() -> None:
    filters = SearchFilters(scenes=("stealth", "boss"), intensity="high", genres=("rock",))
    stored = filters_to_json(filters)
    assert json.loads(stored) == {
        "genres": ["rock"],
        "intensity": "high",
        "scenes": ["boss", "stealth"],
    }
    assert filters_from_json(stored) == SearchFilters(
        scenes=("boss", "stealth"), intensity="high", genres=("rock",)
    )
    assert query_key(None, filters) == "filters:" + stored
    assert query_key(None, SearchFilters(intensity="low")) != query_key(
        None, SearchFilters(intensity="high")
    )
    assert filters_to_json(SearchFilters()) == "{}"


@pytest.mark.parametrize("text", ['{"scenes": "boss"}', '{"intensity": "extreme"}'])
def test_bad_stored_scenes_or_intensity_are_value_errors(text: str) -> None:
    with pytest.raises(ValueError):
        filters_from_json(text)


# -- the LLM parser --------------------------------------------------------------------------


def test_the_reply_schema_has_a_scenes_enum() -> None:
    schema = reply_schema(VOCAB)
    assert schema["properties"]["scenes"]["items"]["enum"] == list(DEFAULT_SCENES)
    assert "scenes" in schema["required"]


def test_replies_are_cleaned_for_scenes() -> None:
    reply = validate_reply(
        parse_reply(scenes=["Boss", "boss", "karaoke", "combat", "menu", "town"]), VOCAB
    )
    assert reply.scenes == ("boss", "combat", "menu")  # unknown dropped, capped at 3
    assert validate_reply({"scenes": "stealth"}, VOCAB).scenes == ("stealth",)
    assert validate_reply({}, VOCAB).scenes == ()


def test_the_llm_adds_scene_hints_to_the_rules_own() -> None:
    provider = FakeProvider(parse_reply(semantic_text="epic fight", scenes=["boss", "chase"]))
    parser = LLMParser(fake_llm_client(provider), 10.0)
    request = SearchRequest(text="battle music", filters=SearchFilters(scenes=("menu",)))
    parsed = parser.parse(request, VOCAB)
    assert parsed.source == "llm"
    assert parsed.filters.scenes == ("menu",)  # the UI's scenes are untouched
    assert parsed.preferences.scene_hints == ("combat", "boss", "chase")  # rules first
    assert "scene: Boss fight, Chase / escape (LLM)" in parsed.notes
    assert provider.calls[0]  # asked once, with the scenes in the schema
    assert parsed.requested_labels() == [
        (SCENE, "menu"),
        (SCENE, "combat"),
        (SCENE, "boss"),
        (SCENE, "chase"),
    ]


def test_the_ui_intensity_wins_over_the_llm_energy() -> None:
    provider = FakeProvider(parse_reply(semantic_text="quiet", energy=0.1))
    parser = LLMParser(fake_llm_client(provider), 10.0)
    request = SearchRequest(text="a track", filters=SearchFilters(intensity="high"))
    assert parser.parse(request, VOCAB).preferences.energy_target == pytest.approx(0.8)


# -- tag scoring -----------------------------------------------------------------------------


def test_top_tags_include_scene_labels(repo: CatalogRepository, ids: dict[str, int]) -> None:
    track, others = ids["Smooth Cafe"], [ids["Lullaby"], ids["Epic Quest"]]
    for n, track_id in enumerate([track, *others]):
        row = {"stealth": [0.9, 0.1, 0.2][n], "combat": [0.2, 0.3, 0.9][n]}
        repo.set_tag_probs(track_id, SCENE, "zeroshot", "scene-zeroshot-catalog@1", row)
    service, _ = make_service(repo)
    plain = service.search(SearchRequest("", SearchFilters(vocal="instrumental", max_risk="green")))
    item = next(i for i in plain.items if i.track_id == track)
    assert [(t.label_set, t.label) for t in item.top_tags][0] == (SCENE, "stealth")
    assert item.top_tags[0].display == "Stealth"
    asked = service.search(
        SearchRequest(
            "", SearchFilters(scenes=("stealth",), vocal="instrumental", max_risk="green")
        )
    )
    assert {t.label_set for i in asked.items for t in i.top_tags} == {SCENE}
    asked_item = next(i for i in asked.items if i.track_id == track)
    assert asked_item.breakdown["tags"]["weight"] > 0
    assert asked_item.explanation and "tags stealth 0." in asked_item.explanation


def test_the_zero_shot_fallback_describes_a_scene_as_game_music(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    embedder = MapEmbedder()
    index = NumpyVectorIndex.from_repository(repo, MODEL_ID)
    scorer = ZeroShotTagScorer(lambda: index, embedder.embed_text, VOCAB)
    scorer.scores(list(ids.values()), SCENE, ["boss", "menu"])
    scorer.scores(list(ids.values()), "genre", ["jazz"])
    assert embedder.calls[0] == [
        "video game music for Boss fight",
        "video game music for Menu / title",
    ]
    assert embedder.calls[1] == ["Jazz music"]
