"""Parse license URLs (Jamendo `license_ccurl`) and short codes into `LicenseInfo`."""

from __future__ import annotations

import re

from mcrar.licensing.model import Family, LicenseInfo, Risk, unknown_license

PIXABAY_URL = "https://pixabay.com/service/license-summary/"
FAL_URL = "https://artlibre.org/licence/lal/en/"

# family -> (commercial_ok, derivatives_ok, share_alike, attribution_required, risk)
_TRAITS: dict[str, tuple[bool, bool, bool, bool, Risk]] = {
    "cc0": (True, True, False, False, "green"),
    "pdm": (True, True, False, False, "green"),
    "cc-by": (True, True, False, True, "green"),
    "cc-by-sa": (True, True, True, True, "amber"),
    "cc-by-nd": (True, False, False, True, "red"),
    "cc-by-nc": (False, True, False, True, "red"),
    "cc-by-nc-sa": (False, True, True, True, "red"),
    "cc-by-nc-nd": (False, False, False, True, "red"),
    "pixabay": (True, True, False, False, "green"),
    "fal": (True, True, True, True, "amber"),
}

_CC_URL = re.compile(
    r"^(?:https?://)?(?:www\.)?creativecommons\.org/(?P<kind>licenses|publicdomain)/"
    r"(?P<slug>[a-z-]+)/(?P<ver>\d+(?:\.\d+)?)(?:/(?P<jur>[a-z-]+))?"
    r"(?:/deed(?:\.[a-z-]+)?)?/?(?:[?#].*)?$"
)
_FAL_URL = re.compile(r"^(?:https?://)?(?:www\.)?artlibre\.org/licen[cs]e/lal(?:/[a-z-]*)?/?$")
_CC_CODE = re.compile(
    r"^cc-?(?:(?P<zero>0|zero)|by(?:-(?P<mods>nc-sa|nc-nd|nc|nd|sa))?)"
    r"(?:-(?P<ver>\d+(?:\.\d+)?))?(?:-(?P<jur>[a-z]{2,}))?$"
)

_URL_FAMILIES: dict[tuple[str, str], Family] = {
    ("licenses", "by"): "cc-by",
    ("licenses", "by-sa"): "cc-by-sa",
    ("licenses", "by-nd"): "cc-by-nd",
    ("licenses", "by-nc"): "cc-by-nc",
    ("licenses", "by-nc-sa"): "cc-by-nc-sa",
    ("licenses", "by-nc-nd"): "cc-by-nc-nd",
    ("publicdomain", "zero"): "cc0",
    ("publicdomain", "mark"): "pdm",
}
_NAMED_CODES: dict[str, Family] = {
    "pdm": "pdm",
    "public-domain-mark": "pdm",
    "pixabay": "pixabay",
    "pixabay-content-license": "pixabay",
    "fal": "fal",
    "lal": "fal",
    "free-art-license": "fal",
    "licence-art-libre": "fal",
    "custom": "custom",
}
_CC_BY_FAMILIES: dict[str | None, Family] = {
    None: "cc-by",
    "sa": "cc-by-sa",
    "nd": "cc-by-nd",
    "nc": "cc-by-nc",
    "nc-sa": "cc-by-nc-sa",
    "nc-nd": "cc-by-nc-nd",
}


def _build(
    family: Family, version: str | None = None, jurisdiction: str | None = None
) -> LicenseInfo:
    commercial, derivatives, share_alike, attribution, risk = _TRAITS[family]
    jur = jurisdiction.lower() if jurisdiction else None
    url: str | None
    if family == "cc0":
        version, jur = version or "1.0", None
        code, url = f"CC0 {version}", f"https://creativecommons.org/publicdomain/zero/{version}/"
    elif family == "pdm":
        version, jur = version or "1.0", None
        code = f"Public Domain Mark {version}"
        url = f"https://creativecommons.org/publicdomain/mark/{version}/"
    elif family == "pixabay":
        code, url = "Pixabay Content License", PIXABAY_URL
    elif family == "fal":
        code, url = "Free Art License", FAL_URL
    else:
        slug = family[3:]
        code = "CC " + slug.upper()
        url = None
        if version:
            code += f" {version}"
            url = f"https://creativecommons.org/licenses/{slug}/{version}/"
            if jur:
                url += f"{jur}/"
        if jur:
            code += f" {jur.upper()}"
    return LicenseInfo(
        family=family,
        version=version,
        jurisdiction=jur,
        code=code,
        url=url,
        commercial_ok=commercial,
        derivatives_ok=derivatives,
        share_alike=share_alike,
        attribution_required=attribution,
        risk=risk,
    )


def _from_url(text: str) -> LicenseInfo | None:
    if _FAL_URL.match(text):
        return _build("fal")
    m = _CC_URL.match(text)
    if m is None:
        return None
    family = _URL_FAMILIES.get((m["kind"], m["slug"]))
    if family is None:
        return None
    return _build(family, m["ver"], m["jur"])


def _from_code(text: str) -> LicenseInfo | None:
    norm = re.sub(r"[\s_]+", "-", text)
    named = _NAMED_CODES.get(norm)
    if named == "custom":
        return LicenseInfo(
            family="custom",
            version=None,
            jurisdiction=None,
            code="Custom license",
            url=None,
            commercial_ok=None,
            derivatives_ok=None,
            share_alike=None,
            attribution_required=None,
            risk="unknown",
        )
    if named is not None:
        return _build(named)
    m = _CC_CODE.match(norm)
    if m is None:
        return None
    if m["zero"]:
        return _build("cc0", m["ver"])
    return _build(_CC_BY_FAMILIES[m["mods"]], m["ver"], m["jur"])


def parse_license(value: str | None) -> LicenseInfo:
    """Parse a license URL or short code. Never raises; garbage yields the unknown license.

    A bare `custom` code yields a custom license with unknown flags and `unknown` risk; use
    `custom_license(...)` when the terms are declared. CC codes without a version (`CC-BY`)
    have no canonical URL, since the version is genuinely unknown.
    """
    if not isinstance(value, str):
        return unknown_license()
    text = value.strip().lower()
    if not text or text == "unknown":
        return unknown_license()
    return _from_url(text) or _from_code(text) or unknown_license()
