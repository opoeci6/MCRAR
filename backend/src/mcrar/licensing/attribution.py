"""TASL (Title, Author, Source, License) attribution text."""

from __future__ import annotations

from mcrar.licensing.model import LicenseInfo


def attribution_text(
    *,
    title: str,
    artist: str | None,
    license: LicenseInfo,  # noqa: A002
    source_url: str | None = None,
    extra: str | None = None,
) -> str:
    """Build a one-line credit following the TASL convention.

    `extra` (a user-declared attribution string) is appended verbatim after a space.
    """
    who = (artist or "").strip() or "Unknown artist"
    text = f'"{title}" by {who}'
    if source_url:
        text += f" ({source_url})"
    if license.family in ("cc0", "pdm"):
        text += f", dedicated to the public domain ({license.code})"
    elif license.family == "unknown":
        text += ", license unknown"
    else:
        text += f", licensed under {license.code}"
        if license.url:
            text += f" ({license.url})"
    if extra:
        text += f" {extra}"
    return text
