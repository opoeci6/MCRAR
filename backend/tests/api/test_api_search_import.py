"""POST /api/search/import: a Jamendo import for a text search (fakes, no network, no torch)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from api_support import IngestJamendo, make_client, parse_sse, wait_done
from recommend_support import MODEL_ID, fake_features

from mcrar.ingest import pipeline
from mcrar.sources import JamendoError

URL = "/api/search/import"


@pytest.fixture(autouse=True)
def fast_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "analyze_audio", fake_features)


class Gate:
    """An analyser that stops inside the first track until the test lets it go."""

    def __init__(self) -> None:
        self.reached = threading.Event()
        self.go = threading.Event()
        self.calls = 0

    def __call__(self, source: object, *, max_seconds: float | None = None):  # noqa: ANN204
        self.calls += 1
        if self.calls == 1:
            self.reached.set()
            assert self.go.wait(20), "the test never opened the gate"
        return fake_features(source)


def test_it_starts_an_ingest_query_job_and_imports_new_tracks(tmp_path: Path) -> None:
    jamendo = IngestJamendo(5)
    with make_client(tmp_path, jamendo=jamendo) as client:
        response = client.post(URL, json={"text": "  tense stealth level ", "limit": 3})
        assert response.status_code == 202, response.text
        job = response.json()["job"]
        assert job["kind"] == "ingest-query"
        assert job["params"] == {
            "text": "tense stealth level",  # as sent, trimmed
            "limit": 3,
            "query": "tense stealth level",  # as parsed
        }
        done = wait_done(client, job["id"])
        assert done["status"] == "done" and done["error"] is None
        report = done["report"]
        assert (report["seen"], report["new"], report["processed"], report["failed"]) == (
            3,
            3,
            3,
            0,
        )
        new = [client.repo.get_track_by_source("jamendo", str(9001 + n)) for n in range(3)]
        assert all(t is not None for t in new)
        assert report["new_track_ids"] == [t.id for t in new]
        assert client.repo.get_track_by_source("jamendo", "9004") is None  # stopped at the limit
        assert all(client.repo.get_embedding(t.id, MODEL_ID) is not None for t in new)
        assert jamendo.closed
        assert len(jamendo.queries) == 1 and jamendo.queries[0]["limit"] == 200
        events = parse_sse(client.get(f"/api/jobs/{job['id']}/events").text)
        assert events[-1]["event"] == "done"
        assert events[-1]["data"]["report"]["new_track_ids"] == report["new_track_ids"]
        progress = [e["data"] for e in events if e["event"] == "progress"]
        assert progress[1]["total"] == 3  # the limit is the progress total
        assert client.loader.keys == ["clap"]  # the default model is clap: loaded once


def test_a_follow_up_search_ranks_the_new_tracks_with_the_catalog(tmp_path: Path) -> None:
    with make_client(tmp_path, jamendo=IngestJamendo(2)) as client:
        job = client.post(URL, json={"text": "tense stealth level", "limit": 2}).json()["job"]
        wait_done(client, job["id"])
        body = {"text": "tense stealth level", "limit": 50}
        items = client.post("/api/search", json=body).json()["items"]
        titles = {item["title"] for item in items}
        assert {"New Track 1", "New Track 2", "Shadow Walk"} <= titles


def test_the_jamendo_queries_carry_the_normalised_text_and_the_mapped_filters(
    tmp_path: Path,
) -> None:
    jamendo = IngestJamendo(3)
    filters = {
        "vocal": "instrumental",
        "duration_min_s": 60,
        "duration_max_s": 240,
        "max_risk": "green",
        "bpm_max": 100,  # no Jamendo equivalent
    }
    with make_client(tmp_path, jamendo=jamendo) as client:
        job = client.post(URL, json={"text": "Lo-Fi dark cave", "filters": filters, "limit": 10})
        wait_done(client, job.json()["job"]["id"])
        common = {
            "vocalinstrumental": "instrumental",
            "duration_between": (60, 240),
            "commercial_only": True,
            "limit": 200,
        }
        # 3 new tracks exist: the later queries run too and find only known ones.
        assert jamendo.queries == [
            {"search": "lofi dark cave", "order": "relevance", **common},
            {"search": "Lo-Fi dark cave", "order": "relevance", **common},
            {"fuzzytags": ["lofi", "dark", "cave"], **common},
        ]


def test_the_semantic_text_is_what_remains_after_the_filter_phrases(tmp_path: Path) -> None:
    jamendo = IngestJamendo(1)
    with make_client(tmp_path, jamendo=jamendo) as client:
        job = client.post(URL, json={"text": "tense stealth level under 90 bpm"}).json()["job"]
        assert job["params"]["text"] == "tense stealth level under 90 bpm"
        assert job["params"]["query"] == "tense stealth level"
        assert job["params"]["limit"] == 50  # the default
        wait_done(client, job["id"])
        assert jamendo.queries[0]["search"] == "tense stealth level"


def test_a_query_without_semantic_text_is_422_and_starts_no_job(tmp_path: Path) -> None:
    with make_client(tmp_path, jamendo=IngestJamendo(1)) as client:
        response = client.post(URL, json={"text": "under 90 bpm"})
        assert response.status_code == 422
        assert response.json() == {"detail": "describe the music to search Jamendo for"}
        assert client.get("/api/jobs").json() == {"jobs": []}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"text": ""},
        {"text": "x" * 301},
        {"text": "calm", "limit": 0},
        {"text": "calm", "limit": 101},
        {"text": "calm", "unknown": 1},
        {"text": "calm", "filters": {"vocal": "both"}},
        {"text": "calm", "filters": {"nope": 1}},
    ],
)
def test_a_bad_body_is_422(tmp_path: Path, body: dict) -> None:
    with make_client(tmp_path, jamendo=IngestJamendo(1)) as client:
        assert client.post(URL, json=body).status_code == 422
        assert client.get("/api/jobs").json() == {"jobs": []}


def test_a_missing_client_id_is_503_and_starts_no_job(tmp_path: Path) -> None:
    with make_client(tmp_path, jamendo=JamendoError("client id is missing")) as client:
        response = client.post(URL, json={"text": "calm"})
        assert response.status_code == 503
        assert response.json() == {"detail": "Jamendo client id is not set"}
        assert client.get("/api/jobs").json() == {"jobs": []}


def test_without_torch_it_is_503_and_starts_no_job(tmp_path: Path) -> None:
    jamendo = IngestJamendo(1)
    with make_client(tmp_path, jamendo=jamendo, torch=False) as client:
        response = client.post(URL, json={"text": "calm"})
        assert response.status_code == 503 and "torch" in response.json()["detail"]
        assert client.get("/api/jobs").json() == {"jobs": []}
        assert jamendo.queries == []


def test_a_second_import_while_a_job_runs_is_409_and_closes_its_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = Gate()
    monkeypatch.setattr(pipeline, "analyze_audio", gate)
    jamendo = IngestJamendo(3)
    with make_client(tmp_path, jamendo=jamendo) as client:
        first = client.post(URL, json={"text": "calm", "limit": 3}).json()["job"]["id"]
        try:
            assert gate.reached.wait(20)
            closed = jamendo.closed  # the running job holds the (shared fake) client
            busy = client.post(URL, json={"text": "calm"})
            assert busy.status_code == 409 and first in busy.json()["detail"]
            assert jamendo.closed  # the refused request closed its own client
            assert closed is False
        finally:
            gate.go.set()
        assert wait_done(client, first)["status"] == "done"


def test_cancelling_ends_cancelled_with_the_new_tracks_so_far(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = Gate()
    monkeypatch.setattr(pipeline, "analyze_audio", gate)
    with make_client(tmp_path, jamendo=IngestJamendo(5)) as client:
        job_id = client.post(URL, json={"text": "calm", "limit": 5}).json()["job"]["id"]
        try:
            assert gate.reached.wait(20)
            assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 202
        finally:
            gate.go.set()
        done = wait_done(client, job_id)
        assert done["status"] == "cancelled"
        assert done["report"]["aborted"] == "cancelled"
        assert 1 <= len(done["report"]["new_track_ids"]) <= 5
        assert gate.calls == 1


def test_the_report_lists_at_most_200_new_track_ids() -> None:
    from mcrar.api.jobs import MAX_NEW_TRACK_IDS, report_to_dict
    from mcrar.ingest import IngestReport

    report = IngestReport(300, 300, 0, 300, 0, 0, [], 1.0, new_track_ids=list(range(300)))
    assert report_to_dict(report)["new_track_ids"] == list(range(MAX_NEW_TRACK_IDS))
    assert MAX_NEW_TRACK_IDS == 200
    assert report_to_dict(IngestReport(0, 0, 0, 0, 0, 0, [], 0.0))["new_track_ids"] == []
