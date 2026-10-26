"""The FastAPI application, built by :func:`create_app` (run with ``uvicorn --factory``).

There is no import-time ``app``: importing this module builds nothing and loads no model. The
lifespan opens the catalog and the model pool when the server starts and closes them when it
stops (:class:`~mcrar.api.state.AppState`). All routers are registered here, including the empty
ones that later milestones fill, so adding an endpoint never touches this file. When the built
frontend exists at ``<home>/frontend/dist`` it is served at ``/`` with a fallback to
``index.html`` for client-side routes; unknown ``/api/...`` paths stay JSON 404s.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response

from mcrar import __version__
from mcrar.api.routes import (
    analyze,
    ingest,
    labels,
    meta,
    projects,
    ratings,
    reference,
    search,
    tracks,
)
from mcrar.api.routes import llm as llm_routes
from mcrar.api.routes import settings as settings_routes
from mcrar.api.security import install_security
from mcrar.api.state import ApiDeps, AppState
from mcrar.config import Settings, get_settings

WARM_ENV_VAR = "MCRAR_API_WARM"  # set by `mcrar serve --warm`, which cannot pass arguments here


def frontend_dist(settings: Settings) -> Path:
    return settings.home / "frontend" / "dist"


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built frontend: real files as they are, any other non-API path as index.html."""
    root = dist.resolve()
    index = root / "index.html"

    def page(path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)

    app.add_api_route("/{path:path}", page, methods=["GET", "HEAD"], include_in_schema=False)


def create_app(
    settings: Settings | None = None,
    *,
    deps: ApiDeps | None = None,
    warm: bool | None = None,
) -> FastAPI:
    """Build the app. ``warm`` loads the default embedder in the background at startup
    (default: the ``MCRAR_API_WARM`` environment variable)."""
    settings = settings or get_settings()
    deps = deps or ApiDeps()
    if warm is None:
        warm = os.environ.get(WARM_ENV_VAR) == "1"

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        state = AppState(settings, deps)
        app.state.mcrar = state
        if warm:
            state.warm()
        try:
            yield
        finally:
            state.close()

    app = FastAPI(title="MCRAR", version=__version__, lifespan=lifespan)
    install_security(app, settings, deps.extra_hosts)
    for module in (
        meta,
        search,
        llm_routes,
        ratings,
        labels,
        tracks,
        projects,
        settings_routes,
        ingest,
        analyze,
        reference,
    ):
        app.include_router(module.router)
    if (frontend_dist(settings) / "index.html").is_file():
        _mount_frontend(app, frontend_dist(settings))
    return app
