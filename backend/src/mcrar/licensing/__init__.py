"""License parsing, risk classification, attribution text and credits rendering.

Everything here is pure: no network, no global state, no writes. Risk levels are guidance for
using music in a commercial game (syncing to visuals may create an adaptation), not legal advice.
"""

from mcrar.licensing.attribution import attribution_text
from mcrar.licensing.credits import LICENSE_DISCLAIMER, CreditItem, render_credits, track_credits
from mcrar.licensing.model import (
    RISK_ORDER,
    Family,
    LicenseInfo,
    Risk,
    custom_license,
    risk_at_most,
)
from mcrar.licensing.parse import parse_license

__all__ = [
    "LICENSE_DISCLAIMER",
    "RISK_ORDER",
    "CreditItem",
    "Family",
    "LicenseInfo",
    "Risk",
    "attribution_text",
    "custom_license",
    "parse_license",
    "render_credits",
    "risk_at_most",
    "track_credits",
]
