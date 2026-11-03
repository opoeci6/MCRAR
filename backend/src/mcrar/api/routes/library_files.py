"""Copy a music file into the library folder (``<data_dir>/library``), for a browser that cannot
give the server a path (a remote or sandboxed client).

``POST /api/library/files?name=<original file name>`` takes the raw file bytes as the request body
(not multipart), streams them to a temporary ``.part`` file while hashing, then names the file
``<sha256><extension>``, so the same bytes always land in the same file and nothing is stored
twice. The name the client sent only decides the extension (reduced to its base name first, and it
must be an audio one); it is never used as a path. The limit is checked against ``Content-Length``
at once and again while reading, so a client that lies about its size is still stopped. A failed or
dropped upload never leaves its ``.part`` file behind. ``POST /api/ingest/files`` then adds the
files to the catalog.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING, Annotated, Any

import anyio.to_thread
from fastapi import APIRouter, HTTPException, Query, Request, Response

from mcrar.api.state import StateDep
from mcrar.sources.local_folder import AUDIO_EXTENSIONS

if TYPE_CHECKING:
    from mcrar.config import Settings

router = APIRouter()

MAX_LIBRARY_FILE_BYTES = 2 * 1024**3
LIBRARY_DIRNAME = "library"
INCOMING_DIRNAME = ".incoming"


def library_dir(settings: Settings) -> Path:
    """The folder that holds the copied-in files (it may not exist yet)."""
    return settings.data_dir / LIBRARY_DIRNAME


def _too_large() -> HTTPException:
    return HTTPException(413, f"file too large (limit {MAX_LIBRARY_FILE_BYTES // 2**20} MB)")


@router.post("/api/library/files", status_code=201)
async def upload_library_file(
    request: Request,
    state: StateDep,
    response: Response,
    name: Annotated[str, Query(max_length=1000)],
) -> dict[str, Any]:
    """Store the request body as ``<sha256><ext>`` in the library folder.

    201 for a new file, 200 with ``already: true`` when the same bytes are already there.
    """
    filename = PureWindowsPath(name).name  # handles both / and \ separators
    suffix = PureWindowsPath(filename).suffix.lower()
    if suffix not in AUDIO_EXTENSIONS:
        allowed = ", ".join(sorted(AUDIO_EXTENSIONS))
        raise HTTPException(422, f"unsupported file type '{suffix[:16]}'; use one of: {allowed}")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_LIBRARY_FILE_BYTES:
        raise _too_large()

    library = library_dir(state.settings)
    incoming = library / INCOMING_DIRNAME
    incoming.mkdir(parents=True, exist_ok=True)
    part = incoming / f"{uuid.uuid4().hex}.part"
    digest = hashlib.sha256()
    size = 0

    def write(handle: Any, chunk: bytes) -> None:
        handle.write(chunk)
        digest.update(chunk)

    try:
        with part.open("wb") as handle:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_LIBRARY_FILE_BYTES:
                    raise _too_large()
                await anyio.to_thread.run_sync(write, handle, chunk)
        if size == 0:
            raise HTTPException(422, "the file is empty")
        final = library / f"{digest.hexdigest()}{suffix}"
        already = final.exists()
        if not already:
            os.replace(part, final)
    finally:
        part.unlink(missing_ok=True)  # gone already after a successful os.replace
    if already:
        response.status_code = 200
    return {"file": final.name, "name": filename, "size": size, "already": already}
