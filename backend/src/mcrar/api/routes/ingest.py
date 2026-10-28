"""Ingest jobs: start an ingest or a re-run of embedding/tagging, watch it, cancel it.

Design
- ``POST /api/ingest/...`` validates the request, then starts one background job
  (:class:`~mcrar.api.jobs.JobManager`, one at a time, else 409) and answers 202 with the job.
  Everything that can fail fast fails before the job starts: a body that does not validate (422),
  a bad Freesound tag (422), a missing Jamendo client id or Freesound API key (503), no torch for
  a re-embed or a search import (503).
- ``POST /api/ingest/freesound`` adds music-like Freesound sounds (kind ``ingest-freesound``). A
  reprocess of the whole catalog without a Freesound key carries on: those tracks fail one by one.
- ``POST /api/search/import`` imports new Jamendo and/or Freesound tracks for a text search (kind
  ``ingest-query``): the text is parsed like a search, the queries come from
  :mod:`mcrar.recommend.jamendo_query` and :mod:`mcrar.recommend.freesound_query` and the run
  stops after ``limit`` new tracks in all (Jamendo first, then Freesound with what is left). It
  embeds with the default model and with CLAP. ``GET /api/search/import/sources`` lists the
  sources that have their secret set. A source that fails only adds a warning; the job fails when
  every source did.
- ``POST /api/ingest/links`` adds the tracks named by pasted Jamendo and Freesound links (kind
  ``ingest-links``, see :mod:`mcrar.sources.links`). No valid link is a 422, a needed key that is
  not set a 503.
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
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

import anyio.to_thread
from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from mcrar.api.jobs import FINAL_EVENTS, Job, JobBusyError, JobNotRunningError, ProgressSink
from mcrar.api.models import NO_TORCH_MESSAGE
from mcrar.api.routes.search import FiltersBody, resolve_filters
from mcrar.api.state import AppState, StateDep
from mcrar.recommend import SearchRequest
from mcrar.secrets import SecretError
from mcrar.sources import FreesoundError, JamendoError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from mcrar.ingest.pipeline import IngestReport, Stage

router = APIRouter()

POLL_S = 1.0  # longest wait for a new event before the stream checks on its client again
KEEPALIVE_S = 15.0
NO_JAMENDO_MESSAGE = "Jamendo client id is not set"
NO_FREESOUND_MESSAGE = (
    "Freesound API key is not set: add it in Settings, or `mcrar secrets set freesound_api_key`"
)
NO_IMPORT_SOURCE_MESSAGE = (
    "Neither a Jamendo client id nor a Freesound API key is set: add one in Settings"
)
IMPORT_NEEDS_TEXT_MESSAGE = "describe the music to search for"
IMPORT_NO_REMOTE_SOURCE_MESSAGE = (
    "the Source filter has no Jamendo or Freesound: only those can be searched for more"
)
LINKS_NEED_LINK_MESSAGE = "no Jamendo or Freesound track link found"
REMOTE_SOURCES = ("jamendo", "freesound")
SOURCE_LABELS = {"jamendo": "Jamendo", "freesound": "Freesound"}
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


class FreesoundIngestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field("", max_length=200)
    tags: list[Annotated[str, Field(max_length=100)]] = Field(default_factory=list, max_length=10)
    licenses: list[Literal["cc0", "by", "by-nc", "sampling+"]] = Field(
        default_factory=lambda: ["cc0", "by"], min_length=1
    )
    duration_min_s: float = Field(10.0, ge=0)
    duration_max_s: float = Field(600.0, le=3600)
    sort: Literal[
        "score",
        "duration_desc",
        "duration_asc",
        "created_desc",
        "created_asc",
        "downloads_desc",
        "downloads_asc",
        "rating_desc",
        "rating_asc",
    ] = "score"
    limit: int = Field(50, ge=1, le=500)
    embed: bool = True
    force: bool = False

    @model_validator(mode="after")
    def _check(self) -> FreesoundIngestBody:
        if self.duration_max_s < self.duration_min_s:
            raise ValueError("duration_max_s must not be below duration_min_s")
        if not self.query.strip() and not any(t.strip() for t in self.tags):
            raise ValueError("give a query or at least one tag")
        return self


class SearchImportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=300)
    filters: FiltersBody = Field(default_factory=FiltersBody)
    limit: int = Field(50, ge=1, le=100)
    sources: list[Literal["jamendo", "freesound"]] | None = Field(None, min_length=1, max_length=2)


class LinksIngestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=10000)
    embed: bool = True
    force: bool = False


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
    source: Literal["jamendo", "freesound", "local"] | None = None


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


def _open_freesound(state: AppState) -> Any:
    try:
        return state.open_freesound()
    except (FreesoundError, SecretError):
        raise HTTPException(status_code=503, detail=NO_FREESOUND_MESSAGE) from None


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


@router.post("/api/ingest/freesound", status_code=202)
def ingest_freesound_route(body: FreesoundIngestBody, state: StateDep) -> dict[str, Any]:
    from mcrar.ingest import ingest_freesound
    from mcrar.sources.freesound import build_filter

    tags = [t.strip() for t in body.tags if t.strip()]
    # Bad tags (ValueError, so 422) fail here, before a client is opened or a job started.
    build_filter(
        tags=tags,
        licenses=body.licenses,
        duration_min_s=body.duration_min_s,
        duration_max_s=body.duration_max_s,
    )
    client = _open_freesound(state)

    def run(sink: ProgressSink) -> IngestReport:
        try:
            return ingest_freesound(
                client,
                state.repo,
                query=body.query,
                tags=tags,
                licenses=body.licenses,
                duration_min_s=body.duration_min_s,
                duration_max_s=body.duration_max_s,
                sort=body.sort,
                limit=body.limit,
                force=body.force,
                stages=_ingest_stages(state, body.embed, sink),
                on_progress=sink.on_event,
            )
        finally:
            client.close()

    return _start(state, "ingest-freesound", body.model_dump(), run, cleanup=client.close)


def _open_import_sources(
    state: AppState, wanted: list[str] | None, allowed: Sequence[str] | None = None
) -> dict[str, Any]:
    """The clients for a search import, in run order (Jamendo, then Freesound).

    ``wanted=None`` opens every source whose secret is set (503 when there is none); a list
    opens exactly those (503 with the first missing source's message). ``allowed`` (the search's
    Source filter, None for no restriction) limits the ``wanted=None`` case to those sources; when
    that leaves a single source, its own missing secret is the 503. Nothing stays open on a
    failure.
    """
    names = [n for n in REMOTE_SOURCES if allowed is None or n in allowed]
    strict = wanted is not None or len(names) == 1
    clients: dict[str, Any] = {}
    try:
        for name, opener in (("jamendo", _open_jamendo), ("freesound", _open_freesound)):
            if name not in (wanted if wanted is not None else names):
                continue
            try:
                clients[name] = opener(state)
            except HTTPException:
                if strict:
                    raise
        if not clients:
            raise HTTPException(status_code=503, detail=NO_IMPORT_SOURCE_MESSAGE)
    except HTTPException:
        _close_all(clients)
        raise
    return clients


def _close_all(clients: dict[str, Any]) -> None:
    for client in clients.values():
        client.close()


@router.get("/api/search/import/sources")
def search_import_sources(state: StateDep) -> dict[str, Any]:
    """The remote sources a search import can use now (those whose secret is set)."""
    usable: list[str] = []
    for name, opener in (("jamendo", _open_jamendo), ("freesound", _open_freesound)):
        try:
            opener(state).close()
        except HTTPException:
            continue
        usable.append(name)
    return {"sources": usable}


def _run_search_import(
    state: AppState,
    sink: ProgressSink,
    clients: dict[str, Any],
    jamendo_searches: list[Any],
    freesound_searches: list[Any],
    limit: int,
) -> IngestReport:
    """Run the import source by source (see :func:`search_import_route` for the budget rule)."""
    from mcrar.ingest import ingest_freesound_queries, ingest_jamendo_queries
    from mcrar.ingest.stages import TAGGING_EMBEDDER, build_stages

    # The tagging heads read CLAP vectors, so CLAP is embedded whatever the default is.
    keys = dict.fromkeys([state.settings.default_embedder, TAGGING_EMBEDDER])
    stages = build_stages(state.settings, [state.pool.get(key) for key in keys])

    def step(position: int, name: str, reports: list[IngestReport]) -> IngestReport | None:
        remaining = limit - sum(r.new for r in reports)
        budget = -(-remaining // (len(clients) - position))  # ceil: the last source gets it all
        if budget < 1:
            return None
        offset = sum(r.seen for r in reports)

        def relay(event: Any) -> None:
            # One progress bar over the whole job: indexes continue, the total is the limit.
            sink.on_event(replace(event, index=event.index + offset, total=limit))

        if name == "jamendo":
            return ingest_jamendo_queries(
                clients[name],
                state.repo,
                queries=jamendo_searches,
                max_new=budget,
                stages=stages,
                on_progress=relay,
            )
        return ingest_freesound_queries(
            clients[name],
            state.repo,
            freesound_searches,
            limit=budget,
            stages=stages,
            on_progress=relay,
        )

    return _run_sources(sink, list(clients), step)


def _run_sources(
    sink: ProgressSink,
    names: Sequence[str],
    step: Callable[[int, str, list[IngestReport]], IngestReport | None],
) -> IngestReport:
    """Run ``step(position, name, reports_so_far)`` for each source in turn, one combined report.

    A step returns None to stop (nothing left to do), a report that is ``aborted`` also stops the
    run. A Jamendo or Freesound error does not end the run: its partial report is kept, a warning
    says which source failed and the next source goes on; only when every source failed is the
    last error raised (with the combined partial report attached). Any other error (a cancel, an
    embedder out of memory, ...) ends the run at once with the combined partial report.
    """
    from mcrar.ingest import combine_reports

    reports: list[IngestReport] = []
    failure: Exception | None = None
    finished = 0
    for position, name in enumerate(names):
        try:
            report = step(position, name, reports)
        except (JamendoError, FreesoundError) as exc:
            partial = getattr(exc, "report", None)
            if partial is not None:  # its tracks count; its abort is this warning, not the job's
                reports.append(replace(partial, aborted=None))
            sink.warning(f"{SOURCE_LABELS[name]} failed: {exc}")
            failure = exc
            continue
        except Exception as exc:
            partial = getattr(exc, "report", None)
            if partial is not None:  # what the earlier sources added counts too
                exc.report = combine_reports([*reports, partial])  # type: ignore[attr-defined]
            raise
        if report is None:
            break
        reports.append(report)
        finished += 1
        if report.aborted:  # interrupted: do not start the next source
            break
    if failure is not None and not finished:
        if reports:
            failure.report = combine_reports(reports)  # type: ignore[attr-defined]
        raise failure
    return combine_reports(reports)


@router.post("/api/search/import", status_code=202)
def search_import_route(body: SearchImportBody, state: StateDep) -> dict[str, Any]:
    """Import new tracks from Jamendo and/or Freesound for a text search, so that CLAP can rank
    them next time.

    ``sources`` omitted means every source whose secret is set; a list means exactly those (a
    missing secret is a 503). When the search has a Source filter, only the remote sources in it
    are used (a filter without one, or a ``sources`` entry outside it, is a 422). The sources run
    one after the other, Jamendo first, in one job; one that fails (a rejected key, a rate limit)
    only adds a warning, and the job fails only when every source did. The budget is ``limit`` new
    tracks in all: every source but the last may take up to its equal share (rounded up), and the
    last takes what is left, so a source that finds fewer new tracks than its share leaves the
    rest to the next one (never more than ``limit`` in total).
    """
    from mcrar.recommend.freesound_query import freesound_queries
    from mcrar.recommend.jamendo_query import jamendo_queries

    filters = resolve_filters(body.filters, state.search.vocab)
    parsed = state.search.parse(SearchRequest(text=body.text, filters=filters))
    if not parsed.semantic_text:
        raise ValueError(IMPORT_NEEDS_TEXT_MESSAGE)
    allowed = parsed.filters.sources  # the search's Source filter; None means every source
    if allowed is not None:
        if not any(name in allowed for name in REMOTE_SOURCES):
            raise ValueError(IMPORT_NO_REMOTE_SOURCE_MESSAGE)
        outside = [name for name in body.sources or () if name not in allowed]
        if outside:
            raise ValueError(
                f"{', '.join(outside)} is not in the search's Source filter ({', '.join(allowed)})"
            )
    if not state.torch_available():  # new tracks cannot be ranked without embeddings
        raise HTTPException(status_code=503, detail=NO_TORCH_MESSAGE)
    clients = _open_import_sources(state, body.sources, allowed)
    queries = {
        "jamendo": jamendo_queries(parsed.semantic_text, parsed.filters, parsed.search_terms),
        "freesound": freesound_queries(parsed.semantic_text, parsed.filters, parsed.search_terms),
    }

    def run(sink: ProgressSink) -> IngestReport:
        try:
            return _run_search_import(
                state, sink, clients, queries["jamendo"], queries["freesound"], body.limit
            )
        finally:
            _close_all(clients)

    # ``text`` is the request as sent (the page matches it against the search on screen),
    # ``query`` what the parser made of it, ``sources`` the sources used (never a secret).
    params = {
        "text": body.text.strip(),
        "limit": body.limit,
        "query": parsed.semantic_text,
        "sources": list(clients),
    }
    return _start(state, "ingest-query", params, run, cleanup=lambda: _close_all(clients))


@router.post("/api/ingest/links", status_code=202)
def ingest_links_route(body: LinksIngestBody, state: StateDep) -> dict[str, Any]:
    """Add the Jamendo and Freesound tracks named by the links in ``text`` (kind ``ingest-links``).

    Jamendo ids run first, then Freesound ids, in one job with one progress bar. The report is
    an ingest report plus ``already`` (in the catalog before the run, still refreshed),
    ``not_found`` (not in the catalog after the run) and ``invalid`` (not a track link).
    """
    from mcrar.ingest import LinksReport, ingest_freesound_ids, ingest_jamendo_ids
    from mcrar.sources.links import parse_track_links

    links = parse_track_links(body.text)  # more than MAX_LINKS ids is a ValueError (422)
    ids = {"jamendo": links.jamendo, "freesound": links.freesound}
    if not any(ids.values()):
        shown = [entry[:80] for entry in links.invalid[:3]]
        more = f" and {len(links.invalid) - 3} more" if len(links.invalid) > 3 else ""
        hint = f" (not recognised: {', '.join(shown)}{more})" if shown else ""
        raise ValueError(LINKS_NEED_LINK_MESSAGE + hint)
    clients: dict[str, Any] = {}
    try:
        if ids["jamendo"]:
            clients["jamendo"] = _open_jamendo(state)
        if ids["freesound"]:
            clients["freesound"] = _open_freesound(state)
    except HTTPException:
        _close_all(clients)
        raise

    wanted = [(source, track_id) for source, found in ids.items() for track_id in found]

    def in_catalog(known: bool) -> list[str]:
        return [
            f"{source}:{track_id}"
            for source, track_id in wanted
            if (state.repo.get_track_by_source(source, track_id) is not None) is known
        ]

    already = in_catalog(True)
    invalid = list(links.invalid)
    total = len(wanted)

    def run(sink: ProgressSink) -> IngestReport:
        try:
            stages = _ingest_stages(state, body.embed, sink)

            def step(position: int, name: str, reports: list[IngestReport]) -> IngestReport:
                offset = sum(r.seen for r in reports)

                def relay(event: Any) -> None:
                    # One progress bar over the whole job: indexes continue, the total is all ids.
                    sink.on_event(replace(event, index=event.index + offset, total=total))

                ingest = ingest_jamendo_ids if name == "jamendo" else ingest_freesound_ids
                return ingest(
                    clients[name],
                    state.repo,
                    ids[name],
                    force=body.force,
                    stages=stages,
                    on_progress=relay,
                )

            report = _run_sources(sink, list(clients), step)
        finally:
            _close_all(clients)
        return LinksReport(
            **vars(report), already=already, not_found=in_catalog(False), invalid=invalid
        )

    params = {"jamendo": len(ids["jamendo"]), "freesound": len(ids["freesound"])}
    return _start(state, "ingest-links", params, run, cleanup=lambda: _close_all(clients))


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
    counts = state.repo.stats()["tracks_by_source"]
    client = freesound = None
    if body.source in (None, "jamendo") and counts.get("jamendo", 0) > 0:
        client = _open_jamendo(state)  # Jamendo audio URLs expire: they are refreshed first
    if body.source in (None, "freesound") and counts.get("freesound", 0) > 0:
        try:
            freesound = _open_freesound(state)
        except HTTPException:
            # Without a key the Freesound tracks fail one by one (with the reason in the log);
            # the rest of a whole-catalog run goes on. Asked for by name, it is a 503.
            if body.source == "freesound":
                raise

    def cleanup() -> None:
        for opened in (client, freesound):
            if opened is not None:
                opened.close()

    return _start(
        state,
        "reprocess-embed",
        params,
        _reprocess_embeddings(state, body, client, freesound),
        cleanup=cleanup,
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
    state: AppState, body: ReprocessBody, client: Any, freesound: Any = None
) -> Callable[[ProgressSink], IngestReport]:
    def run(sink: ProgressSink) -> IngestReport:
        from mcrar.ingest import EmbeddingStage, reprocess_catalog

        try:
            embedder = state.pool.get(state.settings.default_embedder)
            return reprocess_catalog(
                state.repo,
                stages=[EmbeddingStage(embedder)],
                client=client,
                freesound_client=freesound,
                source=body.source,
                force=body.force,
                on_progress=sink.on_event,
            )
        finally:
            for opened in (client, freesound):
                if opened is not None:
                    opened.close()

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
