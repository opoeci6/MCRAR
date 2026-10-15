"""Application factory, health check and the static frontend."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from api_support import make_client

from mcrar import __version__
from mcrar.api import app as app_module


def test_health_reports_catalog_and_loaded_models(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        body = client.get("/api/health").json()
        assert body == {
            "status": "ok",
            "version": __version__,
            "catalog": {"tracks": 21},
            "models_loaded": [],
        }
        client.post("/api/search", json={"text": "tense stealth level"})
        assert client.get("/api/health").json()["models_loaded"] == ["clap"]


def test_there_is_no_import_time_app() -> None:
    assert not hasattr(app_module, "app")


def test_importing_the_app_module_does_not_load_ml_libraries() -> None:
    code = """
import sys
import mcrar.api.app

heavy = {"librosa", "scipy", "torch", "transformers", "sklearn"}
loaded = sorted({name.split(".")[0] for name in sys.modules} & heavy)
assert not loaded, loaded
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False, timeout=60
    )
    assert result.returncode == 0, result.stderr


def test_unknown_api_paths_are_json_404(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/api/nope")
        assert response.status_code == 404
        assert response.json() == {"detail": "Not Found"}


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    folder = tmp_path / "home" / "frontend" / "dist"
    (folder / "assets").mkdir(parents=True)
    (folder / "index.html").write_text("<html>app</html>", encoding="utf-8")
    (folder / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")
    return folder


def test_built_frontend_is_served_with_spa_fallback(tmp_path: Path, dist: Path) -> None:
    with make_client(tmp_path) as client:
        assert client.get("/").text == "<html>app</html>"
        assert client.get("/assets/app.js").text == "console.log(1)"
        assert client.get("/projects/3").text == "<html>app</html>"  # a client-side route
        assert client.get("/api/health").json()["status"] == "ok"
        missing = client.get("/api/nope")
        assert missing.status_code == 404 and missing.json() == {"detail": "Not Found"}
        escape = client.get("/..%2F..%2Fsecret.txt")
        assert escape.status_code == 200 and escape.text == "<html>app</html>"


def test_no_frontend_routes_without_a_build(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert client.get("/").status_code == 404


def test_warm_loads_the_default_embedder_in_the_background(tmp_path: Path) -> None:
    with make_client(tmp_path, warm=True) as client:
        client.app.state.mcrar.pool.get("clap")  # waits for the warm-up load if it is running
        assert client.loader.keys == ["clap"]
        assert client.get("/api/health").json()["models_loaded"] == ["clap"]


def test_reload_settings_rebuilds_the_search_service_only_when_search_inputs_change(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        state = client.app.state.mcrar
        client.post("/api/search", json={"text": "tense stealth level"})
        before, stored_before = state.search, state.stored_tags
        same_mode = client.settings.model_copy(update={"api_port": 9999})
        state.reload_settings(same_mode)
        assert state.search is before and state.settings is same_mode

        search = client.settings.search.model_copy(update={"max_per_artist": 1})
        state.reload_settings(client.settings.model_copy(update={"search": search}))
        assert state.search is not before and state.stored_tags is not stored_before
        assert not before.embedder_loaded  # the old service let go of the model...
        assert client.embedder.closed is False  # ...which the pool still owns
        assert client.post("/api/search", json={"text": "epic battle"}).status_code == 200
        assert client.loader.keys == ["clap"]  # no second load

        rebuilt = state.search
        search = search.model_copy(update={"pool_size": 50})
        state.reload_settings(client.settings.model_copy(update={"search": search}))
        assert state.search is not rebuilt  # new ranking settings need a new service
        assert state.search._settings.search.pool_size == 50

        rebuilt = state.search
        state.reload_settings(
            client.settings.model_copy(update={"search": search, "default_embedder": "glap"})
        )
        assert state.search is not rebuilt  # another default embedder needs a new service
