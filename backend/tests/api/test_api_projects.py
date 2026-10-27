"""Project and shortlist routes, end to end over the synthetic catalog."""

from __future__ import annotations

import json
from pathlib import Path

from api_support import ApiClient, make_client

from mcrar.licensing import LICENSE_DISCLAIMER


def _new(client: ApiClient, name: str = "Stealth Game") -> int:
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


def test_create_list_and_detail(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert client.get("/api/projects").json() == []
        response = client.post("/api/projects", json={"name": "  Stealth Game  "})
        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "Stealth Game" and body["item_count"] == 0
        assert body["created_at"]
        pid = body["id"]
        client.put(f"/api/projects/{pid}/items/{client.ids['Shadow Walk']}")
        listed = client.get("/api/projects").json()
        assert listed == [{**body, "item_count": 1}]
        detail = client.get(f"/api/projects/{pid}").json()
        assert detail["item_count"] == 1 and detail["items"][0]["track"]["title"] == "Shadow Walk"


def test_create_rejects_bad_names_with_422(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        _new(client, "Dup")
        for payload in ({"name": "Dup"}, {"name": "   "}, {"name": ""}, {}, {"name": "x" * 121}):
            assert client.post("/api/projects", json=payload).status_code == 422, payload
        assert client.post("/api/projects", json={"name": "ok", "extra": 1}).status_code == 422
        assert len(client.get("/api/projects").json()) == 1


def test_rename(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        a, _ = _new(client, "A"), _new(client, "B")
        renamed = client.patch(f"/api/projects/{a}", json={"name": "A2"})
        assert renamed.status_code == 200 and renamed.json()["name"] == "A2"
        assert client.patch(f"/api/projects/{a}", json={"name": "B"}).status_code == 422
        assert client.patch(f"/api/projects/{a}", json={"name": " "}).status_code == 422
        assert client.patch("/api/projects/999", json={"name": "Z"}).status_code == 404


def test_delete_cascades_but_keeps_tracks(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        pid = _new(client)
        tid = client.ids["Shadow Walk"]
        client.put(f"/api/projects/{pid}/items/{tid}")
        assert client.delete(f"/api/projects/{pid}").status_code == 204
        assert client.get(f"/api/projects/{pid}").status_code == 404
        assert client.get(f"/api/projects/{pid}/items").status_code == 404
        assert client.delete(f"/api/projects/{pid}").status_code == 404
        assert client.get(f"/api/tracks/{tid}").status_code == 200


def test_items_put_update_list_delete(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        pid = _new(client)
        a, b = client.ids["Shadow Walk"], client.ids["Red Alert"]
        first = client.put(f"/api/projects/{pid}/items/{a}", json={"note": "intro"})
        assert first.status_code == 200
        entry = first.json()
        assert entry["note"] == "intro" and entry["added_at"]
        assert set(entry["track"]) == {
            "id",
            "title",
            "artist",
            "source",
            "duration_s",
            "risk",
            "license_code",
            "source_id",
            "source_url",
            "download_url",
            "license_url",
            "commercial_license_url",
            "attribution_text",
        }
        client.put(f"/api/projects/{pid}/items/{b}")  # no body: no note
        again = client.put(f"/api/projects/{pid}/items/{a}", json={"note": "intro v2"}).json()
        assert again["note"] == "intro v2" and again["added_at"] == entry["added_at"]
        items = client.get(f"/api/projects/{pid}/items").json()
        assert [(i["track"]["id"], i["note"]) for i in items] == [(a, "intro v2"), (b, None)]
        assert client.delete(f"/api/projects/{pid}/items/{a}").status_code == 204
        assert client.delete(f"/api/projects/{pid}/items/{a}").status_code == 404
        assert [i["track"]["id"] for i in client.get(f"/api/projects/{pid}/items").json()] == [b]


def test_entries_carry_the_links_and_credits_of_the_track(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        pid = _new(client)
        quest, boss = client.ids["Epic Quest"], client.ids["Boss Fight"]
        put = client.put(f"/api/projects/{pid}/items/{quest}").json()["track"]
        client.put(f"/api/projects/{pid}/items/{boss}")
        listed = client.get(f"/api/projects/{pid}/items").json()
        detail = client.get(f"/api/projects/{pid}").json()["items"]
        by_title = {i["track"]["title"]: i["track"] for i in listed}
        assert [i["track"] for i in detail] == [i["track"] for i in listed]
        assert by_title["Epic Quest"] == put
        # the same values as the track page, with the download link only when it is allowed
        for title, track_id in (("Epic Quest", quest), ("Boss Fight", boss)):
            page = client.get(f"/api/tracks/{track_id}").json()
            track = by_title[title]
            for field in (
                "source_id",
                "source_url",
                "download_url",
                "license_url",
                "commercial_license_url",
                "attribution_text",
            ):
                assert track[field] == page[field], field
        epic, fight = by_title["Epic Quest"], by_title["Boss Fight"]
        assert epic["download_url"] == "https://example.test/10/download"
        assert fight["download_url"] is None
        assert epic["source_url"] == "https://example.test/10" and epic["source_id"] == "10"
        assert epic["license_url"] == "https://creativecommons.org/licenses/by/3.0/"
        assert epic["attribution_text"] == "Epic Quest by Gus"
        assert fight["attribution_text"] == "Boss Fight by Gus"
        assert epic["commercial_license_url"] is None


def test_item_errors(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        pid = _new(client)
        tid = client.ids["Shadow Walk"]
        assert client.put(f"/api/projects/999/items/{tid}").status_code == 404
        assert client.put(f"/api/projects/{pid}/items/99999").status_code == 404
        assert client.delete(f"/api/projects/999/items/{tid}").status_code == 404
        assert client.get("/api/projects/999/items").status_code == 404
        url = f"/api/projects/{pid}/items/{tid}"
        assert client.put(url, json={"note": "x" * 2001}).status_code == 422
        assert client.put(url, json={"note": "x" * 2000}).status_code == 200
        assert client.put(url, json={"note": "n", "other": 1}).status_code == 422
        assert client.put("/api/projects/abc/items/1").status_code == 422


def test_credits_download(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        pid = _new(client, "Stealth: Game/One")
        for title in ("Shadow Walk", "Red Alert", "Mystery Box"):
            client.put(f"/api/projects/{pid}/items/{client.ids[title]}")
        expected = {
            "txt": "text/plain; charset=utf-8",
            "md": "text/markdown; charset=utf-8",
            "json": "application/json",
        }
        for fmt, media_type in expected.items():
            response = client.get(f"/api/projects/{pid}/credits", params={"format": fmt})
            assert response.status_code == 200
            assert response.headers["content-type"] == media_type
            assert response.headers["content-disposition"] == (
                f'attachment; filename="Stealth-Game-One-credits.{fmt}"'
            )
            assert "Stealth: Game/One" in response.text
            assert LICENSE_DISCLAIMER in response.text
        default = client.get(f"/api/projects/{pid}/credits")
        assert default.headers["content-disposition"].endswith('-credits.txt"')
        payload = json.loads(client.get(f"/api/projects/{pid}/credits?format=json").text)
        assert payload["project"] == "Stealth: Game/One"
        # the stored attribution is used verbatim; the unknown and red tracks are listed
        assert [i["title"] for i in payload["items"]] == ["Shadow Walk", "Mystery Box", "Red Alert"]
        assert payload["items"][0]["attribution"] == "Shadow Walk by Ada"
        text = client.get(f"/api/projects/{pid}/credits").text
        assert text.index("== Green") < text.index("== Unknown") < text.index("== Red")


def test_credits_red_track_shows_commercial_link_and_errors(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        pid = _new(client, "!!!")
        red = client.ids["Red Alert"]
        client.repo._conn.execute(
            "UPDATE tracks SET commercial_license_url = 'https://licensing.example/red' "
            "WHERE id = ?",
            (red,),
        )
        client.put(f"/api/projects/{pid}/items/{red}")
        response = client.get(f"/api/projects/{pid}/credits")
        assert "Commercial license available: https://licensing.example/red" in response.text
        assert 'filename="project-credits.txt"' in response.headers["content-disposition"]
        assert client.get(f"/api/projects/{pid}/credits?format=pdf").status_code == 422
        assert client.get("/api/projects/999/credits").status_code == 404


def test_empty_project_credits(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        pid = _new(client)
        response = client.get(f"/api/projects/{pid}/credits?format=md")
        assert response.status_code == 200 and LICENSE_DISCLAIMER in response.text


def test_cross_origin_writes_are_refused(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        bad = {"Origin": "https://evil.example"}
        assert client.post("/api/projects", json={"name": "x"}, headers=bad).status_code == 403
        assert client.get("/api/projects").json() == []
