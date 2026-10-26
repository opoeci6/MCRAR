"""``POST /api/reference``: embed an uploaded song to search for similar tracks.

The upload (same rules as ``/api/analyze``, see :mod:`mcrar.api.uploads`) is embedded with the
default embedder from the server's model pool, the model catalog tracks are embedded with, by the
same recipe (:func:`mcrar.ml.embedders.embed_audio_source`). The vector goes into the in-memory
:class:`~mcrar.api.references.ReferenceStore`; the response carries an ``upload_id`` that
``POST /api/search`` takes as ``reference: {upload_id}``. The audio itself is not kept. Without
torch the endpoint answers 503, like a text search. The endpoint is a plain ``def``, so FastAPI runs
the embedding in its thread pool.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile

from mcrar.api.references import StoredReference
from mcrar.api.state import StateDep
from mcrar.api.uploads import MAX_UPLOAD_BYTES, read_audio_upload

router = APIRouter()


@router.post("/api/reference")
def upload_reference(file: UploadFile, state: StateDep) -> dict[str, Any]:
    from mcrar.audio import AudioError
    from mcrar.ml.embedders import embed_audio_source

    filename, data = read_audio_upload(file, MAX_UPLOAD_BYTES)
    embedder = state.pool.get(state.settings.default_embedder)  # 503 without the ml extra
    try:
        embedded = embed_audio_source(embedder, data)
    except AudioError as exc:
        raise HTTPException(422, str(exc)) from None
    upload_id = state.references.put(
        StoredReference(embedded.vector, embedder.model_id, filename, embedded.duration_s)
    )
    return {
        "upload_id": upload_id,
        "filename": filename,
        "duration_s": embedded.duration_s,
        "model_id": embedder.model_id,
    }
