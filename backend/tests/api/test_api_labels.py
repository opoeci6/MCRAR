"""The labelling endpoints (M9): next track, pool list, progress, label CRUD, the export."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from api_support import ApiClient, make_client

from mcrar.catalog import PoolEntry

PARTS = ["A", "B", "both", "A", "B"]


def add_pool(client: ApiClient) -> list[str]:
    """The first five catalog tracks as the pool, parts A B both A B; returns their titles."""
    titles = list(client.ids)[:5]
    client.repo.replace_label_pool(
        [
            PoolEntry(client.ids[title], n, "top:boss:zeroshot-catalog", part)
            for n, (title, part) in enumerate(zip(titles, PARTS, strict=True), start=1)
        ]
    )
    return titles


def put(client: ApiClient, title: str, **body: object):
    payload = {"labeller": "Ana", "scenes": [], "intensity": None, "status": "labelled", **body}
    return client.put(f"/api/labels/{client.ids[title]}", json=payload)


def test_the_pool_routes_answer_409_until_there_is_a_pool(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        for path in ("next", "pool", "progress"):
            response = client.get(f"/api/labels/{path}", params={"labeller": "Ana"})
            assert response.status_code == 409, path
            assert response.json() == {"detail": "No labelling pool yet: run mcrar scenes pool"}
        # labels themselves do not need a pool
        assert put(client, list(client.ids)[0], scenes=["boss"]).status_code == 200


def test_next_gives_the_first_unlabelled_track_of_the_part_with_what_the_player_needs(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        titles = add_pool(client)
        body = client.get("/api/labels/next", params={"labeller": "Ana"}).json()
        track = body["track"]
        assert (body["position"], body["part"], body["label"]) == (1, "A", None)
        assert track["id"] == client.ids[titles[0]] and track["title"] == titles[0]
        assert set(track) >= {
            "id", "title", "artist", "duration_s", "source", "risk", "license_code",
            "license_url", "commercial_license_url", "attribution", "stream_url",
        }  # fmt: skip
        assert track["stream_url"] == f"/api/tracks/{track['id']}/stream"
        assert "reason" not in body and "top:" not in json.dumps(
            body
        )  # nothing primes the labeller

        b = client.get("/api/labels/next", params={"labeller": "Ana", "part": "B"}).json()
        assert (b["position"], b["part"]) == (2, "B")
        assert (
            client.get("/api/labels/next", params={"labeller": "Ana", "after": 2}).json()[
                "position"
            ]
            == 3
        )
        a_after = client.get(
            "/api/labels/next", params={"labeller": "Ana", "part": "A", "after": 1}
        )
        assert (a_after.json()["position"], a_after.json()["part"]) == (3, "both")

        put(client, titles[0], scenes=["combat"])
        put(client, titles[2], status="skipped")
        assert client.get("/api/labels/next", params={"labeller": "Ana"}).json()["position"] == 2
        a = client.get("/api/labels/next", params={"labeller": "Ana", "part": "A"}).json()
        assert a["position"] == 4  # 1 labelled, 3 skipped
        assert client.get("/api/labels/next", params={"labeller": "Ben"}).json()["position"] == 1


def test_next_is_null_when_the_part_is_done(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        titles = add_pool(client)
        for title in titles:
            put(client, title, scenes=[])
        assert client.get("/api/labels/next", params={"labeller": "Ana"}).json() == {"track": None}
        assert client.get("/api/labels/next", params={"labeller": "Ana", "after": 5}).json() == {
            "track": None
        }


@pytest.mark.parametrize(
    "params",
    [
        {"labeller": ""},
        {"labeller": "x" * 41},
        {"labeller": "a\x07b"},
        {"labeller": "Ana", "part": "C"},
        {"labeller": "Ana", "after": -1},
        {"labeller": "Ana", "after": "x"},
        {},
    ],
)
def test_bad_query_parameters_are_422(tmp_path: Path, params: dict) -> None:
    with make_client(tmp_path) as client:
        add_pool(client)
        assert client.get("/api/labels/next", params=params).status_code == 422


def test_the_pool_list_shows_the_labellers_status_per_track(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        titles = add_pool(client)
        put(client, titles[0], scenes=["combat"])
        put(client, titles[1], status="skipped")
        put(client, titles[1], labeller="Ben", scenes=["menu"])
        listing = client.get("/api/labels/pool", params={"labeller": "Ana"}).json()
        assert listing["total"] == 5
        assert [(i["position"], i["part"], i["status"]) for i in listing["items"]] == [
            (1, "A", "labelled"),
            (2, "B", "skipped"),
            (3, "both", None),
            (4, "A", None),
            (5, "B", None),
        ]
        assert listing["items"][0] == {
            "position": 1,
            "part": "A",
            "track_id": client.ids[titles[0]],
            "title": titles[0],
            "artist": listing["items"][0]["artist"],
            "status": "labelled",
        }
        only_b = client.get("/api/labels/pool", params={"labeller": "Ana", "part": "B"}).json()
        assert [i["part"] for i in only_b["items"]] == ["B", "both", "B"]
        ben = client.get("/api/labels/pool", params={"labeller": "Ben"}).json()
        assert [i["status"] for i in ben["items"]][:2] == [None, "labelled"]


def test_progress_counts_per_part_and_lists_the_labellers(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        titles = add_pool(client)
        put(client, titles[0], scenes=["combat"])  # part A
        put(client, titles[2], status="skipped")  # part both
        put(client, titles[1], labeller="Ben", scenes=[])
        body = client.get("/api/labels/progress", params={"labeller": "Ana"}).json()
        assert body == {
            "pool_size": 5,
            "parts": {
                "A": {"total": 2, "labelled": 1, "skipped": 0},
                "B": {"total": 2, "labelled": 0, "skipped": 0},
                "both": {"total": 1, "labelled": 0, "skipped": 1},
            },
            "labelled": 1,
            "skipped": 1,
            "labellers": ["Ana", "Ben"],
        }
        new = client.get("/api/labels/progress", params={"labeller": "Zed"}).json()
        assert new["labelled"] == 0 and new["pool_size"] == 5


def test_put_get_and_delete_a_label(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        title = list(client.ids)[0]
        track = client.ids[title]
        missing = client.get(f"/api/labels/{track}", params={"labeller": "Ana"})
        assert missing.status_code == 404

        stored = put(client, title, labeller=" Ana ", scenes=["boss", "combat"], intensity="high")
        assert stored.status_code == 200
        label = stored.json()
        assert (label["track_id"], label["labeller"]) == (track, "Ana")
        assert (label["scenes"], label["intensity"], label["status"]) == (
            ["boss", "combat"],
            "high",
            "labelled",
        )
        assert label["created_at"] and label["updated_at"]
        assert client.get(f"/api/labels/{track}", params={"labeller": "Ana"}).json() == label

        again = put(client, title, scenes=[], intensity=None).json()  # "no scene fits"
        assert again["scenes"] == [] and again["status"] == "labelled"
        assert again["created_at"] == label["created_at"]
        skipped = put(client, title, scenes=["boss"], intensity="low", status="skipped").json()
        assert (skipped["status"], skipped["scenes"], skipped["intensity"]) == ("skipped", [], None)

        assert client.delete(f"/api/labels/{track}", params={"labeller": "Ana"}).status_code == 204
        assert client.delete(f"/api/labels/{track}", params={"labeller": "Ana"}).status_code == 404
        assert client.get(f"/api/labels/{track}", params={"labeller": "Ana"}).status_code == 404


def test_putting_a_bad_label_is_422_and_an_unknown_track_404(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        title = list(client.ids)[0]
        unknown = put(client, title, scenes=["boss", "karaoke"])
        assert unknown.status_code == 422
        assert "karaoke" in unknown.json()["detail"] and "choose from" in unknown.json()["detail"]
        for body in (
            {"intensity": "loud"},
            {"status": "done"},
            {"labeller": ""},
            {"labeller": "x" * 41},
            {"labeller": "tab\there"},
            {"scenes": "boss"},
            {"unexpected": 1},
        ):
            assert put(client, title, **body).status_code == 422, body
        no_status = client.put(f"/api/labels/{client.ids[title]}", json={"labeller": "Ana"})
        assert no_status.status_code == 422
        gone = client.put("/api/labels/99999", json={"labeller": "Ana", "status": "skipped"})
        assert gone.status_code == 404 and "99999" in gone.json()["detail"]
        assert client.get("/api/labels/progress", params={"labeller": "Ana"}).status_code == 409
        assert client.repo.iter_scene_labels() == []


def test_the_export_is_a_download_of_the_labels_file(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        titles = add_pool(client)
        put(client, titles[0], scenes=["combat"], intensity="mid")
        put(client, titles[1], labeller="Ben Jones", scenes=[], status="labelled")
        everyone = client.get("/api/labels/export")
        assert everyone.status_code == 200
        assert everyone.headers["content-type"].startswith("application/json")
        assert everyone.headers["content-disposition"] == (
            'attachment; filename="scene-labels-all.json"'
        )
        body = everyone.json()
        assert (body["schema"], body["kind"]) == (1, "mcrar-scene-labels")
        assert [(r["labeller"], r["scenes"]) for r in body["labels"]] == [
            ("Ana", ["combat"]),
            ("Ben Jones", []),
        ]
        ana = client.get("/api/labels/export", params={"labeller": "Ana"})
        assert ana.headers["content-disposition"] == 'attachment; filename="scene-labels-Ana.json"'
        assert [r["labeller"] for r in ana.json()["labels"]] == ["Ana"]
        # names are reduced to header-safe characters in the file name only
        ben = client.get("/api/labels/export", params={"labeller": "Ben Jones"})
        assert 'filename="scene-labels-Ben-Jones.json"' in ben.headers["content-disposition"]
        assert [r["labeller"] for r in ben.json()["labels"]] == ["Ben Jones"]
        assert client.get("/api/labels/export", params={"labeller": ""}).status_code == 422


def test_a_cross_origin_page_cannot_write_labels(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        title = list(client.ids)[0]
        body = {"labeller": "Ana", "scenes": [], "intensity": None, "status": "labelled"}
        url = f"/api/labels/{client.ids[title]}"
        assert (
            client.put(url, json=body, headers={"Origin": "https://evil.test"}).status_code == 403
        )
        assert client.repo.iter_scene_labels() == []
        assert (
            client.put(url, json=body, headers={"Origin": "http://localhost:5173"}).status_code
            == 200
        )
