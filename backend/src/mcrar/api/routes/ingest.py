"""Ingest jobs: start an ingest or a re-run of embedding/tagging, watch it, cancel it.

Design
- ``POST /api/ingest/...`` validates the request, then starts one background job
  (:class:`~mcrar.api.jobs.JobManager`, one at a time, else 409) and answers 202 with the job.
  Everything that can fail fast fails before the job starts: a body that does not validate (422),
  a missing Jamendo client id (503), no torch for a re-embed or a search import (503).
- ``POST /api/search/import`` imports new Jamendo tracks for a text search (kind ``ingest-query``):
  the text is parsed like a search, the Jamendo queries come from
  :mod:`mcrar.recommend.jamendo_query` and the run stops after ``limit`` new tracks. It embeds
  with the default model and with CLAP.
- The job runs the same pipeline as the CLI (:mod:`mcrar.ingest.pipeline`) with the stages of
  :func:`mcrar.ingest.stages.build_stages`. Embedders come from the server's model pool, the same
  loaded model search uses; the job never closes it. Without torch an ingest still analyses the
  tracks and says so in a ``warning`` event, like ``mcrar ingest`` does.
- ``GET /api/jobs/{id}/events`` is a Server-Sent Events stream: it replays the job's events after
  ``Last-Event-ID`` (header) or ``?after=``, then waits for new ones and ends after the final
  ``done``/``failed``/``cancelled`` event. The wait runs in a worker thread so the event loop
  never blocks, in short slices so a closed connection frees the thread quickly; a ``: keepalive``
  comment goes out while the job is quiet.

The pipeline is imported inside the job functions: importing the API must stay light.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

import anyio.to_thread
from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from mcrar.api.jobs import FINAL_EVENTS, Job, JobBusyError, JobNotRunningError, ProgressSink
from mcrar.api.models import NO_TORCH_MESSAGE
from mcrar.api.routes.search import FiltersBody, resolve_filters
from mcrar.api.state import AppState, StateDep
from mcrar.recommend import SearchRequest
from mcrar.secrets import SecretError
from mcrar.sources import JamendoError

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcrar.ingest.pipeline import IngestReport, Stage

router = APIRouter()

POLL_S = 1.0  # longest wait for a new event before the stream checks on its client again
KEEPALIVE_S = 15.0
NO_JAMENDO_MESSAGE = "Jamendo client id is not set"
IMPORT_NEEDS_TEXT_MESSAGE = "describe the music to search Jamendo for"
NO_EMBED_WARNING = (
    "embedding skipped: torch is not installed, so tracks are analysed but not embedded "
    "(install the ml extra: uv sync --extra ml)"
)
NO_TAGGING_WARNING = "no tagging models are installed (models/registry.json is missing)"


class JamendoIngestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tags: list[Annotated[str, Field(max_length=100)]] | None = Field(None, max_length=20)
    fuzzytags: list[Annotated[str, Field(max_length=100)]] | None = Field(None, max_length=20)
    search: str | None = Field(None, max_length=200)
    vocalinstrumental: Literal["vocal", "instrumental"] | None = None
    commercial_only: bool = False
    order: str | None = Field(None, max_length=50)
    limit: int = Field(50, ge=1, le=1000)
    embed: bool = True
    force: bool = False


class SearchImportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=300)
    filters: FiltersBody = Field(default_factory=FiltersBody)
    limit: int = Field(50, ge=1, le=100)


class LocalIngestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=1000)
    license: str | None = Field(None, max_length=200)
    force: bool = False
    embed: bool = True


class ReprocessBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    what: Literal["embed", "tag"]
    force: bool = False
    source: Literal["jamendo", "local"] | None = None


# -- starting jobs -------------------------------------------------------------------------------


def _start(
    state: AppState,
    kind: str,
    params: dict[str, Any],
    run: Callable[[ProgressSink], IngestReport],
    *,
    cleanup: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Start the job, or answer 409 (after ``cleanup``, which frees what ``run`` would have)."""
    try:
        job = state.jobs.start(kind, params, run)
    except JobBusyError as exc:
        if cleanup is not None:
            cleanup()
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"job": job.to_dict()}


def _open_jamendo(state: AppState) -> Any:
    try:
        return state.open_jamendo()
    except (JamendoError, SecretError):
        raise HTTPException(status_code=503, detail=NO_JAMENDO_MESSAGE) from None


def _ingest_stages(state: AppState, embed: bool, sink: ProgressSink) -> list[Stage] | None:
    """Analysis, plus embedding (and tagging) with the default model when it can be used."""
    from mcrar.ingest.stages import build_stages

    if not embed:
        return None
    if not state.torch_available():
        sink.warning(NO_EMBED_WARNING)
        return None
    return build_stages(state.settings, [state.pool.get(state.settings.default_embedder)])


@router.post("/api/ingest/jamendo", status_code=202)
def ingest_jamendo_route(body: JamendoIngestBody, state: StateDep) -> dict[str, Any]:
    from mcrar.ingest import JamendoQuery, ingest_jamendo

    def split(values: list[str] | None) -> list[str] | None:
        cleaned = [v.strip() for v in values or [] if v.strip()]
        return cleaned or None

    query = JamendoQuery(
        tags=split(body.tags),
        fuzzytags=split(body.fuzzytags),
        search=(body.search or "").strip() or None,
        vocalinstrumental=body.vocalinstrumental,
        commercial_only=body.commercial_only,
        order=body.order or None,
    )
    client = _open_jamendo(state)

    def run(sink: ProgressSink) -> IngestReport:
        try:
            return ingest_jamendo(
                client,
                state.repo,
                query=query,
                limit=body.limit,
                force=body.force,
                stages=_ingest_stages(state, body.embed, sink),
                on_progress=sink.on_event,
            )
        finally:
            client.close()

    return _start(
        state, "ingest-jamendo", body.model_dump(exclude_none=True), run, cleanup=client.close
    )


@router.post("/api/search/import", status_code=202)
def search_import_route(body: SearchImportBody, state: StateDep) -> dict[str, Any]:
    """Import new Jamendo tracks for a text search, so that CLAP can rank them next time."""
    from mcrar.ingest import ingest_jamendo_queries
    from mcrar.ingest.stages import TAGGING_EMBEDDER, build_stages
    from mcrar.recommend.jamendo_query import jamendo_queries

    filters = resolve_filters(body.filters, state.search.vocab)
    parsed = state.search.parse(SearchRequest(text=body.text, filters=filters))
    if not parsed.semantic_text:
        raise ValueError(IMPORT_NEEDS_TEXT_MESSAGE)
    if not state.torch_available():  # new tracks cannot be ranked without embeddings
        raise HTTPException(status_code=503, detail=NO_TORCH_MESSAGE)
    queries = jamendo_queries(parsed.semantic_text, parsed.filters, parsed.search_terms)
    client = _open_jamendo(state)

    def run(sink: ProgressSink) -> IngestReport:
        try:
            # The tagging heads read CLAP vectors, so CLAP is embedded whatever the default is.
            keys = dict.fromkeys([state.settings.default_embedder, TAGGING_EMBEDDER])
            stages = build_stages(state.settings, [state.pool.get(key) for key in keys])
            return ingest_jamendo_queries(
                client,
                state.repo,
                queries=queries,
                max_new=body.limit,
                stages=stages,
                on_progress=sink.on_event,
            )
        finally:
            client.close()

    # ``text`` is the request as sent (the page matches it against the search on screen),
    # ``query`` what the parser made of it.
    params = {"text": body.text.strip(), "limit": body.limit, "query": parsed.semantic_text}
    return _start(state, "ingest-query", params, run, cleanup=client.close)


@router.post("/api/ingest/local", status_code=202)
def ingest_local_route(body: LocalIngestBody, state: StateDep) -> dict[str, Any]:
    from mcrar.ingest import ingest_local
    from mcrar.sources.local_folder import scan_local

    folder = Path(body.path)
    if not folder.is_absolute():
        raise ValueError("path must be an absolute folder path")
    folder = folder.resolve()
    if not folder.is_dir():
        raise ValueError(f"folder not found: {folder}")
    scan_local(folder, license_override=body.license)  # validates the licence now (ValueError)

    def run(sink: ProgressSink) -> IngestReport:
        return ingest_local(
            folder,
            state.repo,
            license_override=body.license,
            force=body.force,
            stages=_ingest_stages(state, body.embed, sink),
            on_progress=sink.on_event,
        )

    params = {**body.model_dump(exclude_none=True), "path": str(folder)}
    return _start(state, "ingest-local", params, run)


@router.post("/api/ingest/reprocess", status_code=202)
def reprocess_route(body: ReprocessBody, state: StateDep) -> dict[str, Any]:
    params = body.model_dump(exclude_none=True)
    if body.what == "tag":
        return _start(state, "reprocess-tag", params, _reprocess_tags(state, body))
    if not state.torch_available():
        raise HTTPException(status_code=503, detail=NO_TORCH_MESSAGE)
    client = None
    if body.source != "local" and state.repo.stats()["tracks_by_source"].get("jamendo", 0) > 0:
        client = _open_jamendo(state)  # Jamendo audio URLs expire: they are refreshed first
    return _start(
        state,
        "reprocess-embed",
        params,
        _reprocess_embeddings(state, body, client),
        cleanup=client.close if client is not None else None,
    )


def _reprocess_tags(state: AppState, body: ReprocessBody) -> Callable[[ProgressSink], IngestReport]:
    def run(sink: ProgressSink) -> IngestReport:
        from mcrar.ingest import IngestReport as Report
        from mcrar.ingest import reprocess_catalog
        from mcrar.ingest.stages import tagging_stages_for

        stages = tagging_stages_for(state.settings)
        if not stages:
            sink.warning(NO_TAGGING_WARNING)
            return Report(0, 0, 0, 0, 0, 0, [], 0.0)
        return reprocess_catalog(
            state.repo,
            stages=stages,
            source=body.source,
            force=body.force,
            on_progress=sink.on_event,
        )

    return run


def _reprocess_embeddings(
    state: AppState, body: ReprocessBody, client: Any
) -> Callable[[ProgressSink], IngestReport]:
    def run(sink: ProgressSink) -> IngestReport:
        from mcrar.ingest import EmbeddingStage, reprocess_catalog

        try:
            embedder = state.pool.get(state.settings.default_embedder)
            return reprocess_catalog(
                state.repo,
                stages=[EmbeddingStage(embedder)],
                client=client,
                source=body.source,
                force=body.force,
                on_progress=sink.on_event,
            )
        finally:
            if client is not None:
                client.close()

    return run


# -- watching jobs -------------------------------------------------------------------------------


@router.get("/api/jobs")
def list_jobs(state: StateDep) -> dict[str, Any]:
    return {"jobs": [job.to_dict() for job in state.jobs.list()]}


@router.get("/api/jobs/{job_id}")
def get_job(job_id: str, state: StateDep) -> dict[str, Any]:
    return {"job": state.jobs.get(job_id).to_dict(detail=True)}


@router.post("/api/jobs/{job_id}/cancel", status_code=202)
def cancel_job(job_id: str, state: StateDep) -> dict[str, Any]:
    try:
        job = state.jobs.cancel(job_id)
    except JobNotRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"job": job.to_dict()}


def format_event(event: dict[str, Any]) -> str:
    return f"id: {event['seq']}\nevent: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"


async def stream_events(job: Job, after: int) -> AsyncIterator[str]:
    """The SSE text of the job's events after ``after``, until its final event."""
    last, idle = after, 0.0
    while True:
        events, ended = await anyio.to_thread.run_sync(
            job.wait_for_events, last, POLL_S, abandon_on_cancel=True
        )
        for event in events:
            yield format_event(event)
            last = event["seq"]
        if events:
            idle = 0.0
            if events[-1]["type"] in FINAL_EVENTS:
                return
        elif ended:
            return  # the client already has everything
        else:
            idle += POLL_S
            if idle >= KEEPALIVE_S:
                idle = 0.0
                yield ": keepalive\n\n"


@router.get("/api/jobs/{job_id}/events")
async def job_events(
    job_id: str,
    state: StateDep,
    after: Annotated[int | None, Query(ge=0)] = None,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    job = state.jobs.get(job_id)
    if after is None:
        after = int(last_event_id) if last_event_id and last_event_id.strip().isdigit() else 0
    return StreamingResponse(
        stream_events(job, after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
