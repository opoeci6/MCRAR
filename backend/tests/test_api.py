from fastapi.testclient import TestClient

from mcrar import __version__
from mcrar.api.app import create_app


def test_health_with_default_dependencies() -> None:
    # No fakes: the app opens the catalog under MCRAR_HOME and is reached as a loopback client.
    with TestClient(create_app(), base_url="http://127.0.0.1") as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": __version__,
        "catalog": {"tracks": 0},
        "models_loaded": [],
    }
