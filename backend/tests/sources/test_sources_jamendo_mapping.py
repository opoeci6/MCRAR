"""Mapping of Jamendo track JSON to SourceTrack."""

from __future__ import annotations

import copy
import dataclasses

import pytest
from sources_support import REAL_TRACK

from mcrar.sources import SourceTrack, parse_track


def test_real_track_maps_field_by_field() -> None:
    track = parse_track(REAL_TRACK)
    assert track is not None
    assert track.source == "jamendo"
    assert track.source_id == "979853"
    assert track.title == "Garnet"
    assert track.artist == "Ken Elkinson"
    assert track.album == "Elemental Volume 1"
    assert track.duration_s == 310.0
    assert track.release_date == "2012-11-15"
    assert track.source_url == "https://www.jamendo.com/track/979853"
    assert track.stream_url == REAL_TRACK["audio"]
    assert track.download_url == "https://prod-1.storage.jamendo.com/download/track/979853/mp32/"
    assert track.audiodownload_allowed is True
    assert track.license_url == "http://creativecommons.org/licenses/by-nc-nd/3.0/"
    assert track.commercial_license_url == "https://licensing.jamendo.com/track/979853"
    assert track.image_url == REAL_TRACK["image"]
    assert track.vocal_instrumental == "instrumental"
    assert track.local_path is None
    assert track.tags == {
        "genres": ["ambient"],
        "instruments": ["synthesizer"],
        "vartags": ["peaceful", "spa"],
        "speed": "medium",
        "acousticelectric": "electric",
        "gender": "neutral",
        "lang": None,
        "content_id_free": False,
        "probackground": True,
    }


def test_source_track_is_frozen_and_has_no_id_field() -> None:
    track = parse_track(REAL_TRACK)
    assert track is not None
    with pytest.raises(dataclasses.FrozenInstanceError):
        track.title = "x"  # type: ignore[misc]
    assert "id" not in {f.name for f in dataclasses.fields(SourceTrack)}


def test_prourl_only_when_prolicensing_is_true() -> None:
    data = copy.deepcopy(REAL_TRACK)
    data["licenses"]["prolicensing"] = "false"
    track = parse_track(data)
    assert track is not None
    assert track.commercial_license_url is None


def test_empty_audiodownload_gives_none_and_not_allowed() -> None:
    data = copy.deepcopy(REAL_TRACK)
    data["audiodownload"] = ""
    data["audiodownload_allowed"] = False
    track = parse_track(data)
    assert track is not None
    assert track.download_url is None
    assert track.audiodownload_allowed is False


def test_download_url_ignored_when_not_allowed_even_if_present() -> None:
    data = copy.deepcopy(REAL_TRACK)
    data["audiodownload_allowed"] = False
    track = parse_track(data)
    assert track is not None
    assert track.download_url is None


def test_string_booleans_in_licenses() -> None:
    data = copy.deepcopy(REAL_TRACK)
    data["licenses"] = {"prolicensing": "false", "probackground": "false"}
    track = parse_track(data)
    assert track is not None
    assert track.tags["probackground"] is False


def test_missing_musicinfo_and_licenses_are_tolerated() -> None:
    data = copy.deepcopy(REAL_TRACK)
    del data["musicinfo"]
    del data["licenses"]
    track = parse_track(data)
    assert track is not None
    assert track.vocal_instrumental is None
    assert track.commercial_license_url is None
    assert track.tags["genres"] == []
    assert track.tags["probackground"] is None
    assert track.tags["speed"] is None


def test_empty_license_url_and_shareurl_fallback() -> None:
    data = copy.deepcopy(REAL_TRACK)
    data["license_ccurl"] = ""
    data["shareurl"] = ""
    track = parse_track(data)
    assert track is not None
    assert track.license_url is None
    assert track.source_url == "https://jamen.do/t/979853"


def test_unknown_vocalinstrumental_and_image_fallback() -> None:
    data = copy.deepcopy(REAL_TRACK)
    data["musicinfo"]["vocalinstrumental"] = "both"
    data["image"] = ""
    track = parse_track(data)
    assert track is not None
    assert track.vocal_instrumental is None
    assert track.image_url == REAL_TRACK["album_image"]


def test_track_without_id_is_skipped() -> None:
    assert parse_track({"name": "no id"}) is None


def test_html_entities_in_names_are_decoded() -> None:
    data = copy.deepcopy(REAL_TRACK)
    data["name"] = "Rock &amp; Roll &quot;Live&quot; &#39;99"
    data["artist_name"] = "Jazyus &amp; EdSeGaMe"
    data["album_name"] = "Tom &amp; Jerry&#039;s &lt;Best&gt; &amp;lt;"
    track = parse_track(data)
    assert track is not None
    assert track.title == 'Rock & Roll "Live" \'99'
    assert track.artist == "Jazyus & EdSeGaMe"
    assert track.album == "Tom & Jerry's <Best> &lt;"  # one level only


def test_entity_decoding_keeps_empty_and_missing_names() -> None:
    data = copy.deepcopy(REAL_TRACK)
    data["name"] = "  "
    data["artist_name"] = None
    data["album_name"] = ""
    track = parse_track(data)
    assert track is not None
    assert (track.title, track.artist, track.album) == ("", "", None)
