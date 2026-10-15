"""GET/PUT /api/settings: the editable subset, the file, the live reload and the refusals."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from api_support import make_client

from mcrar.config import settings_file

EVIL = {"Origin": "https://evil.test"}


def disk(home: Path) -> dict:
    return tomllib.loads(settings_file(home).read_text(encoding="utf-8"))


def test_get_returns_editable_read_only_env_and_embedders(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        body = client.get("/api/settings").json()
        settings = client.app.state.mcrar.settings
    assert set(body) == {"editable", "read_only", "overridden_by_env", "embedders"}
    assert set(body["editable"]) == {"default_embedder", "search"}
    assert body["editable"]["default_embedder"] == "clap"
    assert set(body["editable"]["search"]) == {
        "pool_size",
        "max_per_artist",
        "min_results",
        "weak_cosine",
        "weights",
    }
    assert set(body["editable"]["search"]["weights"]) == {"semantic", "tags", "bpm", "energy"}
    assert body["read_only"] == {
        "home": str(settings.home),
        "data_dir": str(settings.data_dir),
        "models_dir": str(settings.models_dir),
        "cache_dir": str(settings.cache_dir),
        "secrets_dir": str(settings.secrets_dir),
        "secrets_backend": "file",
        "api_host": "127.0.0.1",
        "api_port": 8000,
    }
    assert body["overridden_by_env"] == []
    by_key = {e["key"]: e for e in body["embedders"]}
    assert set(by_key) == {"clap", "glap", "muq-mulan"}
    assert by_key["clap"]["commercial_ok"] is True
    assert by_key["muq-mulan"]["commercial_ok"] is False
    assert all(set(e) == {"key", "model_id", "commercial_ok"} for e in body["embedders"])
    assert by_key["muq-mulan"]["model_id"].startswith("muq-mulan@")


def test_put_writes_the_file_and_reloads_the_running_state(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        state = client.app.state.mcrar
        old_search = state.search
        response = client.put("/api/settings", json={"default_embedder": "glap"})
        assert response.status_code == 200
        assert response.json()["editable"]["default_embedder"] == "glap"
        assert state.settings.default_embedder == "glap"
        assert state.search is not old_search  # the search service was rebuilt
        assert disk(state.settings.home) == {"default_embedder": "glap"}
        assert client.get("/api/settings").json() == response.json()


def test_put_nested_search_settings_are_merged(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        client.put("/api/settings", json={"search": {"pool_size": 77}})
        response = client.put(
            "/api/settings", json={"search": {"weights": {"tags": 0.9}, "min_results": 0}}
        )
        assert response.status_code == 200
        state = client.app.state.mcrar
        assert state.settings.search.pool_size == 77
        assert state.settings.search.min_results == 0
        assert state.settings.search.weights.tags == 0.9
        assert state.settings.search.weights.semantic == 0.6
        assert disk(state.settings.home) == {
            "search": {"pool_size": 77, "min_results": 0, "weights": {"tags": 0.9}}
        }


def test_put_keeps_the_paths_of_the_running_server(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        before = client.get("/api/settings").json()["read_only"]
        client.put("/api/settings", json={"search": {"pool_size": 10}})
        assert client.get("/api/settings").json()["read_only"] == before


def test_an_empty_put_changes_nothing(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert client.put("/api/settings", json={}).status_code == 200
        assert not settings_file(client.app.state.mcrar.settings.home).exists()


def test_a_non_commercial_embedder_can_be_selected_without_any_other_setting(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        response = client.put("/api/settings", json={"default_embedder": "muq-mulan"})
        assert response.status_code == 200
        assert client.app.state.mcrar.settings.default_embedder == "muq-mulan"
        assert disk(client.app.state.mcrar.settings.home) == {"default_embedder": "muq-mulan"}


def test_an_unknown_embedder_is_refused(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.put("/api/settings", json={"default_embedder": "nope"})
        assert response.status_code == 422
        assert "nope" in response.json()["detail"]


def test_a_field_pinned_by_the_environment_is_a_409_naming_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCRAR_SEARCH__POOL_SIZE", "42")
    with make_client(tmp_path) as client:
        state = client.app.state.mcrar
        assert client.get("/api/settings").json()["overridden_by_env"] == ["search.pool_size"]
        response = client.put("/api/settings", json={"search": {"pool_size": 5}})
        assert response.status_code == 409
        assert "search.pool_size" in response.json()["detail"]
        assert not settings_file(state.settings.home).exists()
        # other fields stay editable, and the env value still wins in the reloaded settings
        assert client.put("/api/settings", json={"search": {"min_results": 3}}).status_code == 200
        assert state.settings.search.pool_size == 42
        assert state.settings.search.min_results == 3


@pytest.mark.parametrize(
    "body",
    [
        {"api_port": 1},
        {"home": "/x"},
        {"search": {"unknown": 1}},
        {"search": {"weights": {"nope": 1}}},
        {"commercial_mode": False},  # the removed setting is no longer accepted
        {"search": {"pool_size": 0}},
        {"search": {"weak_cosine": 1.5}},
        {"search": {"weak_cosine": -0.1}},
        {"search": {"pool_size": "many"}},
        {"search": {"weights": {"tags": -1}}},
        {"search": {"weights": {"semantic": 0, "tags": 0, "bpm": 0, "energy": 0}}},
        {"default_embedder": ""},
    ],
)
def test_invalid_bodies_are_422_and_change_nothing(tmp_path: Path, body: dict) -> None:
    with make_client(tmp_path) as client:
        state = client.app.state.mcrar
        before = state.settings
        assert client.put("/api/settings", json=body).status_code == 422
        assert state.settings is before
        assert not settings_file(before.home).exists()


def test_cross_origin_writes_are_refused_on_every_new_route(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        put = client.put("/api/settings", json={"default_embedder": "glap"}, headers=EVIL)
        assert put.status_code == 403
        assert client.app.state.mcrar.settings.default_embedder == "clap"
        assert client.post("/api/analyze", headers=EVIL).status_code == 403
        assert client.put("/api/secrets/x", json={"value": "v"}, headers=EVIL).status_code == 403
        assert client.delete("/api/secrets/x", headers=EVIL).status_code == 403


def test_the_weak_match_threshold_is_editable_and_unset_by_default(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        state = client.app.state.mcrar
        assert client.get("/api/settings").json()["editable"]["search"]["weak_cosine"] is None
        response = client.put("/api/settings", json={"search": {"weak_cosine": 0.5}})
        assert response.status_code == 200
        assert response.json()["editable"]["search"]["weak_cosine"] == 0.5
        assert state.settings.search.weak_cosine == 0.5
        assert disk(state.settings.home) == {"search": {"weak_cosine": 0.5}}
