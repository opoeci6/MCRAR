"""Console output that never fails on a narrow code page.

Piped or redirected output on Windows uses the locale encoding (for example GBK or cp1252),
which cannot hold every track title or path; unencodable characters become "?".
"""

from __future__ import annotations

import sys

import typer


def echo(text: str = "", *, err: bool = False) -> None:
    """Echo text that may hold arbitrary titles without ever failing on a narrow console."""
    stream = sys.stderr if err else sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    typer.echo(text.encode(encoding, "replace").decode(encoding), err=err)
