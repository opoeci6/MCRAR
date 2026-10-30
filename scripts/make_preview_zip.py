"""Zip a staged app folder for scripts/build-preview.ps1.

Usage: python -I make_preview_zip.py <stage parent> <folder name> <out.zip>

Writes ``<out.zip>`` (ZIP64, deflate) holding ``<folder name>/...`` from ``<stage parent>``, with
forward-slash names and entries for empty folders, then prints ``files=N unpacked=B zip=B``.
The last entry is ``python/.complete``: unzip tools extract in archive order, so MCRAR.cmd can
tell a finished unzip from one that was cut off (stopped early, or out of disk space).
"""

from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path

COMPLETE_MARKER = "python/.complete"  # MCRAR.cmd checks for it before anything else


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: make_preview_zip.py <stage parent> <folder name> <out.zip>", file=sys.stderr)
        return 2
    parent, name, out = Path(argv[0]), argv[1], Path(argv[2])
    top = parent / name
    if not top.is_dir():
        print(f"error: {top} is not a folder", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    files = 0
    unpacked = 0
    with zipfile.ZipFile(
        out, "w", zipfile.ZIP_DEFLATED, allowZip64=True, compresslevel=6, strict_timestamps=False
    ) as archive:
        archive.write(top, name + "/")
        for folder, dirs, names in os.walk(top):
            dirs.sort()
            for sub in dirs:
                path = Path(folder, sub)
                if not any(path.iterdir()):
                    archive.write(path, f"{name}/{path.relative_to(top).as_posix()}/")
            for filename in sorted(names):
                path = Path(folder, filename)
                archive.write(path, f"{name}/{path.relative_to(top).as_posix()}")
                files += 1
                unpacked += path.stat().st_size
        archive.writestr(
            f"{name}/{COMPLETE_MARKER}",
            "Written last in the zip: MCRAR.cmd checks it to tell a finished unzip.\r\n",
        )
    print(f"files={files} unpacked={unpacked} zip={out.stat().st_size}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
