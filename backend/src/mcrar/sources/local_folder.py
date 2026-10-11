"""Local-folder source: scan a folder of audio files, with licences declared by sidecar files.

A file is identified by the sha256 of its content (``source_id``), so renamed or moved files keep
their catalog row and byte-identical copies collapse into one track. The licence of a file comes
from the nearest ``mcrar-license.toml`` between the file's directory and the scan root; without
one it is unknown. A broken sidecar never crashes the scan: it is logged and its subtree is
treated as unknown.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from mcrar.licensing import LicenseInfo, custom_license, parse_license
from mcrar.licensing.model import unknown_license
from mcrar.sources.base import SourceTrack

logger = logging.getLogger(__name__)

SOURCE_NAME = "local"
SIDECAR_NAME = "mcrar-license.toml"
AUDIO_EXTENSIONS = frozenset(
    {".wav", ".wave", ".flac", ".ogg", ".oga", ".opus", ".mp3", ".aif", ".aiff"}
)
_CHUNK = 1024 * 1024
_CUSTOM_FLAGS = ("commercial_ok", "derivatives_ok", "attribution_required", "share_alike")


@dataclass(frozen=True)
class LocalItem:
    """One audio file found by :func:`scan_local`, with its resolved licence."""

    path: Path
    source_track: SourceTrack
    license: LicenseInfo
    attribution_extra: str | None = None


@dataclass(frozen=True)
class _Sidecar:
    """A parsed ``mcrar-license.toml``. ``valid=False`` means: unknown licence, no metadata."""

    valid: bool = True
    license: LicenseInfo | None = None  # None: the sidecar does not declare a licence
    artist: str | None = None
    pack: str | None = None
    source_url: str | None = None
    attribution: str | None = None


class _SidecarError(ValueError):
    pass


def _optional_str(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _SidecarError(f"'{key}' must be a string")
    return value.strip() or None


def _parse_license_field(data: dict[str, object], path: Path) -> LicenseInfo | None:
    raw = data.get("license")
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise _SidecarError("'license' must be a string")
    text = raw.strip()
    if text.lower() == "custom":
        flags: dict[str, bool] = {}
        for key in _CUSTOM_FLAGS:
            value = data.get(key)
            if not isinstance(value, bool):
                raise _SidecarError(f"license = \"custom\" needs '{key}' (true or false)")
            flags[key] = value
        return custom_license(name=_optional_str(data, "name"), **flags)
    info = parse_license(text)
    if info.family == "unknown" and text.lower() != "unknown":
        logger.warning("Unrecognised license %r in %s; treating it as unknown", text, path)
    return info


def _read_sidecar(path: Path) -> _Sidecar:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return _Sidecar(
            license=_parse_license_field(data, path),
            artist=_optional_str(data, "artist"),
            pack=_optional_str(data, "pack"),
            source_url=_optional_str(data, "source_url"),
            attribution=_optional_str(data, "attribution"),
        )
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, _SidecarError) as exc:
        logger.warning("Ignoring invalid license sidecar %s: %s", path, exc)
        return _Sidecar(valid=False)


def _is_hidden(name: str) -> bool:
    return name.startswith(".")


def iter_audio_files(root: str | os.PathLike[str]) -> Iterator[Path]:
    """Audio files under ``root`` (recursive, sorted, hidden files and folders skipped)."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not _is_hidden(d))
        for name in sorted(filenames):
            if not _is_hidden(name) and Path(name).suffix.lower() in AUDIO_EXTENSIONS:
                yield Path(dirpath) / name


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _probe_duration(path: Path) -> float | None:
    from mcrar.audio import probe_audio  # lazy: keeps the heavy audio stack off import

    try:
        return float(probe_audio(path).duration_s)
    except Exception:  # noqa: BLE001 - surfaces again, properly, at analysis time
        return None


def scan_local(
    root: str | os.PathLike[str], *, license_override: str | None = None
) -> Iterator[LocalItem]:
    """Yield one :class:`LocalItem` per audio file under ``root``, in sorted order.

    ``license_override`` (a licence code or URL) replaces the licence of every file; the artist,
    pack, attribution and source_url of a valid sidecar still apply. Arguments are validated
    immediately (``NotADirectoryError``, ``ValueError``), not on first iteration.
    """
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise NotADirectoryError(f"not a folder: {root}")
    override: LicenseInfo | None = None
    if license_override is not None:
        override = parse_license(license_override)
        if override.family == "unknown" and license_override.strip().lower() != "unknown":
            raise ValueError(f"unrecognised license: {license_override!r}")
    return _scan(root_path, override)


def _scan(root: Path, override: LicenseInfo | None) -> Iterator[LocalItem]:
    sidecars: dict[Path, _Sidecar | None] = {}

    def nearest(directory: Path) -> _Sidecar | None:
        if directory not in sidecars:
            candidate = directory / SIDECAR_NAME
            if candidate.is_file():
                sidecars[directory] = _read_sidecar(candidate)
            elif directory == root or directory.parent == directory:
                sidecars[directory] = None
            else:
                sidecars[directory] = nearest(directory.parent)
        return sidecars[directory]

    for path in iter_audio_files(root):
        try:
            source_id = file_sha256(path)
        except OSError as exc:
            logger.warning("Skipping unreadable file %s: %s", path, type(exc).__name__)
            continue
        sidecar = nearest(path.parent)
        meta = sidecar if sidecar is not None and sidecar.valid else _Sidecar()
        license_info = override or meta.license or unknown_license()
        absolute = path.absolute()
        yield LocalItem(
            path=absolute,
            source_track=SourceTrack(
                source=SOURCE_NAME,
                source_id=source_id,
                title=path.stem,
                artist=meta.artist,
                album=meta.pack or path.parent.name or None,
                duration_s=_probe_duration(path),
                source_url=meta.source_url,
                local_path=str(absolute),
            ),
            license=license_info,
            attribution_extra=meta.attribution,
        )
