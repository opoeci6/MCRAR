"""PUT/DELETE/GET /api/ratings and the ``rating`` field of the search results."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from api_support import ApiClient, make_client

QUERY = {"text": "tense stealth level"}


def put(client: ApiClient, title: str, rating: int, **query: object):
    body = {**(query or QUERY), "track_id": client.ids[title], "rating": rating}
    return client.put("/api/ratings", json=body)


def delete(client: ApiClient, title: str, **query: object):
    body = {**(query or QUERY), "track_id": client.ids[title]}
    return client.request("DELETE", "/api/ratings", json=body)


def ratings_in_search(client: ApiClient, **body: object) -> dict[str, int | None]:
    items = client.post("/api/search", json={**(body or QUERY), "limit": 50}).json()["items"]
    assert items and all("rating" in item for item in items)
    return {item["title"]: item["rating"] for item in items}


def test_put_stores_a_rating_and_search_shows_it_for_the_same_query(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = put(client, "Shadow Walk", 2)
        assert response.status_code == 200
        assert response.json() == {
            "query_key": "text:tense stealth level",
            "track_id": client.ids["Shadow Walk"],
            "rating": 2,
        }
        assert put(client, "Quiet Vents", 0).status_code == 200

        shown = ratings_in_search(client)
        assert shown["Shadow Walk"] == 2 and shown["Quiet Vents"] == 0
        assert shown["Night Heist"] is None
        # the same words, spelled differently and with other filters, are the same query
        other = ratings_in_search(
            client, text="  Tense STEALTH   level ", filters={"max_risk": "green"}
        )
        assert other["Shadow Walk"] == 2
        # a different query does not show them
        assert set(ratings_in_search(client, text="epic battle").values()) == {None}


def test_putting_again_replaces_the_rating(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        put(client, "Shadow Walk", 2)
        assert put(client, "Shadow Walk", 1).json()["rating"] == 1
        assert ratings_in_search(client)["Shadow Walk"] == 1
        assert client.get("/api/ratings").json()["total"] == 1


def test_filter_only_queries_are_keyed_by_the_resolved_labels(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        by_synonym = {"filters": {"moods": ["spooky"]}}
        response = put(client, "Night Heist", 2, **by_synonym)
        assert response.status_code == 200
        assert response.json()["query_key"] == 'filters:{"moods":["dark"]}'
        assert ratings_in_search(client, filters={"moods": ["dark"]})["Night Heist"] == 2


def test_unknown_track_is_404_and_a_bad_query_is_422(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        missing = client.put("/api/ratings", json={**QUERY, "track_id": 99999, "rating": 1})
        assert missing.status_code == 404 and "99999" in missing.json()["detail"]
        empty = client.put("/api/ratings", json={"track_id": client.ids["Sunny Day"], "rating": 1})
        assert empty.status_code == 422
        assert "search text or at least one filter" in empty.json()["detail"]
        blank = client.put(
            "/api/ratings", json={"text": " ", "track_id": client.ids["Sunny Day"], "rating": 1}
        )
        assert blank.status_code == 422
        bad_label = put(client, "Sunny Day", 1, filters={"genres": ["polka"]})
        assert bad_label.status_code == 422 and "polka" in bad_label.json()["detail"]
        assert client.get("/api/ratings").json() == {"items": [], "total": 0}


@pytest.mark.parametrize(
    "extra",
    [{"rating": 3}, {"rating": -1}, {"rating": "good"}, {"unexpected": 1}, {"track_id": "x"}],
)
def test_invalid_fields_are_422(tmp_path: Path, extra: dict) -> None:
    with make_client(tmp_path) as client:
        body = {**QUERY, "track_id": client.ids["Sunny Day"], "rating": 1, **extra}
        assert client.put("/api/ratings", json=body).status_code == 422


def test_delete_removes_the_rating_then_404(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        put(client, "Shadow Walk", 2)
        assert delete(client, "Shadow Walk").status_code == 204
        assert ratings_in_search(client)["Shadow Walk"] is None
        missing = delete(client, "Shadow Walk")
        assert missing.status_code == 404
        assert delete(client, "Shadow Walk", text="never rated").status_code == 404
        assert client.request("DELETE", "/api/ratings", json={"track_id": 1}).status_code == 422


def test_list_shows_newest_first_with_the_track_and_the_filters(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        ticks = iter(range(1, 1000))  # every write a second later (Windows' clock can repeat)
        client.repo._clock = lambda: (
            datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=next(ticks))
        )
        put(client, "Shadow Walk", 2)
        put(client, "Epic Quest", 1, text="epic battle", filters={"vocal": "instrumental"})
        put(client, "Shadow Walk", 1)  # replaces the first rating and is now the newest
        body = client.get("/api/ratings").json()
        assert body["total"] == 2
        first = body["items"][0]
        assert first["track"] == {
            "id": client.ids["Shadow Walk"],
            "title": "Shadow Walk",
            "artist": "Ada",
        }
        assert (first["query_key"], first["query_text"], first["rating"]) == (
            "text:tense stealth level",
            "tense stealth level",
            1,
        )
        assert first["filters"] == {} and first["updated_at"]
        epic = next(i for i in body["items"] if i["query_text"] == "epic battle")
        assert epic["filters"] == {"vocal": "instrumental"}

        page = client.get("/api/ratings", params={"limit": 1, "offset": 1}).json()
        assert page["total"] == 2 and [i["query_text"] for i in page["items"]] == ["epic battle"]
        assert client.get("/api/ratings", params={"limit": 0}).status_code == 422


def test_a_cross_origin_page_cannot_rate(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        body = {**QUERY, "track_id": client.ids["Shadow Walk"], "rating": 2}
        refused = client.put("/api/ratings", json=body, headers={"Origin": "https://evil.test"})
        assert refused.status_code == 403
        assert client.get("/api/ratings").json()["total"] == 0
        local = client.put("/api/ratings", json=body, headers={"Origin": "http://localhost:5173"})
        assert local.status_code == 200
        gone = client.request(
            "DELETE",
            "/api/ratings",
            json={**QUERY, "track_id": client.ids["Shadow Walk"]},
            headers={"Origin": "https://evil.test"},
        )
        assert gone.status_code == 403 and client.get("/api/ratings").json()["total"] == 1
