"""/api/secrets: names and sources only, never values, in any response."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest
from api_support import ApiClient, make_client

from mcrar.llm.presets import PRESET_IDS

SECRET = "s3cr3t-VALUE-0123456789"


def stored(client: ApiClient) -> dict:
    path = client.app.state.mcrar.settings.secrets_dir / "secrets.toml"
    return tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def test_list_is_empty_with_the_known_names(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        body = client.get("/api/secrets").json()
    assert body["backend"] == "file"
    assert body["items"] == []
    assert [k["name"] for k in body["known"]] == [
        "jamendo_client_id",
        "freesound_api_key",
        *(f"llm_api_key_{p}" for p in PRESET_IDS),
    ]
    assert all(k["description"] for k in body["known"])
    by_name = {k["name"]: k["description"] for k in body["known"]}
    assert by_name["llm_api_key_deepseek"] == "API key for DeepSeek (LLM)"


def test_set_list_delete_round_trip_never_returns_the_value(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        put = client.put("/api/secrets/jamendo_client_id", json={"value": f"  {SECRET}  "})
        assert put.status_code == 204
        assert put.content == b""
        assert stored(client) == {"jamendo_client_id": SECRET}  # stripped
        listing = client.get("/api/secrets")
        assert listing.json()["items"] == [{"name": "jamendo_client_id", "source": "file"}]
        assert SECRET not in listing.text
        assert client.delete("/api/secrets/jamendo_client_id").status_code == 204
        assert client.get("/api/secrets").json()["items"] == []
        assert stored(client) == {}


def test_env_secrets_are_listed_with_source_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCRAR_SECRET_JAMENDO_CLIENT_ID", SECRET)
    with make_client(tmp_path) as client:
        response = client.get("/api/secrets")
        assert response.json()["items"] == [{"name": "jamendo_client_id", "source": "env"}]
        assert SECRET not in response.text


def test_delete_of_a_missing_secret_is_404(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.delete("/api/secrets/jamendo_client_id")
        assert response.status_code == 404
        assert "jamendo_client_id" in response.json()["detail"]


@pytest.mark.parametrize("name", ["Bad-Name", "UPPER", "a.b", "x y"])
def test_an_invalid_name_is_422(tmp_path: Path, name: str) -> None:
    with make_client(tmp_path) as client:
        assert client.put(f"/api/secrets/{name}", json={"value": SECRET}).status_code == 422
        assert client.delete(f"/api/secrets/{name}").status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"value": ""},
        {"value": "   "},
        {"value": SECRET * 200},
        {"value": 12345},
        {"value": SECRET, "extra": SECRET},
        {"other": SECRET},
        [SECRET],
        SECRET,
    ],
)
def test_invalid_bodies_are_422_without_echoing_the_input(tmp_path: Path, payload: Any) -> None:
    with make_client(tmp_path) as client:
        response = client.put("/api/secrets/jamendo_client_id", json=payload)
        assert response.status_code == 422
        assert SECRET not in response.text
        assert "input" not in response.text
        assert stored(client) == {}


def test_a_body_that_is_not_json_is_422_without_echo(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.put(
            "/api/secrets/jamendo_client_id",
            content=f"{{{SECRET}".encode(),
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 422
        assert SECRET not in response.text


def test_an_oversized_body_is_413(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.put("/api/secrets/jamendo_client_id", json={"value": "x" * 100_000})
        assert response.status_code == 413


def test_the_env_backend_is_read_only(tmp_path: Path) -> None:
    with make_client(tmp_path, settings_overrides={"secrets_backend": "env"}) as client:
        put = client.put("/api/secrets/jamendo_client_id", json={"value": SECRET})
        assert put.status_code == 409
        assert "read-only" in put.json()["detail"]
        assert SECRET not in put.text
        assert client.delete("/api/secrets/jamendo_client_id").status_code == 409
        assert client.get("/api/secrets").json()["backend"] == "env"


def test_secret_values_are_not_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("DEBUG"), make_client(tmp_path) as client:
        client.put("/api/secrets/jamendo_client_id", json={"value": SECRET})
        client.put("/api/secrets/jamendo_client_id", json={"value": ""})
    assert SECRET not in caplog.text
