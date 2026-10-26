"""Game scenes over HTTP (M9): the scene vocabulary, the scenes and intensity filters, the
ratings keys and the stored scene tags of a track."""

from __future__ import annotations

from pathlib import Path

import pytest
from api_support import make_client, register_tagging
from tagging_support import fixture_tagger


def test_vocab_lists_the_scene_labels_with_display_names_and_synonyms(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        body = client.get("/api/vocab").json()
        scenes = {s["id"]: s for s in body["scene"]}
        assert len(scenes) == 14 and list(body)[:3] == ["genre", "moodtheme", "scene"]
        assert scenes["boss"]["display"] == "Boss fight"
        assert scenes["defeat"]["display"] == "Defeat / game over"
        assert "battle" in scenes["combat"]["synonyms"]
        assert "game over" in scenes["defeat"]["synonyms"]
        assert "creepy" in scenes["horror"]["synonyms"]


def test_scene_and_intensity_filters_are_resolved_and_echoed(tmp_path: Path) -> None:
    body = {"filters": {"scenes": ["Boss fight", "sneaking"], "intensity": "high"}, "limit": 50}
    with make_client(tmp_path) as client:
        response = client.post("/api/search", json=body)
        assert response.status_code == 200
        parsed = response.json()["parsed"]
        assert parsed["filters"]["scenes"] == ["boss", "stealth"]
        assert parsed["filters"]["intensity"] == "high"
        assert parsed["preferences"]["energy_target"] == pytest.approx(0.8)
        energies = [i["energy"] for i in response.json()["items"] if i["energy"] is not None]
        assert energies[0] > energies[-1]  # the loud tracks come first


def test_the_intensity_beats_an_energy_word_in_the_text(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        words = client.post("/api/search", json={"text": "calm dark", "limit": 3}).json()
        assert words["parsed"]["preferences"]["energy_target"] == pytest.approx(0.3)
        body = {"text": "calm dark", "filters": {"intensity": "high"}, "limit": 3}
        asked = client.post("/api/search", json=body).json()
        assert asked["parsed"]["preferences"]["energy_target"] == pytest.approx(0.8)


def test_text_hints_for_scenes_show_in_the_parsed_query(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        body = client.post("/api/search", json={"text": "boss fight", "limit": 3}).json()
        assert body["parsed"]["preferences"]["scene_hints"] == ["boss", "combat"]
        assert "scene: boss, combat" in body["parsed"]["notes"]


@pytest.mark.parametrize(
    ("filters", "message"),
    [
        ({"scenes": ["karaoke"]}, "unknown scene label 'karaoke'; choose from: combat"),
        ({"genres": ["boss"]}, "unknown genre label 'boss'"),  # a scene, not a genre
    ],
)
def test_unknown_scenes_are_422_with_the_message(
    tmp_path: Path, filters: dict, message: str
) -> None:
    with make_client(tmp_path) as client:
        response = client.post("/api/search", json={"filters": filters})
        assert response.status_code == 422 and message in response.json()["detail"]


@pytest.mark.parametrize(
    "filters", [{"intensity": "extreme"}, {"intensity": 3}, {"scenes": "boss"}, {"scene": ["boss"]}]
)
def test_invalid_scene_fields_are_422(tmp_path: Path, filters: dict) -> None:
    with make_client(tmp_path) as client:
        assert client.post("/api/search", json={"filters": filters}).status_code == 422


def test_ratings_of_a_filter_only_scene_query_are_keyed_by_the_resolved_labels(
    tmp_path: Path,
) -> None:
    query = {"filters": {"scenes": ["Boss fight"], "intensity": "low"}}
    with make_client(tmp_path) as client:
        response = client.put(
            "/api/ratings", json={**query, "track_id": client.ids["Lullaby"], "rating": 2}
        )
        assert response.status_code == 200
        assert response.json()["query_key"] == 'filters:{"intensity":"low","scenes":["boss"]}'
        items = client.post("/api/search", json={**query, "limit": 50}).json()["items"]
        assert {i["title"]: i["rating"] for i in items}["Lullaby"] == 2
        listed = client.get("/api/ratings").json()["items"]
        assert listed[0]["filters"] == {"intensity": "low", "scenes": ["boss"]}


def test_a_track_detail_shows_the_tags_of_the_selected_scene_entry(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    scene = register_tagging(client.settings, fixture_tagger("scene", "zeroshot"), variant="zs")
    version = scene["label_sets"]["scene"]["entries"][0]["id"]
    with client:
        track = client.ids["Shadow Walk"]
        client.repo.set_tag_probs(track, "scene", "zeroshot", version, {"a": 0.7, "b": 0.2})
        other = client.ids["Quiet Vents"]
        client.repo.set_tag_probs(other, "scene", "zeroshot", "scene-zs@0000000", {"c": 0.9})
        assert client.get(f"/api/tracks/{other}").json()["tags"] == []  # another version
        tags = client.get(f"/api/tracks/{track}").json()["tags"]
        assert [(t["label_set"], t["label"], t["prob"]) for t in tags] == [
            ("scene", "a", 0.7),
            ("scene", "b", 0.2),
        ]
