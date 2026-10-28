"""License data model, risk ordering and the custom (store EULA) license builder."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Family = Literal[
    "cc0",
    "pdm",
    "cc-by",
    "cc-by-sa",
    "cc-by-nd",
    "cc-by-nc",
    "cc-by-nc-sa",
    "cc-by-nc-nd",
    "sampling-plus",
    "pixabay",
    "fal",
    "custom",
    "unknown",
]
Risk = Literal["green", "amber", "red", "unknown"]

RISK_ORDER: tuple[Risk, ...] = ("green", "amber", "red", "unknown")


@dataclass(frozen=True)
class LicenseInfo:
    """A parsed license. Flags are `None` when unknown."""

    family: Family
    version: str | None
    jurisdiction: str | None
    code: str
    url: str | None
    commercial_ok: bool | None
    derivatives_ok: bool | None
    share_alike: bool | None
    attribution_required: bool | None
    risk: Risk


def risk_at_most(risk: Risk, max_risk: Risk) -> bool:
    """True when `risk` is no worse than `max_risk` (unknown is worse than red)."""
    return RISK_ORDER.index(risk) <= RISK_ORDER.index(max_risk)


def unknown_license() -> LicenseInfo:
    return LicenseInfo(
        family="unknown",
        version=None,
        jurisdiction=None,
        code="Unknown license",
        url=None,
        commercial_ok=None,
        derivatives_ok=None,
        share_alike=None,
        attribution_required=None,
        risk="unknown",
    )


def custom_license(
    *,
    commercial_ok: bool,
    derivatives_ok: bool,
    attribution_required: bool,
    share_alike: bool = False,
    name: str | None = None,
) -> LicenseInfo:
    """License declared by the user, e.g. an asset pack bought under a store EULA.

    Risk assumes the music is synced to visuals (a possible adaptation): red when commercial
    use is not allowed or derivatives are not allowed, amber with share-alike, else green.
    """
    risk: Risk
    if not commercial_ok or not derivatives_ok:
        risk = "red"
    elif share_alike:
        risk = "amber"
    else:
        risk = "green"
    return LicenseInfo(
        family="custom",
        version=None,
        jurisdiction=None,
        code=(name or "").strip() or "Custom license",
        url=None,
        commercial_ok=commercial_ok,
        derivatives_ok=derivatives_ok,
        share_alike=share_alike,
        attribution_required=attribution_required,
        risk=risk,
    )
