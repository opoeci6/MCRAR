"""parse_sound mapping and the Freesound licences through the licensing parser."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from sources_support import FS_SOUND

from mcrar.licensing import parse_license
from mcrar.sources import SourceTrack, parse_sound
from mcrar.sources.freesound import normalise_license


def sound(**overrides: Any) -> dict[str, Any]:
    data = copy.deepcopy(FS_SOUND)
    data.update(overrides)
    return data


def test_full_mapping() -> None:
    track = parse_sound(FS_SOUND)
    assert isinstance(track, SourceTrack)
    assert track.source == "freesound"
    assert track.source_id == "456789"
    assert track.title == "Warm pad loop"
    assert track.artist == "someone"
    assert track.album is None
    assert track.duration_s == 42.5
    assert track.release_date == "2019-03-04"
    assert track.source_url == "https://freesound.org/people/someone/sounds/456789/"
    assert track.stream_url == "https://cdn.freesound.org/previews/456/456789_1-hq.mp3"
    assert track.download_url == track.source_url
    assert track.audiodownload_allowed is True
    assert track.license_url == "https://creativecommons.org/licenses/by/4.0/"
    assert track.commercial_license_url is None
    assert track.image_url is None
    assert track.vocal_instrumental is None
    assert track.local_path is None
    assert dict(track.tags) == {
        "vartags": ["loop", "pad", "ambient"],
        "category": ["Music"],
        "gen_ai_preference": ["no-preference"],
    }
    json.dumps(dict(track.tags))  # stored as JSON in the catalog


def test_lists_in_category_and_gen_ai_preference() -> None:
    track = parse_sound(sound(category=["Music", "Soundscapes", ""], gen_ai_preference=["a", 3]))
    assert track is not None
    assert track.tags["category"] == ["Music", "Soundscapes"]
    assert track.tags["gen_ai_preference"] == ["a", "3"]


def test_missing_optional_fields() -> None:
    track = parse_sound(
        {"id": 5, "previews": {"preview-hq-mp3": "https://cdn.freesound.org/x.mp3"}}
    )
    assert track is not None
    assert (track.title, track.artist) == ("", "")
    assert track.duration_s is None
    assert track.release_date is None
    assert track.source_url is None and track.download_url is None
    assert track.license_url is None
    assert dict(track.tags) == {"vartags": [], "category": [], "gen_ai_preference": []}


@pytest.mark.parametrize(
    "overrides",
    [
        {"previews": None},
        {"previews": {}},
        {"previews": {"preview-lq-mp3": "https://cdn.freesound.org/lq.mp3"}},
        {"previews": {"preview-hq-ogg": "https://cdn.freesound.org/hq.ogg"}},
        {"previews": {"preview-hq-mp3": ""}},
        {"previews": "nope"},
        {"id": None},
        {"id": ""},
    ],
)
def test_sounds_without_id_or_hq_mp3_preview_are_skipped(overrides: dict[str, Any]) -> None:
    assert parse_sound(sound(**overrides)) is None


def test_no_previews_key_at_all_is_skipped() -> None:
    data = sound()
    del data["previews"]
    assert parse_sound(data) is None


@pytest.mark.parametrize(
    "created,expected",
    [
        ("2019-03-04T12:34:56.789", "2019-03-04"),
        ("2019-03-04", "2019-03-04"),
        ("garbage", None),
        (None, None),
        ("", None),
    ],
)
def test_release_date(created: str | None, expected: str | None) -> None:
    track = parse_sound(sound(created=created))
    assert track is not None
    assert track.release_date == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Creative Commons 0", "https://creativecommons.org/publicdomain/zero/1.0/"),
        ("Attribution", "https://creativecommons.org/licenses/by/4.0/"),
        ("Attribution NonCommercial", "https://creativecommons.org/licenses/by-nc/4.0/"),
        ("  attribution   noncommercial ", "https://creativecommons.org/licenses/by-nc/4.0/"),
        ("Sampling+", "https://creativecommons.org/licenses/sampling+/1.0/"),
        ("http://creativecommons.org/publicdomain/zero/1.0/", None),  # a URL stays as is
        ("Something else", None),
        (None, None),
        ("", None),
    ],
)
def test_normalise_license(value: str | None, expected: str | None) -> None:
    if expected is None:
        assert normalise_license(value) == (value.strip() or None if value else None)
    else:
        assert normalise_license(value) == expected


# (freesound licence value, family, risk, commercial_ok)
LICENCE_CASES = [
    ("http://creativecommons.org/publicdomain/zero/1.0/", "cc0", "green", True),
    ("https://creativecommons.org/publicdomain/zero/1.0/", "cc0", "green", True),
    ("http://creativecommons.org/licenses/by/4.0/", "cc-by", "green", True),
    ("https://creativecommons.org/licenses/by/4.0/", "cc-by", "green", True),
    ("http://creativecommons.org/licenses/by/3.0/", "cc-by", "green", True),
    ("http://creativecommons.org/licenses/by-nc/4.0/", "cc-by-nc", "red", False),
    ("https://creativecommons.org/licenses/by-nc/3.0/", "cc-by-nc", "red", False),
    ("http://creativecommons.org/licenses/by-nc/3.0/", "cc-by-nc", "red", False),
    ("http://creativecommons.org/licenses/sampling+/1.0/", "sampling-plus", "red", False),
    ("https://creativecommons.org/licenses/sampling+/1.0/", "sampling-plus", "red", False),
    ("Creative Commons 0", "cc0", "green", True),
    ("Attribution", "cc-by", "green", True),
    ("Attribution NonCommercial", "cc-by-nc", "red", False),
    ("Sampling+", "sampling-plus", "red", False),
]


@pytest.mark.parametrize(
    "value,family,risk,commercial", LICENCE_CASES, ids=[c[0] for c in LICENCE_CASES]
)
def test_freesound_licences_through_the_licensing_parser(
    value: str, family: str, risk: str, commercial: bool
) -> None:
    track = parse_sound(sound(license=value))
    assert track is not None
    info = parse_license(track.license_url)
    assert info.family == family
    assert info.risk == risk
    assert info.commercial_ok is commercial
    assert info.attribution_required is (family != "cc0")


def test_unrecognised_licence_stays_raw_and_parses_as_unknown() -> None:
    track = parse_sound(sound(license="All rights reserved"))
    assert track is not None
    assert track.license_url == "All rights reserved"
    assert parse_license(track.license_url).family == "unknown"
