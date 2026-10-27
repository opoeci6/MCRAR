"""POST /api/search, GET /api/vocab and /api/stats."""

from __future__ import annotations

from pathlib import Path

import pytest
from api_support import ApiClient, make_client, register_tagging


def test_text_search_returns_ranked_items_with_a_breakdown(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post("/api/search", json={"text": "tense stealth level", "limit": 5})
        assert response.status_code == 200
        body = response.json()
        titles = [item["title"] for item in body["items"]]
        assert titles[:3] == ["Shadow Walk", "Quiet Vents", "Night Heist"]
        assert len(titles) == 5 and body["total_candidates"] >= 5
        first = body["items"][0]
        assert first["breakdown"]["semantic"]["raw"] == pytest.approx(1.0)
        assert first["explanation"]
        scores = [item["score"] for item in body["items"]]
        assert scores == sorted(scores, reverse=True)


def test_the_embedder_is_loaded_once_across_requests(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        for text in ("tense stealth level", "epic battle", "tense stealth level"):
            assert client.post("/api/search", json={"text": text}).status_code == 200
        assert client.loader.keys == ["clap"]
        assert client.embedder.calls  # the fake did the embedding
        assert client.get("/api/health").json()["models_loaded"] == ["clap"]
    assert client.embedder.closed  # shutting the app down unloads the models


def test_structured_filters_apply(tmp_path: Path) -> None:
    body = {
        "text": "epic battle",
        "filters": {
            "max_risk": "green",
            "vocal": "instrumental",
            "bpm_min": 100,
            "bpm_max": 120,
            "duration_min_s": 200,
            "sources": ["jamendo"],
        },
        "limit": 50,
    }
    with make_client(tmp_path) as client:
        items = client.post("/api/search", json=body).json()["items"]
        assert items and all(i["risk"] == "green" and i["source"] == "jamendo" for i in items)
        assert all(i["duration_s"] >= 200 for i in items)
        assert "Epic Quest" in [i["title"] for i in items]


def test_download_url_only_when_the_track_allows_it(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        items = client.post("/api/search", json={"text": "epic battle", "limit": 50}).json()[
            "items"
        ]
        by_title = {i["title"]: i for i in items}
        assert by_title["Epic Quest"]["download_url"] == "https://example.test/10/download"
        assert by_title["Boss Fight"]["download_url"] is None


def test_items_include_the_tempo_confidence(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        items = client.post("/api/search", json={"text": "epic battle", "limit": 50}).json()[
            "items"
        ]
        by_title = {i["title"]: i for i in items}
        assert by_title["Boss Fight"]["bpm"] == 150.0
        assert by_title["Boss Fight"]["bpm_confidence"] == 0.9


def test_filter_only_search_works_without_torch(tmp_path: Path) -> None:
    body = {"filters": {"max_risk": "green", "vocal": "instrumental"}, "limit": 50}
    with make_client(tmp_path, torch=False) as client:
        response = client.post("/api/search", json=body)
        assert response.status_code == 200 and response.json()["items"]
        assert client.loader.keys == []


TORCH_MISSING = {"detail": "text search needs the ml extra (torch is not installed)"}


def client_with_genre_model(tmp_path: Path) -> tuple[ApiClient, str]:
    """A no-torch client whose registry allows one genre model (labels a, b, c); returns the
    client (not entered yet) and that model's version."""
    client = make_client(tmp_path, torch=False)
    registry = register_tagging(client.settings, commercial=True)
    return client, registry["label_sets"]["genre"]["entries"][0]["id"]


def tag_genres(client: ApiClient, version: str, *, skip: tuple[str, ...] = ()) -> None:
    for n, (title, track_id) in enumerate(client.ids.items()):
        if title not in skip:
            probs = {"a": 0.1 + 0.04 * n, "b": 0.5, "c": 0.2}
            client.repo.set_tag_probs(track_id, "genre", "head", version, probs)


def test_filter_only_genre_search_works_without_torch_when_tracks_are_tagged(
    tmp_path: Path,
) -> None:
    client, version = client_with_genre_model(tmp_path)
    tag_genres(client, version, skip=("Unembedded Tune",))  # it has no embedding: no zero-shot
    with client:
        response = client.post("/api/search", json={"filters": {"genres": ["a"]}, "limit": 50})
        assert response.status_code == 200
        items = response.json()["items"]
        assert items and client.loader.keys == []
        raw = {item["title"]: item["breakdown"]["tags"]["raw"] for item in items}
        assert raw.pop("Unembedded Tune") == 0.0  # untagged and not embedded: nothing to score by
        scores = list(raw.values())  # in ranking order: standardised, so in (0, 1)
        assert scores == sorted(scores, reverse=True) and 0.0 < scores[-1] < scores[0] < 1.0


def test_filter_only_genre_search_needs_torch_for_an_untagged_embedded_track(
    tmp_path: Path,
) -> None:
    client, version = client_with_genre_model(tmp_path)
    tag_genres(client, version, skip=("Shadow Walk",))
    with client:
        response = client.post("/api/search", json={"filters": {"genres": ["a"]}})
        assert response.status_code == 503 and response.json() == TORCH_MISSING
        assert client.loader.keys == []


def test_filter_only_genre_search_ignores_tags_of_a_model_that_is_not_allowed(
    tmp_path: Path,
) -> None:
    client, _ = client_with_genre_model(tmp_path)
    tag_genres(client, "genre-logreg@0000000")  # an older version than the registry's
    with client:
        response = client.post("/api/search", json={"filters": {"genres": ["a"]}})
        assert response.status_code == 503 and response.json() == TORCH_MISSING


def test_text_search_without_torch_is_503(tmp_path: Path) -> None:
    with make_client(tmp_path, torch=False) as client:
        response = client.post("/api/search", json={"text": "tense stealth level"})
        assert response.status_code == 503
        assert response.json() == {
            "detail": "text search needs the ml extra (torch is not installed)"
        }
        assert client.loader.keys == []


def test_a_model_that_cannot_load_is_503_not_a_traceback(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        client.app.state.mcrar.pool._factory = lambda key, settings: 1 / 0
        response = client.post("/api/search", json={"text": "tense stealth level"})
        assert response.status_code == 503
        assert response.json() == {"detail": "could not load model 'clap' (ZeroDivisionError)"}


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"filters": {"genres": ["polka"]}}, "unknown genre label 'polka'; choose from: blues"),
        ({"filters": {"moods": ["jazz"]}}, "unknown moodtheme label 'jazz'"),
        ({"filters": {"sources": ["spotify"]}}, "sources must be one of: jamendo, local"),
        ({"filters": {"bpm_min": 120, "bpm_max": 80}}, "bpm_min must not exceed bpm_max"),
        (
            {"filters": {"duration_min_s": 90, "duration_max_s": 30}},
            "duration_min_s must not exceed duration_max_s",
        ),
        ({}, "give a search text or at least one filter"),
        ({"text": "   "}, "give a search text or at least one filter"),
    ],
)
def test_bad_requests_are_422_with_the_message(tmp_path: Path, body: dict, message: str) -> None:
    with make_client(tmp_path) as client:
        response = client.post("/api/search", json=body)
        assert response.status_code == 422
        assert message in response.json()["detail"]


@pytest.mark.parametrize(
    "body",
    [
        {"text": "x", "limit": 0},
        {"text": "x", "limit": 101},
        {"text": "x", "offset": -1},
        {"text": "x", "filters": {"max_risk": "purple"}},
        {"text": "x", "filters": {"bpm_min": -5}},
        {"text": "x", "unexpected": 1},
    ],
)
def test_invalid_fields_are_422(tmp_path: Path, body: dict) -> None:
    with make_client(tmp_path) as client:
        assert client.post("/api/search", json=body).status_code == 422


def test_paging(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        everything = client.post("/api/search", json={"text": "tense stealth level", "limit": 100})
        page = client.post(
            "/api/search", json={"text": "tense stealth level", "limit": 3, "offset": 2}
        )
        expected = [i["track_id"] for i in everything.json()["items"][2:5]]
        assert [i["track_id"] for i in page.json()["items"]] == expected


def test_vocab_lists_labels_with_display_names_and_synonyms(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        body = client.get("/api/vocab").json()
        genres = {g["id"]: g for g in body["genre"]}
        assert genres["hip-hop"]["display"] == "Hip-Hop"
        assert "rap" in genres["hip-hop"]["synonyms"]
        moods = {m["id"]: m for m in body["moodtheme"]}
        assert "spooky" in moods["dark"]["synonyms"] and moods["calm"]["synonyms"] == []


def test_stats(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        body = client.get("/api/stats").json()
        assert body["tracks"] == 21 and body["tracks_by_source"] == {"jamendo": 19, "local": 2}
