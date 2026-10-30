"""``python -m mcrar``: the command line of the ``mcrar`` script (for the portable build)."""

from __future__ import annotations

from mcrar.cli import app

if __name__ == "__main__":
    app(prog_name="mcrar")
