"""``POST /api/analyze``: BPM, key, loudness and energy of an uploaded reference track.

Nothing is stored: the bytes are analysed in memory and dropped, and the response carries only the
base name of the upload (never a path from the client). The upload is read by
:mod:`mcrar.api.uploads` (extension check, size limit enforced while reading).
``mcrar.audio`` (librosa, scipy) is imported inside the endpoint to keep the API import light.
The endpoint is a plain ``def``, so FastAPI runs the analysis in its thread pool.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile

from mcrar.api.uploads import MAX_UPLOAD_BYTES, read_audio_upload

router = APIRouter()


@router.post("/api/analyze")
def analyze(file: UploadFile) -> dict[str, Any]:
    from mcrar.audio import AudioError, analyze_audio

    filename, data = read_audio_upload(file, MAX_UPLOAD_BYTES)
    try:
        features = analyze_audio(data)
    except AudioError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"filename": filename, "features": features.to_dict()}
