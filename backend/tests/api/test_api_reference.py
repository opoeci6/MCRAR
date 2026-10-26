"""POST /api/reference (an uploaded song embedded and kept in memory) and searching by reference."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from api_support import ApiClient, make_client
from recommend_support import MODEL_ID, QUERY_TEXTS, ToneEmbedder, axis, tone_wav_bytes

from mcrar.api.references import REFERENCE_STORE_MAX, ReferenceStore, StoredReference
from mcrar.api.routes import reference as reference_routes


def client_for(tmp_path: Path, **kwargs: object) -> ApiClient:
    return make_client(tmp_path, embedder=ToneEmbedder(QUERY_TEXTS), **kwargs)  # type: ignore[arg-type]


def upload(client: ApiClient, name: str = "song.wav", data: bytes | None = None):
    data = tone_wav_bytes("stealth") if data is None else data
    return client.post("/api/reference", files={"file": (name, data, "application/octet-stream")})


def titles(response) -> list[str]:  # noqa: ANN001
    return [item["title"] for item in response.json()["items"]]


# -- the upload -----------------------------------------------------------------------------------


def test_an_upload_is_embedded_with_the_default_model(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        response = upload(client, "C:\\music\\my song.wav")
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"upload_id", "filename", "duration_s", "model_id"}
        assert body["filename"] == "my song.wav"  # the base name only
        assert body["duration_s"] == pytest.approx(3.0, abs=0.05)
        assert body["model_id"] == MODEL_ID
        assert len(body["upload_id"]) >= 12
        assert client.loader.keys == ["clap"]
        stored = client.app.state.mcrar.references.get(body["upload_id"])
        assert stored is not None and stored.model_id == MODEL_ID
        assert int(np.argmax(stored.vector)) == 0  # the stealth tone, as the fake hears it


def test_each_upload_gets_its_own_id(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        ids = {upload(client).json()["upload_id"] for _ in range(3)}
    assert len(ids) == 3


@pytest.mark.parametrize("name", ["notes.txt", "song", "song.exe", ""])
def test_a_wrong_extension_is_422(tmp_path: Path, name: str) -> None:
    with client_for(tmp_path) as client:
        assert upload(client, name).status_code == 422
        assert len(client.app.state.mcrar.references) == 0


def test_undecodable_audio_is_422(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        response = upload(client, "song.wav", b"this is not audio at all")
        assert response.status_code == 422 and response.json()["detail"]


def test_an_oversized_upload_is_413(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = tone_wav_bytes("stealth", seconds=1.0)
    monkeypatch.setattr(reference_routes, "MAX_UPLOAD_BYTES", len(data) - 1)
    with client_for(tmp_path) as client:
        assert upload(client, data=data).status_code == 413
        monkeypatch.setattr(reference_routes, "MAX_UPLOAD_BYTES", len(data))
        assert upload(client, data=data).status_code == 200


def test_a_missing_file_part_is_422(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        assert client.post("/api/reference", data={"x": "y"}).status_code == 422


def test_without_torch_an_upload_is_503(tmp_path: Path) -> None:
    with client_for(tmp_path, torch=False) as client:
        response = upload(client)
        assert response.status_code == 503 and "torch" in response.json()["detail"]


def test_the_store_keeps_the_last_32_uploads(tmp_path: Path) -> None:
    assert REFERENCE_STORE_MAX == 32
    with client_for(tmp_path) as client:
        first = upload(client, data=tone_wav_bytes("calm", seconds=1.0)).json()["upload_id"]
        for _ in range(REFERENCE_STORE_MAX - 1):
            upload(client, data=tone_wav_bytes("jazz", seconds=1.0))
        assert len(client.app.state.mcrar.references) == 32
        kept = client.post("/api/search", json={"reference": {"upload_id": first}})
        assert kept.status_code == 200  # and the search made it the most recently used
        upload(client, data=tone_wav_bytes("jazz", seconds=1.0))
        assert (
            client.post("/api/search", json={"reference": {"upload_id": first}}).status_code == 200
        )
        for _ in range(REFERENCE_STORE_MAX):
            upload(client, data=tone_wav_bytes("jazz", seconds=1.0))
        gone = client.post("/api/search", json={"reference": {"upload_id": first}})
        assert gone.status_code == 404


def test_the_store_evicts_the_least_recently_used() -> None:
    store = ReferenceStore(max_entries=2)

    def entry(name: str) -> StoredReference:
        return StoredReference(axis("calm"), MODEL_ID, name, 1.0)

    a, b = store.put(entry("a")), store.put(entry("b"))
    assert store.get(a) is not None  # a is now newer than b
    c = store.put(entry("c"))
    assert store.get(b) is None and store.get(a) is not None and store.get(c) is not None
    store.clear()
    assert len(store) == 0 and store.get(a) is None


# -- searching with a reference -------------------------------------------------------------------


def test_a_search_by_upload_ranks_by_the_uploaded_song(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        upload_id = upload(client, "song.wav").json()["upload_id"]
        response = client.post("/api/search", json={"reference": {"upload_id": upload_id}})
        assert response.status_code == 200
        body = response.json()
        assert titles(response)[:3] == ["Shadow Walk", "Quiet Vents", "Night Heist"]
        assert body["reference"] == {
            "kind": "upload",
            "track_id": None,
            "label": "song.wav",
            "weight": 0.5,
        }
        first = body["items"][0]
        assert first["breakdown"]["reference"] == {"raw": 1.0, "weight": 1.0, "contribution": 1.0}
        assert first["explanation"].startswith("Sounds close to “song.wav”")
        assert body["match"] == {"top_cosine": None, "weak": False}
        assert "vector" not in str(body)
        assert client.embedder.calls == []  # no text, so no text embedding


def test_a_search_by_track_leaves_the_track_out_and_needs_no_torch(tmp_path: Path) -> None:
    with client_for(tmp_path, torch=False) as client:
        track_id = client.ids["Shadow Walk"]
        response = client.post("/api/search", json={"reference": {"track_id": track_id}})
        assert response.status_code == 200
        body = response.json()
        assert titles(response)[:2] == ["Quiet Vents", "Night Heist"]
        assert "Shadow Walk" not in titles(response)
        assert body["reference"] == {
            "kind": "track",
            "track_id": track_id,
            "label": "Shadow Walk — Ada",
            "weight": 0.5,
        }


def test_a_reference_can_be_blended_with_text_and_filters(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        upload_id = upload(client).json()["upload_id"]
        body = {
            "text": "epic battle",
            "reference": {"upload_id": upload_id},
            "filters": {"max_risk": "green"},
            "limit": 50,
        }
        text_side = client.post("/api/search", json={**body, "reference_weight": 0.0})
        ref_side = client.post("/api/search", json={**body, "reference_weight": 1.0})
        assert titles(text_side)[0] != "Shadow Walk" and titles(ref_side)[0] == "Shadow Walk"
        for response in (text_side, ref_side):
            assert {i["risk"] for i in response.json()["items"]} == {"green"}
        assert ref_side.json()["reference"]["weight"] == 1.0
        item = client.post("/api/search", json=body).json()["items"][0]
        assert (
            item["breakdown"]["semantic"]["weight"] > 0 < item["breakdown"]["reference"]["weight"]
        )


def test_a_search_with_a_reference_has_no_ratings(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        track_id = client.ids["Epic Quest"]
        rated = client.put(
            "/api/ratings", json={"text": "epic battle", "track_id": track_id, "rating": 2}
        )
        assert rated.status_code == 200
        plain = client.post("/api/search", json={"text": "epic battle"}).json()["items"]
        assert 2 in {item["rating"] for item in plain}
        upload_id = upload(client).json()["upload_id"]
        mixed = client.post(
            "/api/search",
            json={"text": "epic battle", "reference": {"upload_id": upload_id}, "limit": 50},
        ).json()["items"]
        assert mixed and {item["rating"] for item in mixed} == {None}


def test_an_unknown_or_expired_upload_is_404(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        response = client.post("/api/search", json={"reference": {"upload_id": "nope"}})
        assert response.status_code == 404
        assert response.json()["detail"] == "This uploaded song has expired. Upload it again."


def test_an_upload_from_another_model_is_409(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        upload_id = upload(client).json()["upload_id"]
        assert client.put("/api/settings", json={"default_embedder": "glap"}).status_code == 200
        response = client.post("/api/search", json={"reference": {"upload_id": upload_id}})
        assert response.status_code == 409
        assert response.json()["detail"] == (
            "The embedding model changed since the upload. Upload it again."
        )


def test_an_unknown_track_is_404(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        response = client.post("/api/search", json={"reference": {"track_id": 99999}})
        assert response.status_code == 404


def test_a_track_without_an_embedding_is_422_with_the_way_out(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        body = {"reference": {"track_id": client.ids["Unembedded Tune"]}}
        response = client.post("/api/search", json=body)
        assert response.status_code == 422
        assert "Re-embed missing tracks" in response.json()["detail"]


@pytest.mark.parametrize(
    "body",
    [
        {"reference": {"track_id": 1, "upload_id": "abc"}},
        {"reference": {}},
        {"reference": {"track_id": 1, "path": "/etc/passwd"}},
        {"reference": {"track_id": 1}, "reference_weight": 1.5},
        {"reference": {"track_id": 1}, "reference_weight": -0.1},
        {"reference": {"upload_id": ""}},
        {"reference_weight": 0.5},  # nothing to search for
    ],
)
def test_a_malformed_reference_is_422(tmp_path: Path, body: dict) -> None:
    with client_for(tmp_path) as client:
        assert client.post("/api/search", json=body).status_code == 422


def test_rerank_refuses_a_reference(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        body = {"text": "epic battle", "reference": {"track_id": client.ids["Shadow Walk"]}}
        response = client.post("/api/search/rerank", json=body)
        assert response.status_code == 422
        assert response.json()["detail"] == "LLM rerank doesn't use a reference song yet."


def test_a_search_without_a_reference_is_unchanged(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        body = client.post("/api/search", json={"text": "tense stealth level"}).json()
        assert body["reference"] is None
        assert body["items"][0]["breakdown"]["reference"]["weight"] == 0.0
