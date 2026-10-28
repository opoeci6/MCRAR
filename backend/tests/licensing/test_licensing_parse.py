from __future__ import annotations

import dataclasses

import pytest

from mcrar.licensing import (
    RISK_ORDER,
    custom_license,
    parse_license,
    risk_at_most,
)

CC = "https://creativecommons.org"
PIX = "https://pixabay.com/service/license-summary/"
FAL = "https://artlibre.org/licence/lal/en/"

# (input, family, version, jurisdiction, code, url, commercial, derivatives, share_alike,
#  attribution, risk)
CASES = [
    # Real Jamendo license_ccurl values.
    (
        "http://creativecommons.org/licenses/by-nc-nd/3.0/",
        "cc-by-nc-nd",
        "3.0",
        None,
        "CC BY-NC-ND 3.0",
        f"{CC}/licenses/by-nc-nd/3.0/",
        False,
        False,
        False,
        True,
        "red",
    ),
    (
        "http://creativecommons.org/licenses/by-sa/2.5/es/",
        "cc-by-sa",
        "2.5",
        "es",
        "CC BY-SA 2.5 ES",
        f"{CC}/licenses/by-sa/2.5/es/",
        True,
        True,
        True,
        True,
        "amber",
    ),
    (
        "http://creativecommons.org/licenses/by/2.0/be/",
        "cc-by",
        "2.0",
        "be",
        "CC BY 2.0 BE",
        f"{CC}/licenses/by/2.0/be/",
        True,
        True,
        False,
        True,
        "green",
    ),
    (
        "http://creativecommons.org/licenses/by-nc-nd/2.0/fr/",
        "cc-by-nc-nd",
        "2.0",
        "fr",
        "CC BY-NC-ND 2.0 FR",
        f"{CC}/licenses/by-nc-nd/2.0/fr/",
        False,
        False,
        False,
        True,
        "red",
    ),
    (
        "http://artlibre.org/licence/lal/",
        "fal",
        None,
        None,
        "Free Art License",
        FAL,
        True,
        True,
        True,
        True,
        "amber",
    ),
    # Public domain URLs.
    (
        "https://creativecommons.org/publicdomain/zero/1.0/",
        "cc0",
        "1.0",
        None,
        "CC0 1.0",
        f"{CC}/publicdomain/zero/1.0/",
        True,
        True,
        False,
        False,
        "green",
    ),
    (
        "http://creativecommons.org/publicdomain/mark/1.0",
        "pdm",
        "1.0",
        None,
        "Public Domain Mark 1.0",
        f"{CC}/publicdomain/mark/1.0/",
        True,
        True,
        False,
        False,
        "green",
    ),
    # Other CC families by URL.
    (
        "https://creativecommons.org/licenses/by-nc/4.0/",
        "cc-by-nc",
        "4.0",
        None,
        "CC BY-NC 4.0",
        f"{CC}/licenses/by-nc/4.0/",
        False,
        True,
        False,
        True,
        "red",
    ),
    (
        "https://creativecommons.org/licenses/by-nc-sa/4.0/",
        "cc-by-nc-sa",
        "4.0",
        None,
        "CC BY-NC-SA 4.0",
        f"{CC}/licenses/by-nc-sa/4.0/",
        False,
        True,
        True,
        True,
        "red",
    ),
    (
        "https://creativecommons.org/licenses/by-nd/4.0/",
        "cc-by-nd",
        "4.0",
        None,
        "CC BY-ND 4.0",
        f"{CC}/licenses/by-nd/4.0/",
        True,
        False,
        False,
        True,
        "red",
    ),
    # CC Sampling+ (Freesound): not usable as is in a commercial game, so red.
    (
        "http://creativecommons.org/licenses/sampling+/1.0/",
        "sampling-plus",
        "1.0",
        None,
        "CC Sampling+ 1.0",
        f"{CC}/licenses/sampling+/1.0/",
        False,
        True,
        False,
        True,
        "red",
    ),
    (
        "https://creativecommons.org/licenses/sampling+/1.0",
        "sampling-plus",
        "1.0",
        None,
        "CC Sampling+ 1.0",
        f"{CC}/licenses/sampling+/1.0/",
        False,
        True,
        False,
        True,
        "red",
    ),
    (
        "cc-sampling+",
        "sampling-plus",
        "1.0",
        None,
        "CC Sampling+ 1.0",
        f"{CC}/licenses/sampling+/1.0/",
        False,
        True,
        False,
        True,
        "red",
    ),
    (
        "Sampling+",
        "sampling-plus",
        "1.0",
        None,
        "CC Sampling+ 1.0",
        f"{CC}/licenses/sampling+/1.0/",
        False,
        True,
        False,
        True,
        "red",
    ),
    # Freesound licence URLs (http and https, 3.0 and 4.0).
    (
        "http://creativecommons.org/licenses/by-nc/3.0/",
        "cc-by-nc",
        "3.0",
        None,
        "CC BY-NC 3.0",
        f"{CC}/licenses/by-nc/3.0/",
        False,
        True,
        False,
        True,
        "red",
    ),
    (
        "https://creativecommons.org/licenses/by/4.0/",
        "cc-by",
        "4.0",
        None,
        "CC BY 4.0",
        f"{CC}/licenses/by/4.0/",
        True,
        True,
        False,
        True,
        "green",
    ),
    (
        "http://creativecommons.org/publicdomain/zero/1.0/",
        "cc0",
        "1.0",
        None,
        "CC0 1.0",
        f"{CC}/publicdomain/zero/1.0/",
        True,
        True,
        False,
        False,
        "green",
    ),
    # Short codes.
    (
        "CC0",
        "cc0",
        "1.0",
        None,
        "CC0 1.0",
        f"{CC}/publicdomain/zero/1.0/",
        True,
        True,
        False,
        False,
        "green",
    ),
    (
        "PDM",
        "pdm",
        "1.0",
        None,
        "Public Domain Mark 1.0",
        f"{CC}/publicdomain/mark/1.0/",
        True,
        True,
        False,
        False,
        "green",
    ),
    ("CC-BY", "cc-by", None, None, "CC BY", None, True, True, False, True, "green"),
    (
        "CC-BY-4.0",
        "cc-by",
        "4.0",
        None,
        "CC BY 4.0",
        f"{CC}/licenses/by/4.0/",
        True,
        True,
        False,
        True,
        "green",
    ),
    (
        "CC BY-SA 3.0",
        "cc-by-sa",
        "3.0",
        None,
        "CC BY-SA 3.0",
        f"{CC}/licenses/by-sa/3.0/",
        True,
        True,
        True,
        True,
        "amber",
    ),
    ("CC-BY-NC", "cc-by-nc", None, None, "CC BY-NC", None, False, True, False, True, "red"),
    ("CC-BY-NC-SA", "cc-by-nc-sa", None, None, "CC BY-NC-SA", None, False, True, True, True, "red"),
    (
        "CC-BY-NC-ND",
        "cc-by-nc-nd",
        None,
        None,
        "CC BY-NC-ND",
        None,
        False,
        False,
        False,
        True,
        "red",
    ),
    ("CC-BY-ND", "cc-by-nd", None, None, "CC BY-ND", None, True, False, False, True, "red"),
    (
        "Pixabay",
        "pixabay",
        None,
        None,
        "Pixabay Content License",
        PIX,
        True,
        True,
        False,
        False,
        "green",
    ),
    ("FAL", "fal", None, None, "Free Art License", FAL, True, True, True, True, "amber"),
    ("custom", "custom", None, None, "Custom license", None, None, None, None, None, "unknown"),
    ("unknown", "unknown", None, None, "Unknown license", None, None, None, None, None, "unknown"),
]


@pytest.mark.parametrize(
    "value,family,version,jur,code,url,commercial,derivatives,share_alike,attribution,risk",
    CASES,
    ids=[c[0] for c in CASES],
)
def test_parse_table(
    value, family, version, jur, code, url, commercial, derivatives, share_alike, attribution, risk
):
    info = parse_license(value)
    assert info.family == family
    assert info.version == version
    assert info.jurisdiction == jur
    assert info.code == code
    assert info.url == url
    assert info.commercial_ok is commercial
    assert info.derivatives_ok is derivatives
    assert info.share_alike is share_alike
    assert info.attribution_required is attribution
    assert info.risk == risk


@pytest.mark.parametrize(
    "value",
    [
        "HTTP://CREATIVECOMMONS.ORG/LICENSES/BY-NC-ND/3.0/",
        "  http://creativecommons.org/licenses/by-nc-nd/3.0/  \n",
        "https://creativecommons.org/licenses/by-nc-nd/3.0/",
        "http://creativecommons.org/licenses/by-nc-nd/3.0",
        "https://www.creativecommons.org/licenses/by-nc-nd/3.0",
        "https://creativecommons.org/licenses/by-nc-nd/3.0/deed.en",
        "cc by-nc-nd 3.0",
        "cc_by_nc_nd_3.0",
        "CC BY-NC-ND 3.0",
    ],
)
def test_variants_normalize_to_same_license(value):
    expected = parse_license("http://creativecommons.org/licenses/by-nc-nd/3.0/")
    assert parse_license(value) == expected


def test_jurisdiction_url_is_lowercase_and_code_uppercase():
    info = parse_license("HTTPS://creativecommons.org/licenses/by-sa/2.5/ES")
    assert info.jurisdiction == "es"
    assert info.url == f"{CC}/licenses/by-sa/2.5/es/"
    assert info.code == "CC BY-SA 2.5 ES"


def test_short_code_with_jurisdiction():
    info = parse_license("CC BY-NC-ND 3.0 FR")
    assert (info.family, info.version, info.jurisdiction) == ("cc-by-nc-nd", "3.0", "fr")
    assert info.url == f"{CC}/licenses/by-nc-nd/3.0/fr/"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        None,
        "foo",
        "http://example.com",
        "http://creativecommons.org/",
        "http://creativecommons.org/licenses/by-xx/3.0/",
        "http://creativecommons.org/licenses/zero/1.0/",
        "http://creativecommons.org/licenses/sampling/1.0/",
        "http://creativecommons.org/licenses/sampling++/1.0/",
        "http://creativecommons.org/publicdomain/sampling+/1.0/",
        "sampling+x",
        "http://creativecommons.org/publicdomain/by/1.0/",
        "cc-bx-4.0",
        "all rights reserved",
        42,
        b"cc0",
    ],
)
def test_garbage_is_unknown_and_never_raises(value):
    info = parse_license(value)
    assert info.family == "unknown"
    assert info.risk == "unknown"
    assert info.code == "Unknown license"
    assert info.url is None
    assert info.commercial_ok is None
    assert info.derivatives_ok is None
    assert info.share_alike is None
    assert info.attribution_required is None


def test_license_info_is_frozen():
    info = parse_license("CC0")
    with pytest.raises(dataclasses.FrozenInstanceError):
        info.risk = "red"  # type: ignore[misc]


@pytest.mark.parametrize(
    "commercial,derivatives,share_alike,risk",
    [
        (False, True, False, "red"),
        (False, False, False, "red"),
        (False, True, True, "red"),
        (True, False, False, "red"),
        (True, False, True, "red"),
        (True, True, True, "amber"),
        (True, True, False, "green"),
    ],
)
def test_custom_license_risk_matrix(commercial, derivatives, share_alike, risk):
    info = custom_license(
        commercial_ok=commercial,
        derivatives_ok=derivatives,
        attribution_required=True,
        share_alike=share_alike,
    )
    assert info.family == "custom"
    assert info.risk == risk
    assert info.commercial_ok is commercial
    assert info.derivatives_ok is derivatives
    assert info.share_alike is share_alike
    assert info.attribution_required is True
    assert info.url is None


def test_custom_license_name_and_default_code():
    named = custom_license(
        commercial_ok=True,
        derivatives_ok=True,
        attribution_required=False,
        name="Unity Asset Store EULA",
    )
    assert named.code == "Unity Asset Store EULA"
    assert named.attribution_required is False
    unnamed = custom_license(commercial_ok=True, derivatives_ok=True, attribution_required=False)
    assert unnamed.code == "Custom license"
    assert unnamed.share_alike is False


def test_risk_order():
    assert RISK_ORDER == ("green", "amber", "red", "unknown")


@pytest.mark.parametrize("risk", RISK_ORDER)
@pytest.mark.parametrize("max_risk", RISK_ORDER)
def test_risk_at_most_truth_table(risk, max_risk):
    assert risk_at_most(risk, max_risk) is (RISK_ORDER.index(risk) <= RISK_ORDER.index(max_risk))


def test_risk_at_most_unknown_is_worse_than_red():
    assert risk_at_most("unknown", "red") is False
    assert risk_at_most("red", "red") is True
    assert risk_at_most("green", "amber") is True
    assert risk_at_most("amber", "green") is False
    assert risk_at_most("unknown", "unknown") is True
