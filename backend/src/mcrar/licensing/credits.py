"""Render a credits / license report for a set of tracks as txt, md or json."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Literal

from mcrar.licensing.attribution import attribution_text
from mcrar.licensing.model import LicenseInfo, Risk

if TYPE_CHECKING:
    from mcrar.catalog import StoredTrack

LICENSE_DISCLAIMER = (
    "Risk levels (green, amber, red, unknown) are informational guidance for using music in a "
    "commercial game, not legal advice. Always verify each track's license on its source page "
    "before you use it."
)

# Red last, so the tracks that need action sit at the end of the report.
_RENDER_ORDER: tuple[Risk, ...] = ("green", "amber", "unknown", "red")
_TITLES: dict[Risk, str] = {
    "green": "Green: generally safe",
    "amber": "Amber: copyleft, check share-alike",
    "unknown": "Unknown: license could not be determined",
    "red": "Red: not usable in a commercial game as is",
}


@dataclass(frozen=True)
class CreditItem:
    title: str
    artist: str | None
    license: LicenseInfo
    source_url: str | None = None
    attribution_extra: str | None = None
    commercial_license_url: str | None = None

    @property
    def attribution(self) -> str:
        return attribution_text(
            title=self.title,
            artist=self.artist,
            license=self.license,
            source_url=self.source_url,
            extra=self.attribution_extra,
        )


def _sorted(items: Sequence[CreditItem]) -> list[CreditItem]:
    return sorted(
        items,
        key=lambda i: (
            _RENDER_ORDER.index(i.license.risk),
            i.title.casefold(),
            (i.artist or "").casefold(),
            i.source_url or "",
            i.title,
            i.artist or "",
        ),
    )


def _lines(item: CreditItem, bullet: str) -> list[str]:
    lic = item.license
    license_line = lic.code + (f" ({lic.url})" if lic.url else "")
    out = [f"{bullet}License: {license_line}", f"{bullet}Risk: {lic.risk}"]
    if item.source_url:
        out.append(f"{bullet}Source: {item.source_url}")
    if lic.risk == "red" and item.commercial_license_url:
        out.append(f"{bullet}Commercial license available: {item.commercial_license_url}")
    out.append(f"{bullet}Attribution: {item.attribution}")
    return out


def _heading(item: CreditItem) -> str:
    return f'"{item.title}" by {(item.artist or "").strip() or "Unknown artist"}'


def _render_txt(items: list[CreditItem]) -> str:
    out = ["MUSIC CREDITS", "", LICENSE_DISCLAIMER]
    for risk in _RENDER_ORDER:
        group = [i for i in items if i.license.risk == risk]
        if not group:
            continue
        out += ["", f"== {_TITLES[risk]} =="]
        for item in group:
            out += ["", _heading(item), *_lines(item, "  ")]
    return "\n".join(out) + "\n"


def _render_md(items: list[CreditItem]) -> str:
    out = ["# Music credits", "", f"> {LICENSE_DISCLAIMER}"]
    for risk in _RENDER_ORDER:
        group = [i for i in items if i.license.risk == risk]
        if not group:
            continue
        out += ["", f"## {_TITLES[risk]}"]
        for item in group:
            out += ["", f"### {_heading(item)}", "", *_lines(item, "- ")]
    return "\n".join(out) + "\n"


def _render_json(items: list[CreditItem]) -> str:
    payload = {
        "disclaimer": LICENSE_DISCLAIMER,
        "items": [
            {
                "title": i.title,
                "artist": i.artist,
                "license": asdict(i.license),
                "source_url": i.source_url,
                "attribution_extra": i.attribution_extra,
                "commercial_license_url": i.commercial_license_url,
                "attribution": i.attribution,
            }
            for i in items
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def render_credits(items: Sequence[CreditItem], fmt: Literal["txt", "md", "json"]) -> str:
    """Render credits grouped by risk (green, amber, unknown, red last), sorted deterministically.

    The json format is an object `{"disclaimer": ..., "items": [...]}`.
    """
    ordered = _sorted(items)
    if fmt == "txt":
        return _render_txt(ordered)
    if fmt == "md":
        return _render_md(ordered)
    if fmt == "json":
        return _render_json(ordered)
    raise ValueError(f"unsupported credits format: {fmt!r}")


def track_credits(track: StoredTrack, fmt: Literal["txt", "md", "json"]) -> str:
    """The credits / licence report of one catalog track (what the track page downloads).

    A first version: one item from the stored licence columns. A user-declared attribution
    suffix kept in the stored ``attribution_text`` is passed on as the item's extra.
    """
    license_info = LicenseInfo(
        family=track.license_family or "unknown",  # type: ignore[arg-type]
        version=None,
        jurisdiction=None,
        code=track.license_code or "Unknown license",
        url=track.license_url,
        commercial_ok=track.commercial_ok,
        derivatives_ok=track.derivatives_ok,
        share_alike=track.share_alike,
        attribution_required=track.attribution_required,
        risk=track.risk,  # type: ignore[arg-type]
    )
    title = track.title or "Untitled"
    generated = attribution_text(
        title=title, artist=track.artist, license=license_info, source_url=track.source_url
    )
    stored = (track.attribution_text or "").strip()
    extra = stored[len(generated) :].strip() if stored.startswith(generated) else ""
    item = CreditItem(
        title=title,
        artist=track.artist,
        license=license_info,
        source_url=track.source_url,
        attribution_extra=extra or None,
        commercial_license_url=track.commercial_license_url,
    )
    return render_credits([item], fmt)
