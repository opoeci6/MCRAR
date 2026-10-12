"""The vocabulary: built-in labels, the M3b registry, synonyms, resolving user input."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcrar.config import get_settings
from mcrar.recommend import Vocabulary
from mcrar.recommend.vocab import DEFAULT_GENRES, DEFAULT_MOODTHEMES


def test_defaults_have_the_agreed_label_ids() -> None:
    vocab = Vocabulary.default()
    assert len(vocab.labels("genre")) == 16 == len(DEFAULT_GENRES)
    assert len(vocab.labels("moodtheme")) == 56 == len(DEFAULT_MOODTHEMES)
    assert vocab.has("genre", "soul-rnb") and vocab.has("moodtheme", "meditative")
    assert not vocab.has("genre", "calm")
    assert vocab.display_name("genre", "old-time-historic") == "Old-Time / Historic"
    assert vocab.display_name("moodtheme", "calm") == "Calm"


def test_match_finds_ids_display_names_and_synonyms() -> None:
    vocab = Vocabulary.default()
    found = vocab.match("a spooky r&b rap with chiptune and chill vibes")
    assert set(found["genre"]) == {"soul-rnb", "hip-hop", "electronic"}
    assert set(found["moodtheme"]) == {"dark", "game", "relaxing"}


def test_match_is_whole_word_and_case_insensitive() -> None:
    vocab = Vocabulary.default()
    assert vocab.match("Rockabilly")["genre"] == ()
    assert vocab.match("ROCK")["genre"] == ("rock",)
    assert vocab.match("hip hop")["genre"] == ("hip-hop",)
    assert vocab.match("Soul / R&B")["genre"] == ("soul-rnb",)


def test_resolve_accepts_names_and_rejects_unknown_ones() -> None:
    vocab = Vocabulary.default()
    assert vocab.resolve("genre", ["Jazz", "hip hop", ""]) == ("jazz", "hip-hop")
    assert vocab.resolve("moodtheme", ["spooky"]) == ("dark",)
    with pytest.raises(ValueError, match="unknown genre label 'polka'.*choose from: blues"):
        vocab.resolve("genre", ["polka"])
    with pytest.raises(ValueError, match="unknown genre label 'calm'"):
        vocab.resolve("genre", ["calm"])  # a mood, not a genre


def _registry(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_registry_labels_and_display_names_win(tmp_path: Path) -> None:
    path = _registry(
        tmp_path,
        {
            "schema": 1,
            "label_sets": {
                "genre": {
                    "kind": "single_label",
                    "labels": ["jazz", "polka"],
                    "display": {"polka": "Polka Dots"},
                    "entries": [],
                },
                "valence": {"kind": "regression", "labels": ["value"]},
            },
        },
    )
    vocab = Vocabulary.from_registry(path)
    assert vocab.labels("genre") == ("jazz", "polka")
    assert vocab.display_name("genre", "polka") == "Polka Dots"
    assert vocab.display_name("genre", "jazz") == "Jazz"
    assert vocab.match("polka dots please")["genre"] == ("polka",)
    assert vocab.match("a rock song")["genre"] == ()  # not in this registry's genre set
    assert vocab.labels("moodtheme") == tuple(DEFAULT_MOODTHEMES)  # absent set: defaults
    assert "valence" not in vocab.label_set_names


def test_a_missing_or_broken_registry_means_the_defaults(tmp_path: Path) -> None:
    defaults = Vocabulary.default().labels("genre")
    assert Vocabulary.from_registry(tmp_path / "nope.json").labels("genre") == defaults
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert Vocabulary.from_registry(broken).labels("genre") == defaults
    for payload in ([], {"label_sets": []}, {"label_sets": {"genre": {"labels": "jazz"}}}):
        assert Vocabulary.from_registry(_registry(tmp_path, payload)).labels("genre") == defaults
    bad_ids = {"label_sets": {"genre": {"labels": ["Not Valid", 3]}}}
    assert Vocabulary.from_registry(_registry(tmp_path, bad_ids)).labels("genre") == defaults


def test_load_reads_models_registry_json_under_the_models_dir(isolated_env: Path) -> None:
    settings = get_settings()
    assert Vocabulary.load(settings).labels("genre") == tuple(DEFAULT_GENRES)
    (settings.models_dir).mkdir()
    (settings.models_dir / "registry.json").write_text(
        json.dumps({"label_sets": {"genre": {"labels": ["jazz"]}}}), encoding="utf-8"
    )
    assert Vocabulary.load(settings).labels("genre") == ("jazz",)
