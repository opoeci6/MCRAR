"""Download helpers shared by the routes that hand out a credits report as a file.

The file name comes from a track title or project name, which are user text, so it is reduced to
``[A-Za-z0-9._-]`` before it goes into the ``Content-Disposition`` header.
"""

from __future__ import annotations

import re

from fastapi.responses import Response

CREDITS_TYPES = {
    "txt": ("text/plain; charset=utf-8", "txt"),
    "md": ("text/markdown; charset=utf-8", "md"),
    "json": ("application/json", "json"),
}


def safe_stem(name: str | None, fallback: str) -> str:
    """A header-safe file name stem of at most 60 characters."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name or "").strip("-.")[:60] or fallback


def credits_download(body: str, fmt: str, *, stem: str, suffix: str) -> Response:
    """``body`` as an attachment named ``<stem>-<suffix>.<ext>`` with the format's media type."""
    media_type, extension = CREDITS_TYPES[fmt]
    return Response(
        body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{stem}-{suffix}.{extension}"'},
    )
