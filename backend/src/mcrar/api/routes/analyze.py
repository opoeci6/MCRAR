"""``POST /api/analyze``: BPM, key, loudness and energy of an uploaded reference track.

Nothing is stored: the bytes are analysed in memory and dropped, and the response carries only the
base name of the upload (never a path from the client). The size limit is enforced while reading
the upload in chunks, so a client that lies about (or omits) ``Content-Length`` is still stopped.
``mcrar.audio`` (librosa, scipy) is imported inside the endpoint to keep the API import light.
The endpoint is a plain ``def``, so FastAPI runs the analysis in its thread pool.
"""

from __future__ import annotations

from pathlib import PureWindowsPath
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile

from mcrar.sources.local_folder import AUDIO_EXTENSIONS

router = APIRouter()

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
_CHUNK = 1024 * 1024


def _read_limited(upload: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while chunk := upload.file.read(_CHUNK):
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"file too large (limit {MAX_UPLOAD_BYTES // 2**20} MB)")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/api/analyze")
def analyze(file: UploadFile) -> dict[str, Any]:
    from mcrar.audio import AudioError, analyze_audio

    filename = PureWindowsPath(file.filename or "").name  # handles both / and \ separators
    suffix = PureWindowsPath(filename).suffix.lower()
    if suffix not in AUDIO_EXTENSIONS:
        allowed = ", ".join(sorted(AUDIO_EXTENSIONS))
        raise HTTPException(422, f"unsupported file type '{suffix[:16]}'; use one of: {allowed}")
    data = _read_limited(file)
    try:
        features = analyze_audio(data)
    except AudioError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"filename": filename, "features": features.to_dict()}
