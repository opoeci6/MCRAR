"""The rule parser: every phrasing of every hard constraint, soft cues, stripping, merging."""

from __future__ import annotations

import pytest

from mcrar.recommend import (
    ParsedQuery,
    RuleParser,
    SearchFilters,
    SearchRequest,
    Vocabulary,
    parse,
)

VOCAB = Vocabulary.default()


def run(text: str | None, **filters: object) -> ParsedQuery:
    return parse(SearchRequest(text=text, filters=SearchFilters(**filters)), VOCAB)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("text", "bpm_min", "bpm_max", "left"),
    [
        ("120 bpm", 110, 130, None),
        ("synthwave 120 BPM", 110, 130, "synthwave"),
        ("around 100 bpm", 90, 110, None),
        ("about 100 bpm chase", 90, 110, "chase"),
        ("~100 bpm chase", 90, 110, "chase"),
        ("chase ~ 100bpm", 90, 110, "chase"),
        ("80-100 bpm", 80, 100, None),
        ("80 - 100 bpm", 80, 100, None),
        ("80 to 100 bpm", 80, 100, None),
        ("80 bpm to 100 bpm", 80, 100, None),
        ("between 80 and 100 bpm", 80, 100, None),
        ("100-80 bpm", 80, 100, None),  # reversed bounds are put in order
        ("under 90 bpm", None, 90, None),
        ("below 90 bpm sneaking", None, 90, "sneaking"),
        ("less than 90 bpm", None, 90, None),
        ("slower than 90 bpm", None, 90, None),
        ("< 90 bpm", None, 90, None),
        ("<90bpm", None, 90, None),
        ("over 140 bpm", 140, None, None),
        ("above 140 bpm", 140, None, None),
        ("more than 140 bpm", 140, None, None),
        ("faster than 140 bpm", 140, None, None),
        ("> 140 bpm", 140, None, None),
        ("over 80 bpm and under 100 bpm", 80, 100, None),
        ("UNDER 90 BPM", None, 90, None),
    ],
)
def test_bpm_phrases(
    text: str, bpm_min: float | None, bpm_max: float | None, left: str | None
) -> None:
    q = run(text)
    assert (q.filters.bpm_min, q.filters.bpm_max) == (bpm_min, bpm_max)
    assert q.semantic_text == left
    assert any(n.startswith("BPM") for n in q.notes)


def test_bpm_notes_are_readable() -> None:
    assert run("under 100 bpm").notes == ["BPM ≤ 100"]
    assert run("over 100 bpm").notes == ["BPM ≥ 100"]
    assert run("80-100 bpm").notes == ["BPM 80-100"]
    assert run("100 bpm").notes == ["BPM around 100 (90-110)"]


@pytest.mark.parametrize(
    "text",
    [
        "no vocals",
        "without vocals",
        "no vocal",
        "no singing",
        "instrumental",
        "no voice",
        "No Vocals",
    ],
)
def test_instrumental_phrases(text: str) -> None:
    q = run(f"dark ambient {text}")
    assert q.filters.vocal == "instrumental"
    assert q.semantic_text == "dark ambient"
    assert "instrumental only" in q.notes


@pytest.mark.parametrize(
    "text", ["with vocals", "vocal", "vocals", "singing", "sung", "female vocals", "male vocals"]
)
def test_vocal_phrases(text: str) -> None:
    q = run(f"pop ballad {text}")
    assert q.filters.vocal == "vocal"
    assert q.semantic_text == "pop ballad"


def test_conflicting_vocal_phrases_apply_no_filter_and_say_so() -> None:
    q = run("rock instrumental with vocals")
    assert q.filters.vocal is None
    assert q.semantic_text == "rock"
    assert any("no vocal filter" in n for n in q.notes)


@pytest.mark.parametrize(
    ("text", "low", "high"),
    [
        ("under 30 seconds", None, 30),
        ("under 30 sec", None, 30),
        ("under 30 s", None, 30),
        ("under 30s", None, 30),
        ("shorter than 2 minutes", None, 120),
        ("shorter than 2 min", None, 120),
        ("less than 1.5 minutes", None, 90),
        ("below 45 seconds", None, 45),
        ("longer than 3 minutes", 180, None),
        ("longer than 90 seconds", 90, None),
        ("over 2 min", 120, None),
        ("more than 60 sec", 60, None),
        ("longer than 1 minute and shorter than 4 minutes", 60, 240),
    ],
)
def test_duration_phrases(text: str, low: float | None, high: float | None) -> None:
    q = run(f"battle theme {text}")
    assert (q.filters.duration_min_s, q.filters.duration_max_s) == (low, high)
    assert q.semantic_text == "battle theme"
    assert any(n.startswith("duration") for n in q.notes)


def test_bpm_and_duration_do_not_confuse_each_other() -> None:
    q = run("under 90 bpm, under 30 seconds")
    assert q.filters.bpm_max == 90 and q.filters.duration_max_s == 30
    assert q.semantic_text is None


@pytest.mark.parametrize("word", ["jingle", "stinger", "sting", "short cue", "Jingle"])
def test_jingle_words_cap_the_duration_at_20_seconds(word: str) -> None:
    q = run(f"victory {word}")
    assert q.filters.duration_max_s == 20
    assert q.semantic_text == "victory"


def test_explicit_duration_beats_the_jingle_default() -> None:
    assert run("victory jingle under 10 seconds").filters.duration_max_s == 10


@pytest.mark.parametrize(
    "text",
    [
        "commercial use",
        "safe for commercial use",
        "safe for commercial",
        "for my commercial game",
        "for a commercial game",
        "royalty-free for games",
        "royalty free for games",
        "for commercial use",
    ],
)
def test_commercial_phrases_mean_green(text: str) -> None:
    q = run(f"calm piano {text}")
    assert q.filters.max_risk == "green"
    assert q.semantic_text == "calm piano"


@pytest.mark.parametrize("text", ["no attribution", "CC0", "public domain"])
def test_no_attribution_phrases_mean_green_with_a_credit_note(text: str) -> None:
    q = run(f"piano {text}")
    assert q.filters.max_risk == "green"
    assert q.semantic_text == "piano"
    assert any("CC BY" in n and "credit" in n for n in q.notes)


@pytest.mark.parametrize(
    ("text", "energy"),
    [
        ("calm piano", 0.3),
        ("relaxing music", 0.3),
        ("chill beats", 0.3),
        ("peaceful forest", 0.3),
        ("soft pads", 0.3),
        ("quiet room", 0.3),
        ("ambient drone", 0.3),
        ("sleepy lullaby", 0.3),
        ("energetic run", 0.8),
        ("intense chase", 0.8),
        ("aggressive guitars", 0.8),
        ("powerful drums", 0.8),
        ("epic finale", 0.8),
        ("driving bass", 0.8),
        ("fast pursuit", 0.8),
        ("action scene", 0.8),
        ("calm but intense", 0.55),
        ("tense stealth level", None),
    ],
)
def test_energy_words(text: str, energy: float | None) -> None:
    prefs = run(text).preferences
    assert prefs.energy_target == (pytest.approx(energy) if energy is not None else None)


def test_energy_words_stay_in_the_text() -> None:
    assert run("calm piano").semantic_text == "calm piano"


@pytest.mark.parametrize(
    ("text", "target"),
    [("slow dirge", 75), ("upbeat tune", 125), ("fast chase", 145), ("a quiet walk", None)],
)
def test_tempo_words_set_a_target_only_without_a_number(text: str, target: float | None) -> None:
    assert run(text).preferences.bpm_target == target


def test_tempo_word_is_ignored_when_a_bpm_filter_exists() -> None:
    assert run("slow dirge under 100 bpm").preferences.bpm_target is None
    assert run("slow dirge", bpm_min=60, bpm_max=70).preferences.bpm_target is None


@pytest.mark.parametrize(
    ("text", "genres", "moods"),
    [
        ("jazz cafe", ("jazz",), ()),
        ("Hip Hop beat", ("hip-hop",), ()),
        ("hip-hop beat", ("hip-hop",), ()),
        ("rap battle", ("hip-hop",), ()),
        ("r&b slow jam", ("soul-rnb",), ("slow",)),
        ("old time historic radio", ("old-time-historic",), ()),
        ("spooky forest", (), ("dark",)),
        ("creepy basement", (), ("dark",)),
        ("chill lofi", (), ("relaxing",)),
        ("chiptune boss", ("electronic",), ("game",)),
        ("8-bit boss", ("electronic",), ("game",)),
        ("epic orchestral trailer", (), ("epic", "trailer")),
        ("tense stealth level", (), ()),
        ("rockabilly", (), ()),  # whole words only
    ],
)
def test_genre_and_mood_hints(text: str, genres: tuple[str, ...], moods: tuple[str, ...]) -> None:
    prefs = run(text).preferences
    assert prefs.genre_hints == genres
    assert prefs.mood_hints == moods


def test_hints_stay_in_the_text_and_are_noted() -> None:
    q = run("dark jazz")
    assert q.semantic_text == "dark jazz"
    assert "genre: jazz" in q.notes and "mood: dark" in q.notes


def test_hard_phrases_are_not_read_as_hints() -> None:
    q = run("jazz for commercial use, instrumental")
    assert q.semantic_text == "jazz"
    assert q.preferences.mood_hints == ()  # "commercial" is also a mood label
    assert q.preferences.genre_hints == ("jazz",)  # "instrumental" is also a genre label: stripped


def test_only_constraints_leave_no_semantic_text() -> None:
    q = run("under 90 bpm, instrumental")
    assert q.semantic_text is None
    assert (q.filters.bpm_max, q.filters.vocal) == (90, "instrumental")


@pytest.mark.parametrize("text", [None, "", "   ", "music", "Music for", "the"])
def test_nothing_descriptive_means_filter_only(text: str | None) -> None:
    assert run(text).semantic_text is None


def test_stripping_leaves_a_tidy_text() -> None:
    assert run("Tense stealth level, no vocals, under 100 bpm.").semantic_text == (
        "Tense stealth level"
    )
    assert run("music with no vocals for a commercial game").semantic_text is None
    assert run("calm piano with no vocals").semantic_text == "calm piano"
    assert run("   ").notes == []


def test_the_example_of_the_brief() -> None:
    q = run("tense stealth level, no vocals", max_risk="amber")
    assert q.semantic_text == "tense stealth level"
    assert q.filters.vocal == "instrumental"
    assert q.filters.max_risk == "amber"


def test_ui_filters_win_over_parsed_ones_group_by_group() -> None:
    q = run(
        "no vocals under 90 bpm under 30 seconds commercial use",
        vocal="vocal",
        bpm_min=100,
        duration_max_s=60,
    )
    f = q.filters
    assert f.vocal == "vocal"
    assert (f.bpm_min, f.bpm_max) == (100, None)  # the parsed max is not mixed in
    assert (f.duration_min_s, f.duration_max_s) == (None, 60)
    assert f.max_risk == "green"  # nothing set in the filters: the parsed licence applies
    assert q.semantic_text is None  # the phrases are stripped even when overridden
    assert sum("ignored" in n for n in q.notes) == 3


@pytest.mark.parametrize("ui", ["amber", "red", "unknown"])
def test_the_stricter_licence_limit_wins_and_a_note_says_so(ui: str) -> None:
    q = run("piano for commercial use", max_risk=ui)
    assert q.filters.max_risk == "green"  # a UI limit never loosens a parsed one
    assert q.semantic_text == "piano"
    risk_notes = [n for n in q.notes if n.startswith("licence")]
    assert len(risk_notes) == 1
    if ui == "unknown":
        assert risk_notes[0] == "licence: green only (safe for commercial use)"
    else:
        assert f"stricter than your max_risk={ui}" in risk_notes[0]


def test_an_equally_strict_or_absent_phrase_changes_nothing() -> None:
    assert run("piano for commercial use", max_risk="green").filters.max_risk == "green"
    for ui in ("green", "amber", "red"):
        assert run("piano", max_risk=ui).filters.max_risk == ui


def test_ui_filters_alone_fill_the_gaps_the_text_leaves() -> None:
    q = run("no vocals", bpm_max=100, sources=("local",), genres=("jazz",), moods=("calm",))
    assert q.filters.vocal == "instrumental"
    assert q.filters.bpm_max == 100
    assert q.filters.sources == ("local",)
    assert q.requested_labels() == [("genre", "jazz"), ("moodtheme", "calm")]


def test_requested_labels_merge_filters_and_hints_without_duplicates() -> None:
    q = run("dark jazz", genres=("jazz", "blues"), moods=("calm",))
    assert q.requested_labels() == [
        ("genre", "jazz"),
        ("genre", "blues"),
        ("moodtheme", "calm"),
        ("moodtheme", "dark"),
    ]


def test_parse_is_deterministic_and_the_rule_parser_matches_the_function() -> None:
    request = SearchRequest(text="dark ambient 70-90 bpm no vocals, under 2 minutes")
    assert RuleParser().parse(request, VOCAB) == parse(request, VOCAB) == parse(request, VOCAB)
