"""PUT /api/tracks/{id}/license: declaring the licence of a local track by hand."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from api_support import ApiClient, make_client, wait_done
from recommend_support import fake_features, write_wav

from mcrar.catalog import TrackRecord
from mcrar.ingest import pipeline

UNKNOWN_CREDIT = '"Song" by Ana (https://ana.example), license unknown'


def add_local(client: ApiClient, **fields: object) -> int:
    record = TrackRecord(
        source="local",
        source_id="hash-1",
        title="Song",
        artist="Ana",
        source_url="https://ana.example",
        attribution_text=UNKNOWN_CREDIT,
        **fields,  # type: ignore[arg-type]
    )
    return client.repo.upsert_track(record)


def put(client: ApiClient, track_id: int, license_text: object):  # noqa: ANN201
    return client.put(f"/api/tracks/{track_id}/license", json={"license": license_text})


def test_the_licence_of_a_local_track_can_be_set(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        track_id = add_local(client)
        response = put(client, track_id, "CC-BY-4.0")
        assert response.status_code == 200
        body = response.json()
        assert body == client.get(f"/api/tracks/{track_id}").json()  # the detail, as is
        assert (body["risk"], body["license_code"]) == ("green", "CC BY 4.0")
        assert body["license_url"] == "https://creativecommons.org/licenses/by/4.0/"
        expected = (
            '"Song" by Ana (https://ana.example), licensed under CC BY 4.0 '
            "(https://creativecommons.org/licenses/by/4.0/)"
        )
        assert body["attribution_text"] == expected
        lic = body["license"]
        assert lic["set_by_user"] is True and lic["family"] == "cc-by"
        assert lic["attribution_text"] == expected and lic["attribution_required"] is True
        assert (lic["commercial_ok"], lic["derivatives_ok"], lic["share_alike"]) == (True,) * 2 + (
            False,
        )
        # the credits report reads the stored columns
        credits = client.get(f"/api/tracks/{track_id}/credits", params={"format": "json"}).json()
        (item,) = credits["items"]
        assert item["license"]["family"] == "cc-by" and item["attribution"] == expected
        assert "CC BY 4.0" in client.get(f"/api/tracks/{track_id}/credits").text


def test_a_track_starts_with_the_flag_off(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        track_id = add_local(client)
        assert client.get(f"/api/tracks/{track_id}").json()["license"]["set_by_user"] is False


def test_the_new_risk_reaches_stats_listing_and_the_search_filter(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        track_id = add_local(client)
        by_risk = client.get("/api/stats").json()["tracks_by_risk"]
        assert 1 <= by_risk["unknown"]
        assert track_id not in client.repo.filter_track_ids(max_risk="red")
        put(client, track_id, "CC0")
        after = client.get("/api/stats").json()["tracks_by_risk"]
        assert after["unknown"] == by_risk["unknown"] - 1
        assert after["green"] == by_risk.get("green", 0) + 1
        assert track_id in client.repo.filter_track_ids(max_risk="green")
        listed = client.get("/api/tracks", params={"risk": "green", "source": "local"}).json()
        assert track_id in [t["id"] for t in listed["items"]]
        put(client, track_id, "CC-BY-NC-4.0")  # red: out of a green search again
        assert track_id not in client.repo.filter_track_ids(max_risk="green")
        assert track_id in client.repo.filter_track_ids(max_risk="red")


def test_the_text_a_sidecar_added_to_the_credit_line_is_kept(tmp_path: Path) -> None:
    generated = '"Song" by Ana (https://ana.example), dedicated to the public domain (CC0 1.0)'
    with make_client(tmp_path) as client:
        track_id = client.repo.upsert_track(
            TrackRecord(
                source="local",
                source_id="hash-2",
                title="Song",
                artist="Ana",
                source_url="https://ana.example",
                license_code="CC0 1.0",
                license_family="cc0",
                risk="green",
                attribution_text=generated + " Music by Ana",
            )
        )
        body = put(client, track_id, "CC-BY-4.0").json()
        assert body["attribution_text"].endswith(
            "licensed under CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/) Music by Ana"
        )
        again = put(client, track_id, "CC0").json()  # and again through another licence
        assert again["attribution_text"] == generated + " Music by Ana"


def test_unknown_clears_the_flag_and_says_so_in_the_credit_line(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        track_id = add_local(client)
        assert put(client, track_id, "CC0").json()["license"]["set_by_user"] is True
        body = put(client, track_id, "unknown").json()
        assert body["license"]["set_by_user"] is False
        assert (body["risk"], body["license"]["family"]) == ("unknown", "unknown")
        assert body["attribution_text"] == UNKNOWN_CREDIT


def test_an_unrecognised_licence_is_422(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        track_id = add_local(client)
        response = put(client, track_id, "my own terms")
        assert response.status_code == 422
        assert "unrecognised license" in response.json()["detail"]
        stored = client.get(f"/api/tracks/{track_id}").json()
        assert stored["risk"] == "unknown" and stored["license"]["set_by_user"] is False


@pytest.mark.parametrize("value", ["", "x" * 201, 5, None])
def test_the_body_is_validated(tmp_path: Path, value: object) -> None:
    with make_client(tmp_path) as client:
        track_id = add_local(client)
        assert put(client, track_id, value).status_code == 422
        extra = client.put(f"/api/tracks/{track_id}/license", json={"license": "CC0", "x": 1})
        assert extra.status_code == 422


def test_a_jamendo_or_freesound_track_is_422(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        jamendo = client.ids["Shadow Walk"]
        before = client.get(f"/api/tracks/{jamendo}").json()
        response = put(client, jamendo, "CC0")
        assert response.status_code == 422
        assert response.json()["detail"] == (
            "The licence of a Jamendo or Freesound track comes from the source."
        )
        freesound = client.repo.upsert_track(TrackRecord(source="freesound", source_id="9"))
        assert put(client, freesound, "CC0").status_code == 422
        assert client.get(f"/api/tracks/{jamendo}").json() == before


def test_an_unknown_track_is_404(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert put(client, 99999, "CC0").status_code == 404


@pytest.fixture
def busy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """A client whose job manager has a job running until the test lets it go."""
    reached, go = threading.Event(), threading.Event()

    def gate(source: object, *, max_seconds: float | None = None):  # noqa: ANN202
        reached.set()
        assert go.wait(20), "the test never opened the gate"
        return fake_features(source)

    monkeypatch.setattr(pipeline, "analyze_audio", gate)
    folder = tmp_path / "music"
    write_wav(folder / "a.wav", freq=330.0)
    with make_client(tmp_path) as client:
        job = client.post("/api/ingest/local", json={"path": str(folder), "embed": False})
        job_id = job.json()["job"]["id"]
        try:
            assert reached.wait(20)
            yield client
        finally:
            go.set()
        wait_done(client, job_id)


def test_setting_a_licence_is_409_while_a_job_runs(busy: ApiClient) -> None:
    track_id = add_local(busy)
    response = put(busy, track_id, "CC0")
    assert response.status_code == 409 and "job is running" in response.json()["detail"]
    assert busy.get(f"/api/tracks/{track_id}").json()["risk"] == "unknown"
