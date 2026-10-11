from fastapi.testclient import TestClient

from mcrar import __version__
from mcrar.api.app import app


def test_health() -> None:
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}
