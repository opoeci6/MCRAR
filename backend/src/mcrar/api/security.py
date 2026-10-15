"""Local-only protections and the error mapping of the HTTP API.

The server is meant for the person at the keyboard, bound to loopback. Two middlewares keep a web
page in the user's browser from using it:

- ``TrustedHostMiddleware`` accepts only loopback names and the configured ``api_host`` in the
  ``Host`` header (DNS rebinding makes a hostile name resolve to 127.0.0.1). A wildcard bind
  address such as ``0.0.0.0`` (``mcrar serve --allow-remote``) accepts any host.
- :class:`LoopbackOriginMiddleware` refuses a state-changing request whose ``Origin`` is not a
  loopback page (the Vite dev server on another port is fine). Reads are not restricted.

There is deliberately no CORS middleware: browsers then block cross-origin reads, and the
frontend reaches the API through the Vite proxy or the same origin.

The exception handlers turn input problems into 422, unknown ids into 404 and unusable models
into 503, with a short message and never a traceback or a secret.
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from mcrar.api.models import ModelUnavailableError
from mcrar.config import Settings
from mcrar.ml import ModelError

log = logging.getLogger(__name__)

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]", "::1")
WILDCARD_HOSTS = ("0.0.0.0", "::", "[::]", "")
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CROSS_ORIGIN_REFUSED = {"detail": "cross-origin request refused"}


def allowed_hosts(settings: Settings, extra: tuple[str, ...] = ()) -> list[str]:
    """The ``Host`` header names the app answers to (without port)."""
    api_host = settings.api_host.strip().lower()
    if api_host in WILDCARD_HOSTS:
        return ["*"]
    hosts = [*LOOPBACK_HOSTS, *extra]
    hosts.append(f"[{api_host}]" if ":" in api_host and not api_host.startswith("[") else api_host)
    return list(dict.fromkeys(hosts))


def is_loopback_origin(origin: str) -> bool:
    """``http(s)://`` plus a loopback host on any port."""
    try:
        parts = urlsplit(origin)
        host = parts.hostname
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and host in ("127.0.0.1", "localhost", "::1")


class LoopbackOriginMiddleware:
    """Answer 403 to a non-read request that carries a non-loopback ``Origin`` header."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"].upper() not in SAFE_METHODS:
            origin = next((v for k, v in scope["headers"] if k == b"origin"), None)
            if origin is not None and not is_loopback_origin(origin.decode("latin-1")):
                response = JSONResponse(CROSS_ORIGIN_REFUSED, status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def install_security(app: FastAPI, settings: Settings, extra_hosts: tuple[str, ...] = ()) -> None:
    """Add the middlewares (the host check runs first) and the exception handlers."""
    app.add_middleware(LoopbackOriginMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts(settings, extra_hosts))

    def detail(status: int, message: str) -> JSONResponse:
        return JSONResponse({"detail": message}, status_code=status)

    @app.exception_handler(ValueError)  # includes SearchError
    async def _invalid(request: Request, exc: ValueError) -> JSONResponse:
        return detail(422, str(exc) or "invalid request")

    @app.exception_handler(LookupError)
    async def _not_found(request: Request, exc: LookupError) -> JSONResponse:
        return detail(404, str(exc.args[0]) if exc.args else "not found")

    @app.exception_handler(ModelUnavailableError)
    async def _model_unavailable(request: Request, exc: ModelUnavailableError) -> JSONResponse:
        return detail(503, str(exc))

    @app.exception_handler(ModelError)
    async def _model_error(request: Request, exc: ModelError) -> JSONResponse:
        return detail(503, str(exc))

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path)
        return detail(500, "internal error")
