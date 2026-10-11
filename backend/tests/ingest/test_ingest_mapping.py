"""SourceTrack + LicenseInfo -> TrackRecord."""

from __future__ import annotations

from ingest_support import CC_BY, CC_BY_NC_ND, make_track

from mcrar.ingest import to_track_record
from mcrar.licensing import custom_license, parse_license


def test_red_non_commercial_no_derivatives_track() -> None:
    src = make_track(
        979853,
        title="Garnet",
        artist="Ken Elkinson",
        license_url=CC_BY_NC_ND,
        commercial_license_url="https://licensing.jamendo.com/track/979853",
        download_url="https://dl.example/979853",
        audiodownload_allowed=True,
        image_url="https://img.example/1.jpg",
        release_date="2012-11-15",
        vocal_instrumental="instrumental",
        tags={"genres": ["ambient"], "speed": "medium"},
    )
    rec = to_track_record(src, parse_license(src.license_url))
    assert (rec.source, rec.source_id) == ("jamendo", "979853")
    assert (rec.title, rec.artist, rec.album) == ("Garnet", "Ken Elkinson", "Album")
    assert rec.duration_s == 180.0
    assert rec.release_date == "2012-11-15"
    assert rec.source_url == "https://www.jamendo.com/track/979853"
    assert rec.stream_url == src.stream_url
    assert rec.download_url == "https://dl.example/979853"
    assert rec.audiodownload_allowed is True
    assert rec.image_url == "https://img.example/1.jpg"
    assert rec.local_path is None
    assert rec.license_url == "https://creativecommons.org/licenses/by-nc-nd/3.0/"
    assert rec.license_code == "CC BY-NC-ND 3.0"
    assert rec.license_family == "cc-by-nc-nd"
    assert rec.risk == "red"
    assert rec.commercial_ok is False
    assert rec.derivatives_ok is False
    assert rec.share_alike is False
    assert rec.attribution_required is True
    assert rec.commercial_license_url == "https://licensing.jamendo.com/track/979853"
    assert rec.vocal_instrumental == "instrumental"
    assert rec.source_tags == {"genres": ["ambient"], "speed": "medium"}
    assert rec.attribution_text == (
        '"Garnet" by Ken Elkinson (https://www.jamendo.com/track/979853), '
        "licensed under CC BY-NC-ND 3.0 (https://creativecommons.org/licenses/by-nc-nd/3.0/)"
    )


def test_green_cc_by_track() -> None:
    src = make_track(5, title="Sunrise", artist="Ann")
    rec = to_track_record(src, parse_license(CC_BY))
    assert rec.risk == "green"
    assert rec.license_family == "cc-by"
    assert rec.license_code == "CC BY 4.0"
    assert (rec.commercial_ok, rec.derivatives_ok, rec.share_alike) == (True, True, False)
    assert rec.attribution_required is True
    assert rec.commercial_license_url is None
    assert rec.attribution_text is not None
    assert rec.attribution_text.startswith('"Sunrise" by Ann (https://www.jamendo.com/track/5)')
    assert "CC BY 4.0" in rec.attribution_text


def test_unrecognised_license_keeps_the_raw_url_and_is_unknown() -> None:
    src = make_track(6, license_url="https://example.com/my-terms")
    rec = to_track_record(src, parse_license(src.license_url))
    assert rec.risk == "unknown"
    assert rec.license_url == "https://example.com/my-terms"
    assert rec.commercial_ok is None
    assert rec.attribution_text is not None
    assert "license unknown" in rec.attribution_text


def test_local_track_with_custom_license_and_extra_attribution() -> None:
    src = make_track(
        7,
        source="local",
        source_id="ab" * 32,
        title="Loop",
        artist=None,
        license_url=None,
        stream_url=None,
        local_path="C:/music/loop.wav",
    )
    lic = custom_license(
        commercial_ok=True, derivatives_ok=True, attribution_required=False, name="Store EULA"
    )
    rec = to_track_record(src, lic, attribution_extra="Music by X")
    assert rec.artist is None
    assert rec.local_path == "C:/music/loop.wav"
    assert (rec.license_family, rec.license_code, rec.license_url) == ("custom", "Store EULA", None)
    assert rec.risk == "green"
    assert rec.attribution_text is not None
    assert rec.attribution_text.endswith("licensed under Store EULA Music by X")
    assert rec.attribution_text.startswith('"Loop" by Unknown artist')


def test_source_tags_are_copied() -> None:
    src = make_track(8)
    rec = to_track_record(src, parse_license(CC_BY))
    assert rec.source_tags == dict(src.tags)
    assert rec.source_tags is not src.tags
