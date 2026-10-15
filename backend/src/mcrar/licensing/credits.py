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
    # A stored, ready-made credit line (catalog ``attribution_text``); used verbatim when set.
    attribution_override: str | None = None

    @property
    def attribution(self) -> str:
        if self.attribution_override:
            return self.attribution_override
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


def _render_txt(items: list[CreditItem], project: str | None) -> str:
    out = ["MUSIC CREDITS" + (f": {project}" if project else ""), "", LICENSE_DISCLAIMER]
    for risk in _RENDER_ORDER:
        group = [i for i in items if i.license.risk == risk]
        if not group:
            continue
        out += ["", f"== {_TITLES[risk]} =="]
        for item in group:
            out += ["", _heading(item), *_lines(item, "  ")]
    return "\n".join(out) + "\n"


def _render_md(items: list[CreditItem], project: str | None) -> str:
    title = "# Music credits" + (f": {project}" if project else "")
    out = [title, "", f"> {LICENSE_DISCLAIMER}"]
    for risk in _RENDER_ORDER:
        group = [i for i in items if i.license.risk == risk]
        if not group:
            continue
        out += ["", f"## {_TITLES[risk]}"]
        for item in group:
            out += ["", f"### {_heading(item)}", "", *_lines(item, "- ")]
    return "\n".join(out) + "\n"


def _render_json(items: list[CreditItem], project: str | None) -> str:
    payload: dict[str, object] = {"disclaimer": LICENSE_DISCLAIMER}
    if project is not None:
        payload["project"] = project
    payload["items"] = [
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
    ]
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def render_credits(
    items: Sequence[CreditItem],
    fmt: Literal["txt", "md", "json"],
    *,
    project: str | None = None,
) -> str:
    """Render credits grouped by risk (green, amber, unknown, red last), sorted deterministically.

    The json format is an object `{"disclaimer": ..., "items": [...]}`. With ``project`` the txt
    and md titles carry the name and the json object gains a ``"project"`` key.
    """
    ordered = _sorted(items)
    if fmt == "txt":
        return _render_txt(ordered, project)
    if fmt == "md":
        return _render_md(ordered, project)
    if fmt == "json":
        return _render_json(ordered, project)
    raise ValueError(f"unsupported credits format: {fmt!r}")


def track_credit_item(track: StoredTrack) -> CreditItem:
    """One credit entry from a catalog row.

    The licence is rebuilt from the stored columns (not by parsing the URL: a user-declared custom
    licence has none), so its risk and flags are exactly what the catalog holds. The stored
    ``attribution_text`` already carries any user-declared suffix and is the credit line verbatim;
    a row without one gets the generated TASL line.
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
    return CreditItem(
        title=title,
        artist=track.artist,
        license=license_info,
        source_url=track.source_url,
        attribution_extra=extra or None,
        commercial_license_url=track.commercial_license_url,
        attribution_override=stored or None,
    )


def track_credits(track: StoredTrack, fmt: Literal["txt", "md", "json"]) -> str:
    """The credits / licence report of one catalog track (what the track page downloads)."""
    return render_credits([track_credit_item(track)], fmt)


def project_credits(
    project_name: str, tracks: Sequence[StoredTrack], fmt: Literal["txt", "md", "json"]
) -> str:
    """The credits report of a project's shortlist, titled with the project name.

    Every track is listed, a track with an unknown licence in the unknown group. The json
    format gains a ``"project"`` key next to ``disclaimer`` and ``items``.
    """
    items = [track_credit_item(t) for t in tracks]
    return render_credits(items, fmt, project=project_name)
