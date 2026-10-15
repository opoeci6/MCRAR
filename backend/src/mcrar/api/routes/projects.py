"""Projects and their shortlists: CRUD, notes and the project credits download.

A project is a named shortlist of catalog tracks (a game, a level). All state lives in the
catalog through ``CatalogRepository``. A duplicate or empty project name is a 422 (the
repository's ``ValueError``); an unknown project or track is a 404. Adding a track that is
already on the shortlist only replaces its note, so ``PUT`` is safe to repeat.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from mcrar.api.routes._files import credits_download, safe_stem
from mcrar.api.routes.tracks import track_summary
from mcrar.api.state import AppState, StateDep
from mcrar.catalog import Project, ShortlistEntry
from mcrar.licensing import project_credits

router = APIRouter()

ProjectName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class ProjectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ProjectName


class ItemBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Annotated[str | None, Field(max_length=2000)] = None


def _project(state: AppState, project_id: int) -> Project:
    project = state.repo.get_project(project_id)
    if project is None:
        raise LookupError(f"no project with id {project_id}")
    return project


def _project_json(project: Project, item_count: int) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "created_at": project.created_at,
        "item_count": item_count,
    }


def _entry_json(entry: ShortlistEntry) -> dict[str, Any]:
    return {
        "track": track_summary(entry.track),
        "note": entry.note,
        "added_at": entry.added_at,
    }


def _count(state: AppState, project_id: int) -> int:
    return state.repo.shortlist_counts().get(project_id, 0)


@router.get("/api/projects")
def list_projects(state: StateDep) -> list[dict[str, Any]]:
    counts = state.repo.shortlist_counts()
    return [_project_json(p, counts.get(p.id, 0)) for p in state.repo.list_projects()]


@router.post("/api/projects", status_code=201)
def create_project(body: ProjectBody, state: StateDep) -> dict[str, Any]:
    project_id = state.repo.create_project(body.name)
    return _project_json(_project(state, project_id), 0)


@router.get("/api/projects/{project_id}")
def project_detail(project_id: int, state: StateDep) -> dict[str, Any]:
    project = _project(state, project_id)
    entries = state.repo.shortlist_entries(project_id)
    return {**_project_json(project, len(entries)), "items": [_entry_json(e) for e in entries]}


@router.patch("/api/projects/{project_id}")
def rename_project(project_id: int, body: ProjectBody, state: StateDep) -> dict[str, Any]:
    state.repo.rename_project(project_id, body.name)
    return _project_json(_project(state, project_id), _count(state, project_id))


@router.delete("/api/projects/{project_id}", status_code=204)
def delete_project(project_id: int, state: StateDep) -> Response:
    if not state.repo.delete_project(project_id):
        raise LookupError(f"no project with id {project_id}")
    return Response(status_code=204)


# -- shortlist items -------------------------------------------------------------------------


@router.get("/api/projects/{project_id}/items")
def list_items(project_id: int, state: StateDep) -> list[dict[str, Any]]:
    return [_entry_json(e) for e in state.repo.shortlist_entries(project_id)]


@router.put("/api/projects/{project_id}/items/{track_id}")
def put_item(
    project_id: int, track_id: int, state: StateDep, body: ItemBody | None = None
) -> dict[str, Any]:
    """Add the track, or replace its note (an absent note clears it)."""
    state.repo.add_to_shortlist(project_id, track_id, body.note if body else None)
    entry = next(e for e in state.repo.shortlist_entries(project_id) if e.track.id == track_id)
    return _entry_json(entry)


@router.delete("/api/projects/{project_id}/items/{track_id}", status_code=204)
def delete_item(project_id: int, track_id: int, state: StateDep) -> Response:
    _project(state, project_id)
    if not state.repo.remove_from_shortlist(project_id, track_id):
        raise LookupError(f"track {track_id} is not in project {project_id}")
    return Response(status_code=204)


# -- credits ---------------------------------------------------------------------------------


@router.get("/api/projects/{project_id}/credits")
def credits(
    project_id: int,
    state: StateDep,
    fmt: Annotated[Literal["txt", "md", "json"], Query(alias="format")] = "txt",
) -> Response:
    project = _project(state, project_id)
    tracks = [e.track for e in state.repo.shortlist_entries(project_id)]
    stem = safe_stem(project.name, "project")
    return credits_download(
        project_credits(project.name, tracks, fmt), fmt, stem=stem, suffix="credits"
    )
