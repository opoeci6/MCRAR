"""A folder browser for the local-music picker: drives, folders and how many audio files each has.

Only for a server that listens on loopback (the person at the keyboard): any other bind address
answers 403, because browsing the server's disk for a remote client would leak it. The routes are
read-only and never list files, only folders and a count of the audio files directly inside.
"""

from __future__ import annotations

import os
import string
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from mcrar.api.state import require_local_files
from mcrar.sources.local_folder import AUDIO_EXTENSIONS

router = APIRouter(dependencies=[Depends(require_local_files)])

MAX_ENTRIES = 2000  # directory entries looked at per folder; more than that is "truncated"
# FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM: what Explorer hides (AppData, the old
# "Application Data" junctions, $Recycle.Bin). Only Windows has st_file_attributes.
_HIDDEN_ATTRIBUTES = 0x2 | 0x4


def _hidden(entry: os.DirEntry[str]) -> bool:
    if entry.name.startswith("."):
        return True
    attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    return bool(attributes & _HIDDEN_ATTRIBUTES)


def _entry(path: Path, name: str | None = None) -> dict[str, str]:
    return {"name": name or path.name or str(path), "path": str(path)}


def _roots() -> list[Path]:
    if os.name == "nt":
        found = [Path(f"{letter}:\\") for letter in string.ascii_uppercase]
        return [p for p in found if _exists(p)]
    return [Path("/")]


def _exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


@router.get("/api/files/roots")
def file_roots() -> dict[str, Any]:
    """The drives (or ``/``) and the usual places (home and its Music folder)."""
    places: list[Path] = []
    try:
        home = Path.home()
    except (RuntimeError, OSError):
        home = None
    if home is not None:
        for candidate in (home, home / "Music"):
            if _exists(candidate) and candidate.is_dir():
                places.append(candidate)
    return {
        "roots": [_entry(p, str(p)) for p in _roots()],
        "places": [_entry(p) for p in places],
    }


@router.get("/api/files/list")
def file_list(path: str) -> dict[str, Any]:
    """The sub-folders of ``path`` (not recursive, hidden ones skipped: a leading dot, or the
    Windows hidden or system attribute; sorted without regard to case) and how many audio files
    are directly in it."""
    requested = Path(path)
    if not path.strip() or not requested.is_absolute():
        raise ValueError("path must be an absolute folder path")
    try:
        folder = requested.resolve()
        if not folder.exists():
            raise ValueError(f"folder not found: {folder}")
        if not folder.is_dir():
            raise ValueError(f"not a folder: {folder}")
    except OSError:
        raise ValueError(f"cannot read this folder: {path}") from None
    folders: list[Path] = []
    audio = 0
    truncated = False
    try:
        with os.scandir(folder) as entries:
            for seen, entry in enumerate(entries):
                if seen >= MAX_ENTRIES:
                    truncated = True
                    break
                try:
                    if _hidden(entry):
                        continue
                    is_dir = entry.is_dir()
                    is_file = not is_dir and entry.is_file()
                except OSError:
                    continue
                if is_dir:
                    folders.append(folder / entry.name)
                elif is_file and Path(entry.name).suffix.lower() in AUDIO_EXTENSIONS:
                    audio += 1
    except OSError:
        raise ValueError(f"cannot read this folder (no permission?): {folder}") from None
    folders.sort(key=lambda p: (p.name.lower(), p.name))
    parent = folder.parent
    return {
        "path": str(folder),
        "parent": None if parent == folder else str(parent),
        "folders": [_entry(p) for p in folders],
        "audio_files": audio,
        "truncated": truncated,
    }
