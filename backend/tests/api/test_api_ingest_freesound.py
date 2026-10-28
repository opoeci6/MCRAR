"""POST /api/ingest/freesound and the Freesound side of reprocess (fakes, no network, no torch)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from api_support import ApiClient, IngestFreesound, IngestJamendo, make_client, wait_done
from recommend_support import MODEL_ID, fake_features

from mcrar.catalog import TrackRecord
from mcrar.ingest import pipeline
from mcrar.sources import FreesoundAuthError, FreesoundError

NO_KEY = (
    "Freesound API key is not set: add it in Settings, or `mcrar secrets set freesound_api_key`"
)


@pytest.fixture(autouse=True)
def fast_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "analyze_audio", fake_features)


def start(client: ApiClient, **body: object) -> dict[str, Any]:
    response = client.post("/api/ingest/freesound", json=body)
    assert response.status_code == 202, response.text
    return response.json()["job"]


def add_freesound_track(client: ApiClient, n: int = 1) -> int:
    return client.repo.upsert_track(
        TrackRecord(
            source="freesound",
            source_id=str(n),
            title=f"Old Sound {n}",
            stream_url=f"https://cdn.freesound.org/previews/{n}/p.mp3",
            risk="green",
        )
    )


def test_ingest_adds_the_sounds_and_embeds_them_with_the_pool_model(tmp_path: Path) -> None:
    freesound = IngestFreesound(3)
    with make_client(tmp_path, freesound=freesound) as client:
        job = start(
            client,
            query=" calm pad ",
            tags=[" Loop ", ""],
            licenses=["cc0"],
            duration_min_s=20,
            duration_max_s=90,
            sort="downloads_desc",
            limit=3,
        )
        assert job["kind"] == "ingest-freesound"
        assert job["params"]["limit"] == 3 and job["params"]["licenses"] == ["cc0"]
        assert "api_key" not in str(job) and "token" not in str(job).lower()
        done = wait_done(client, job["id"])
        assert done["status"] == "done" and done["error"] is None
        report = done["report"]
        assert (report["seen"], report["new"], report["processed"], report["failed"]) == (
            3,
            3,
            3,
            0,
        )
        new = client.repo.get_track_by_source("freesound", "7001")
        assert new is not None and new.title == "New Sound 1" and new.license_family == "cc0"
        assert client.repo.get_embedding(new.id, MODEL_ID) is not None
        assert client.repo.get_features(new.id) is not None
        assert client.loader.keys == ["clap"]
        assert freesound.fetched == ["7001", "7002", "7003"] and freesound.closed
        assert freesound.queries == [
            {
                "query": " calm pad ",
                "tags": ["Loop"],
                "licenses": ["cc0"],
                "duration_min_s": 20.0,
                "duration_max_s": 90.0,
                "sort": "downloads_desc",
                "limit": 3,
            }
        ]


def test_the_defaults_are_cc0_and_by_ten_to_six_hundred_seconds(tmp_path: Path) -> None:
    freesound = IngestFreesound(1)
    with make_client(tmp_path, freesound=freesound) as client:
        job = start(client, tags=["ambient"], embed=False)
        assert wait_done(client, job["id"])["status"] == "done"
        (query,) = freesound.queries
        assert query["licenses"] == ["cc0", "by"] and query["sort"] == "score"
        assert (query["duration_min_s"], query["duration_max_s"], query["limit"]) == (10, 600, 50)
        assert client.loader.keys == []  # embed=False


def test_a_tag_alone_or_a_query_alone_is_enough(tmp_path: Path) -> None:
    with make_client(tmp_path, freesound=IngestFreesound(1)) as client:
        first = start(client, query="rain", embed=False)
        wait_done(client, first["id"])
        second = start(client, tags=["rain"], embed=False)
        assert wait_done(client, second["id"])["status"] == "done"


def test_a_missing_api_key_is_503_and_starts_no_job(tmp_path: Path) -> None:
    for n, freesound in enumerate((None, FreesoundError("no key"))):
        with make_client(tmp_path / str(n), freesound=freesound) as client:
            response = client.post("/api/ingest/freesound", json={"query": "rain"})
            assert response.status_code == 503
            assert response.json() == {"detail": NO_KEY}
            assert client.get("/api/jobs").json() == {"jobs": []}


@pytest.mark.parametrize(
    "body",
    [
        {},  # neither a query nor a tag
        {"query": "   "},
        {"query": "", "tags": [" "]},
        {"query": "x" * 201},
        {"query": "a", "tags": [f"t{n}" for n in range(11)]},
        {"query": "a", "licenses": []},
        {"query": "a", "licenses": ["gpl"]},
        {"query": "a", "licenses": "cc0"},
        {"query": "a", "duration_min_s": -1},
        {"query": "a", "duration_max_s": 3601},
        {"query": "a", "duration_min_s": 100, "duration_max_s": 50},
        {"query": "a", "sort": "random"},
        {"query": "a", "limit": 0},
        {"query": "a", "limit": 501},
        {"query": "a", "tags": "rain"},
        {"query": "a", "unknown": 1},
        {"query": "a", "tags": ["has space"]},  # rejected by the client's tag check
        {"query": "a", "tags": ["x" * 101]},
    ],
)
def test_a_bad_body_is_422_and_starts_no_job(tmp_path: Path, body: dict[str, Any]) -> None:
    freesound = IngestFreesound(1)
    with make_client(tmp_path, freesound=freesound) as client:
        response = client.post("/api/ingest/freesound", json=body)
        assert response.status_code == 422, response.text
        assert client.get("/api/jobs").json() == {"jobs": []}
        assert freesound.queries == []


def test_the_limits_themselves_are_accepted(tmp_path: Path) -> None:
    body = {
        "query": "a",
        "limit": 500,
        "duration_min_s": 0,
        "duration_max_s": 3600,
        "licenses": ["cc0", "by", "by-nc", "sampling+"],
        "embed": False,
    }
    with make_client(tmp_path, freesound=IngestFreesound(1)) as client:
        assert wait_done(client, start(client, **body)["id"])["status"] == "done"


def test_an_auth_error_ends_the_job_failed_with_the_partial_report(tmp_path: Path) -> None:
    class Rejecting(IngestFreesound):
        def fetch_audio(self, track: Any, **kwargs: Any) -> bytes:
            raise FreesoundAuthError("Freesound rejected the request (HTTP 401)")

    freesound = Rejecting(2)
    with make_client(tmp_path, freesound=freesound) as client:
        done = wait_done(client, start(client, query="rain", embed=False)["id"])
        assert done["status"] == "failed"
        assert "FreesoundAuthError" in done["error"] and done["report"]["aborted"] is not None
        assert freesound.closed


# -- reprocess -----------------------------------------------------------------------------------


def test_reprocess_embeds_freesound_tracks_with_the_freesound_client(tmp_path: Path) -> None:
    freesound = IngestFreesound(0)
    with make_client(tmp_path, jamendo=IngestJamendo(0), freesound=freesound) as client:
        track_id = add_freesound_track(client)
        response = client.post(
            "/api/ingest/reprocess", json={"what": "embed", "source": "freesound"}
        )
        assert response.status_code == 202, response.text
        assert response.json()["job"]["params"] == {
            "what": "embed",
            "force": False,
            "source": "freesound",
        }
        done = wait_done(client, response.json()["job"]["id"])
        assert done["status"] == "done"
        assert (done["report"]["processed"], done["report"]["failed"]) == (1, 0)
        assert client.repo.get_embedding(track_id, MODEL_ID) is not None
        assert freesound.fetched == ["1"] and freesound.closed


def test_reprocess_of_freesound_by_name_needs_the_key(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        add_freesound_track(client)
        response = client.post(
            "/api/ingest/reprocess", json={"what": "embed", "source": "freesound"}
        )
        assert response.status_code == 503 and response.json() == {"detail": NO_KEY}
        assert client.get("/api/jobs").json() == {"jobs": []}


def test_reprocess_without_a_catalog_of_freesound_tracks_never_opens_a_client(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path, freesound=FreesoundError("no key")) as client:
        response = client.post("/api/ingest/reprocess", json={"what": "embed", "source": "local"})
        assert response.status_code == 202
        assert wait_done(client, response.json()["job"]["id"])["status"] == "done"


def test_a_whole_catalog_reprocess_without_a_key_fails_only_the_freesound_tracks(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path, jamendo=IngestJamendo(0)) as client:
        track_id = add_freesound_track(client)
        response = client.post("/api/ingest/reprocess", json={"what": "embed"})
        assert response.status_code == 202, response.text
        done = wait_done(client, response.json()["job"]["id"])
        assert done["status"] == "done"
        ours = [f for f in done["report"]["failures"] if f["source_id"] == "1"]
        assert any("no Freesound client" in f["message"] for f in ours)
        assert client.repo.get_embedding(track_id, MODEL_ID) is None


def test_a_jamendo_reprocess_does_not_open_the_freesound_client(tmp_path: Path) -> None:
    freesound = IngestFreesound(0)
    with make_client(tmp_path, jamendo=IngestJamendo(0), freesound=freesound) as client:
        track_id = add_freesound_track(client)
        response = client.post("/api/ingest/reprocess", json={"what": "embed", "source": "jamendo"})
        assert wait_done(client, response.json()["job"]["id"])["status"] == "done"
        assert not freesound.fetched and not freesound.closed  # never opened
        assert client.repo.get_embedding(track_id, MODEL_ID) is None
