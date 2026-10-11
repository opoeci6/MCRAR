from __future__ import annotations

import json

import pytest

from mcrar.licensing import (
    LICENSE_DISCLAIMER,
    CreditItem,
    attribution_text,
    custom_license,
    parse_license,
    render_credits,
)

NC_ND = parse_license("http://creativecommons.org/licenses/by-nc-nd/3.0/")
BY = parse_license("http://creativecommons.org/licenses/by/4.0/")
CC0 = parse_license("CC0")
SA = parse_license("CC BY-SA 3.0")


def test_attribution_cc_by_nc_nd_matches_tasl_example():
    text = attribution_text(
        title="Garnet", artist="Ken Elkinson", license=NC_ND, source_url="https://jamen.do/t/979853"
    )
    assert text == (
        '"Garnet" by Ken Elkinson (https://jamen.do/t/979853), '
        "licensed under CC BY-NC-ND 3.0 (https://creativecommons.org/licenses/by-nc-nd/3.0/)"
    )


def test_attribution_cc_by():
    text = attribution_text(title="T", artist="A", license=BY, source_url="https://x.test/t")
    assert text == (
        '"T" by A (https://x.test/t), licensed under CC BY 4.0 '
        "(https://creativecommons.org/licenses/by/4.0/)"
    )


def test_attribution_cc0_is_public_domain():
    text = attribution_text(title="T", artist="A", license=CC0, source_url="https://x.test/t")
    assert text == '"T" by A (https://x.test/t), dedicated to the public domain (CC0 1.0)'


def test_attribution_missing_artist_and_url():
    for artist in (None, "", "  "):
        text = attribution_text(title="T", artist=artist, license=BY)
        assert text == (
            '"T" by Unknown artist, licensed under CC BY 4.0 '
            "(https://creativecommons.org/licenses/by/4.0/)"
        )


def test_attribution_custom_with_extra_appended_verbatim():
    lic = custom_license(
        commercial_ok=True,
        derivatives_ok=True,
        attribution_required=True,
        name="Unity Asset Store EULA",
    )
    extra = 'Music by "Pack Name" (c) 2024 Studio X.'
    text = attribution_text(title="T", artist="A", license=lic, extra=extra)
    assert text == f'"T" by A, licensed under Unity Asset Store EULA {extra}'
    assert text.endswith(extra)


def test_attribution_unknown_license():
    text = attribution_text(title="T", artist="A", license=parse_license("foo"))
    assert text == '"T" by A, license unknown'


def _items() -> list[CreditItem]:
    return [
        CreditItem(
            title="Zed",
            artist="Zoe",
            license=NC_ND,
            source_url="https://jamen.do/t/1",
            commercial_license_url="https://licensing.jamendo.com/track/1",
        ),
        CreditItem(title="Alpha", artist="Ann", license=BY, source_url="https://jamen.do/t/2"),
        CreditItem(title="Mid", artist=None, license=SA),
        CreditItem(title="Bravo", artist="Bob", license=CC0),
        CreditItem(title="Huh", artist="Hal", license=parse_license("")),
        CreditItem(
            title="Pack",
            artist="Studio",
            license=custom_license(
                commercial_ok=True, derivatives_ok=True, attribution_required=True, name="EULA"
            ),
            attribution_extra="Credit Studio X.",
        ),
    ]


@pytest.mark.parametrize("fmt", ["txt", "md", "json"])
def test_all_formats_contain_disclaimer(fmt):
    assert LICENSE_DISCLAIMER in render_credits(_items(), fmt)
    assert LICENSE_DISCLAIMER in render_credits([], fmt)


def test_disclaimer_says_not_legal_advice_and_verify():
    assert "not legal advice" in LICENSE_DISCLAIMER
    assert "verify" in LICENSE_DISCLAIMER


@pytest.mark.parametrize("fmt", ["txt", "md", "json"])
def test_output_is_deterministic_and_order_independent(fmt):
    items = _items()
    first = render_credits(items, fmt)
    assert render_credits(items, fmt) == first
    assert render_credits(list(reversed(items)), fmt) == first


def test_json_parses_and_round_trips_fields():
    items = _items()
    data = json.loads(render_credits(items, "json"))
    assert data["disclaimer"] == LICENSE_DISCLAIMER
    rows = {r["title"]: r for r in data["items"]}
    assert len(data["items"]) == len(items)
    for item in items:
        row = rows[item.title]
        assert row["artist"] == item.artist
        assert row["source_url"] == item.source_url
        assert row["attribution_extra"] == item.attribution_extra
        assert row["commercial_license_url"] == item.commercial_license_url
        assert row["license"]["family"] == item.license.family
        assert row["license"]["code"] == item.license.code
        assert row["license"]["url"] == item.license.url
        assert row["license"]["risk"] == item.license.risk
        assert row["license"]["commercial_ok"] == item.license.commercial_ok
        assert row["license"]["derivatives_ok"] == item.license.derivatives_ok
        assert row["license"]["share_alike"] == item.license.share_alike
        assert row["license"]["attribution_required"] == item.license.attribution_required
        assert row["license"]["version"] == item.license.version
        assert row["license"]["jurisdiction"] == item.license.jurisdiction
        assert row["attribution"] == attribution_text(
            title=item.title,
            artist=item.artist,
            license=item.license,
            source_url=item.source_url,
            extra=item.attribution_extra,
        )


@pytest.mark.parametrize("fmt", ["txt", "md"])
def test_human_formats_group_by_risk_with_red_last(fmt):
    out = render_credits(_items(), fmt)
    pos = {name: out.index(f'"{name}"') for name in ("Alpha", "Bravo", "Mid", "Huh", "Zed")}
    assert max(pos["Alpha"], pos["Bravo"]) < pos["Mid"] < pos["Huh"] < pos["Zed"]
    # Titles are sorted within a group.
    assert pos["Alpha"] < pos["Bravo"]
    assert out.index("Zed") > out.index("Huh")


@pytest.mark.parametrize("fmt", ["txt", "md"])
def test_commercial_license_hint_only_on_red(fmt):
    out = render_credits(_items(), fmt)
    assert "commercial license available: https://licensing.jamendo.com/track/1" in out.lower()
    green = CreditItem(
        title="G", artist="A", license=BY, commercial_license_url="https://elsewhere.test/buy"
    )
    assert "https://elsewhere.test/buy" not in render_credits([green], fmt)


@pytest.mark.parametrize("fmt", ["txt", "md"])
def test_human_formats_show_attribution_and_missing_artist(fmt):
    out = render_credits(_items(), fmt)
    assert "Unknown artist" in out
    assert "Credit Studio X." in out
    assert '"Zed" by Zoe (https://jamen.do/t/1), licensed under CC BY-NC-ND 3.0' in out


def test_md_has_headings():
    out = render_credits(_items(), "md")
    assert out.startswith("# Music credits")
    assert "### " in out
    assert "## Red" in out


def test_unsupported_format_raises():
    with pytest.raises(ValueError):
        render_credits([], "html")  # type: ignore[arg-type]
