"""``track_credits``: the one-track credits report built from a catalog row."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from mcrar.catalog import StoredTrack
from mcrar.licensing import track_credits

TRACK = StoredTrack(
    id=7,
    created_at="2026-01-01T00:00:00Z",
    updated_at="2026-01-01T00:00:00Z",
    source="jamendo",
    source_id="123",
    title="Night Heist",
    artist="Ada",
    source_url="https://www.jamendo.com/track/123",
    license_code="CC BY 3.0",
    license_url="https://creativecommons.org/licenses/by/3.0/",
    license_family="cc-by",
    risk="green",
    commercial_ok=True,
    derivatives_ok=True,
    share_alike=False,
    attribution_required=True,
)
TASL = (
    '"Night Heist" by Ada (https://www.jamendo.com/track/123), licensed under CC BY 3.0 '
    "(https://creativecommons.org/licenses/by/3.0/)"
)


@pytest.mark.parametrize("fmt", ["txt", "md", "json"])
def test_every_format_carries_the_attribution(fmt: str) -> None:
    text = track_credits(TRACK, fmt)  # type: ignore[arg-type]
    assert TASL in text.replace('\\"', '"')
    assert "CC BY 3.0" in text and "green" in text


def test_json_has_the_licence_fields() -> None:
    payload = json.loads(track_credits(TRACK, "json"))
    item = payload["items"][0]
    assert item["title"] == "Night Heist" and item["license"]["family"] == "cc-by"
    assert item["license"]["commercial_ok"] is True and item["attribution"] == TASL


def test_a_declared_attribution_suffix_is_kept() -> None:
    track = replace(TRACK, attribution_text=TASL + " Remixed for Game X")
    assert (
        track_credits(track, "txt")
        .splitlines()[-1]
        .endswith("CC BY 3.0 (" + TRACK.license_url + ") Remixed for Game X")
    )


def test_missing_licence_data_still_renders() -> None:
    bare = StoredTrack(
        id=1, created_at="x", updated_at="x", source="local", source_id="a.wav", risk="unknown"
    )
    text = track_credits(bare, "txt")
    assert '"Untitled" by Unknown artist' in text and "Unknown license" in text


def test_red_tracks_show_the_commercial_licence_link() -> None:
    track = replace(
        TRACK,
        risk="red",
        license_family="cc-by-nc",
        license_code="CC BY-NC 3.0",
        commercial_license_url="https://licensing.example/123",
    )
    assert "Commercial license available: https://licensing.example/123" in track_credits(
        track, "txt"
    )
