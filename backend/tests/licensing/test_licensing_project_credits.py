"""``track_credit_item`` and ``project_credits``: the report of a project's shortlist."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from mcrar.catalog import StoredTrack
from mcrar.licensing import (
    LICENSE_DISCLAIMER,
    CreditItem,
    custom_license,
    project_credits,
    render_credits,
    track_credit_item,
)

BASE = StoredTrack(
    id=1,
    created_at="x",
    updated_at="x",
    source="jamendo",
    source_id="1",
    title="Night Heist",
    artist="Ada",
    source_url="https://www.jamendo.com/track/1",
    license_code="CC BY 3.0",
    license_url="https://creativecommons.org/licenses/by/3.0/",
    license_family="cc-by",
    risk="green",
    commercial_ok=True,
    derivatives_ok=True,
    share_alike=False,
    attribution_required=True,
)
RED = replace(
    BASE,
    id=2,
    title="Red Alert",
    license_code="CC BY-NC 3.0",
    license_url="https://creativecommons.org/licenses/by-nc/3.0/",
    license_family="cc-by-nc",
    risk="red",
    commercial_ok=False,
    commercial_license_url="https://licensing.example/2",
)
UNKNOWN = StoredTrack(
    id=3, created_at="x", updated_at="x", source="local", source_id="m.wav", risk="unknown"
)
CUSTOM = replace(
    BASE,
    id=4,
    title="Pack Theme",
    source="local",
    source_url=None,
    license_code="Asset Store EULA",
    license_url=None,
    license_family="custom",
    risk="amber",
    share_alike=True,
)


def test_stored_attribution_is_used_verbatim() -> None:
    track = replace(BASE, attribution_text="Custom credit line, thanks to Ada")
    item = track_credit_item(track)
    assert item.attribution == "Custom credit line, thanks to Ada"
    assert "Custom credit line, thanks to Ada" in project_credits("g", [track], "txt")


def test_declared_extra_is_kept_in_the_stored_line() -> None:
    generated = track_credit_item(BASE).attribution
    track = replace(BASE, attribution_text=generated + " Remixed for Game X")
    item = track_credit_item(track)
    assert item.attribution == generated + " Remixed for Game X"
    assert item.attribution_extra == "Remixed for Game X"


def test_without_stored_attribution_the_line_is_generated() -> None:
    item = track_credit_item(BASE)
    assert item.attribution_override is None
    assert item.attribution.startswith('"Night Heist" by Ada (https://www.jamendo.com/track/1)')


def test_credit_item_without_override_is_unchanged() -> None:
    item = CreditItem(title="T", artist=None, license=track_credit_item(BASE).license)
    assert item.attribution == (
        '"T" by Unknown artist, licensed under CC BY 3.0 '
        "(https://creativecommons.org/licenses/by/3.0/)"
    )


def test_custom_licence_keeps_its_risk_and_flags_without_a_url() -> None:
    lic = track_credit_item(CUSTOM).license
    assert (lic.family, lic.risk, lic.url, lic.code) == (
        "custom",
        "amber",
        None,
        "Asset Store EULA",
    )
    assert (lic.commercial_ok, lic.derivatives_ok, lic.share_alike) == (True, True, True)
    payload = json.loads(project_credits("g", [CUSTOM], "json"))
    assert payload["items"][0]["license"]["risk"] == "amber"
    text = project_credits("g", [CUSTOM], "txt")
    assert "== Amber" in text and "License: Asset Store EULA" in text and "http" not in text


def test_custom_licence_helper_agrees_with_the_rebuilt_info() -> None:
    declared = custom_license(commercial_ok=True, derivatives_ok=True, attribution_required=True)
    track = replace(CUSTOM, license_code=declared.code, risk=declared.risk, share_alike=False)
    assert track_credit_item(track).license.risk == declared.risk == "green"


@pytest.mark.parametrize("fmt", ["txt", "md", "json"])
def test_disclaimer_and_project_name_in_every_format(fmt: str) -> None:
    text = project_credits("My Game", [BASE, RED, UNKNOWN], fmt)  # type: ignore[arg-type]
    assert LICENSE_DISCLAIMER in text
    assert "My Game" in text


def test_txt_and_md_titles() -> None:
    assert project_credits("My Game", [BASE], "txt").startswith("MUSIC CREDITS: My Game\n")
    assert project_credits("My Game", [BASE], "md").startswith("# Music credits: My Game\n")


def test_json_structure() -> None:
    payload = json.loads(project_credits("My Game", [RED, BASE, UNKNOWN], "json"))
    assert list(payload) == ["disclaimer", "project", "items"]
    assert payload["project"] == "My Game" and payload["disclaimer"] == LICENSE_DISCLAIMER
    assert [i["title"] for i in payload["items"]] == ["Night Heist", "Untitled", "Red Alert"]


def test_groups_unknown_track_and_red_commercial_link() -> None:
    text = project_credits("g", [RED, UNKNOWN, BASE], "txt")
    green, unknown, red = (text.index(h) for h in ("== Green", "== Unknown", "== Red"))
    assert green < unknown < red
    assert text.index("Commercial license available: https://licensing.example/2") > red
    assert '"Untitled" by Unknown artist' in text[unknown:red]


def test_empty_project_still_has_header_and_disclaimer() -> None:
    text = project_credits("Empty", [], "txt")
    assert "Empty" in text and LICENSE_DISCLAIMER in text
    assert json.loads(project_credits("Empty", [], "json"))["items"] == []


def test_render_credits_without_project_has_no_project_key() -> None:
    payload = json.loads(render_credits([track_credit_item(BASE)], "json"))
    assert "project" not in payload
    assert render_credits([], "txt").startswith("MUSIC CREDITS\n")
