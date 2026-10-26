"""Reading an audio upload safely, shared by ``POST /api/analyze`` and ``POST /api/reference``.

The file name is reduced to its base name (never a path from the client), the extension must be an
audio one the library scans for, and the size limit is enforced while reading in chunks, so a client
that lies about (or omits) ``Content-Length`` is still stopped. The limit is a parameter, read by
each route from its own module constant at call time.
"""

from __future__ import annotations

from pathlib import PureWindowsPath

from fastapi import HTTPException, UploadFile

from mcrar.sources.local_folder import AUDIO_EXTENSIONS

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
_CHUNK = 1024 * 1024


def read_limited(upload: UploadFile, max_bytes: int) -> bytes:
    """The upload's bytes; HTTP 413 as soon as more than ``max_bytes`` have been read."""
    chunks: list[bytes] = []
    total = 0
    while chunk := upload.file.read(_CHUNK):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(413, f"file too large (limit {max_bytes // 2**20} MB)")
        chunks.append(chunk)
    return b"".join(chunks)


def read_audio_upload(upload: UploadFile, max_bytes: int) -> tuple[str, bytes]:
    """``(base file name, bytes)`` of an audio upload; HTTP 422 for an unsupported extension and
    413 for a file over ``max_bytes``."""
    filename = PureWindowsPath(upload.filename or "").name  # handles both / and \ separators
    suffix = PureWindowsPath(filename).suffix.lower()
    if suffix not in AUDIO_EXTENSIONS:
        allowed = ", ".join(sorted(AUDIO_EXTENSIONS))
        raise HTTPException(422, f"unsupported file type '{suffix[:16]}'; use one of: {allowed}")
    return filename, read_limited(upload, max_bytes)
