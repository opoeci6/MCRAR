"""``build_filters`` and ``parse_range``: the validation the CLI and the API share."""

from __future__ import annotations

import pytest

from mcrar import cli
from mcrar.recommend import SearchFilters, Vocabulary
from mcrar.recommend.request import SOURCES, build_filters, flag_name, parse_range

VOCAB = Vocabulary.default()


@pytest.mark.parametrize(
    ("value", "single_is_max", "expected"),
    [
        (None, False, (None, None)),
        ("90", False, (80.0, 100.0)),
        ("5", False, (0.0, 15.0)),
        ("80-100", False, (80.0, 100.0)),
        ("100-", False, (100.0, None)),
        ("-30", True, (None, 30.0)),
        ("30", True, (None, 30.0)),
        ("0-30", True, (0.0, 30.0)),
        (" 60 - 120 ", True, (60.0, 120.0)),
    ],
)
def test_parse_range(value: str | None, single_is_max: bool, expected: tuple) -> None:
    assert parse_range(value, "bpm", single_is_max=single_is_max) == expected


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("fast", "--bpm must look like 80-100 or 90, got 'fast'"),
        ("", "--bpm must look like 80-100 or 90, got ''"),
        ("120-80", "--bpm: the first number must not exceed the second, got '120-80'"),
    ],
)
def test_parse_range_errors(value: str, message: str) -> None:
    with pytest.raises(ValueError) as info:
        parse_range(value, "bpm", single_is_max=False)
    assert str(info.value) == message


def test_defaults_build_the_empty_filter() -> None:
    assert build_filters(VOCAB) == SearchFilters()


def test_everything_is_resolved_and_validated() -> None:
    filters = build_filters(
        VOCAB,
        genres=["Jazz", "hip hop"],
        moods=["spooky"],
        bpm=(80, 100),
        duration=(0, 30),
        max_risk="amber",
        vocal="instrumental",
        sources=["local", "local"],
    )
    assert filters == SearchFilters(
        max_risk="amber",
        vocal="instrumental",
        bpm_min=80,
        bpm_max=100,
        duration_min_s=None,  # a minimum of 0 is no minimum
        duration_max_s=30,
        sources=("local",),
        genres=("jazz", "hip-hop"),
        moods=("dark",),
    )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_risk": "purple"}, "max_risk must be one of: green, amber, red"),
        ({"vocal": "choir"}, "vocal must be one of: vocal, instrumental"),
        ({"sources": ["jamendo", "spotify"]}, "source must be one of: jamendo, local"),
        ({"genres": ["polka"]}, "unknown genre label 'polka'; choose from: blues"),
        ({"moods": ["jazz"]}, "unknown moodtheme label 'jazz'"),
        ({"bpm": (120, 80)}, "bpm_min must not exceed bpm_max"),
        ({"duration": (9, 3)}, "duration_min_s must not exceed duration_max_s"),
        ({"bpm": (-1, None)}, "bpm_min must not be negative"),
    ],
)
def test_errors_use_the_plain_names(kwargs: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        build_filters(VOCAB, **kwargs)


def test_the_cli_spelling_of_the_names() -> None:
    assert flag_name("max_risk") == "--max-risk"
    with pytest.raises(ValueError, match="--max-risk must be one of"):
        build_filters(VOCAB, max_risk="purple", arg=flag_name)
    with pytest.raises(ValueError, match="--source must be one of"):
        build_filters(VOCAB, sources=[""], arg=flag_name)


def test_the_sources_match_the_cli() -> None:
    assert SOURCES == cli.SOURCES
