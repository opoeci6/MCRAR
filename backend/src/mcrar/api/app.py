"""FastAPI application. Only the health check exists until milestone M5."""

from fastapi import FastAPI

from mcrar import __version__

app = FastAPI(title="MCRAR", version=__version__)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
