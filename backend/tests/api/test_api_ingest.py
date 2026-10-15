"""The ingest routes: start jobs, watch them over SSE, cancel them (fakes, no network, no torch)."""

from __future__ import annotations

import asyncio
import sys
import threading
import time
import types
from pathlib import Path

import pytest
from api_support import (
    ApiClient,
    IngestJamendo,
    make_client,
    parse_sse,
    wait_done,
)
from recommend_support import MODEL_ID, fake_features, write_wav

from mcrar.api.jobs import Job
from mcrar.api.routes import ingest as ingest_routes
from mcrar.ingest import pipeline
from mcrar.sources import JamendoError


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


def titles(client: ApiClient) -> set[str]:
    items = client.get("/api/tracks", params={"limit": 200}).json()["items"]
    return {t["title"] for t in items}


def start_jamendo(client: ApiClient, **body: object) -> dict:
    response = client.post("/api/ingest/jamendo", json=body)
    assert response.status_code == 202, response.text
    return response.json()["job"]


# -- Jamendo -------------------------------------------------------------------------------------


def test_jamendo_ingest_adds_the_tracks_and_embeds_them_with_the_pool_model(tmp_path: Path) -> None:
    jamendo = IngestJamendo(3)
    with make_client(tmp_path, jamendo=jamendo) as client:
        job = start_jamendo(
            client, tags=[" rock ", ""], search="fast", vocalinstrumental="instrumental", limit=3
        )
        assert job["status"] in ("running", "done") and job["kind"] == "ingest-jamendo"
        assert job["params"]["limit"] == 3 and "client_id" not in str(job)
        done = wait_done(client, job["id"])
        assert done["status"] == "done" and done["error"] is None
        report = done["report"]
        assert (report["seen"], report["new"], report["processed"], report["failed"]) == (
            3,
            3,
            3,
            0,
        )
        assert report["aborted"] is None
        assert {"New Track 1", "New Track 2", "New Track 3"} <= titles(client)
        new = client.repo.get_track_by_source("jamendo", "9001")
        assert new is not None and client.repo.get_embedding(new.id, MODEL_ID) is not None
        assert client.repo.get_features(new.id) is not None
        assert client.loader.keys == ["clap"] and not client.embedder.closed
        assert jamendo.closed
        query = jamendo.queries[0]
        assert query["tags"] == ["rock"] and query["search"] == "fast" and query["limit"] == 3
        assert query["vocalinstrumental"] == "instrumental" and "commercial_only" not in query


def test_events_stream_in_order_and_replay_after_a_given_id(tmp_path: Path) -> None:
    with make_client(tmp_path, jamendo=IngestJamendo(3)) as client:
        job_id = start_jamendo(client, limit=3)["id"]
        wait_done(client, job_id)
        response = client.get(f"/api/jobs/{job_id}/events")
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["x-accel-buffering"] == "no"
        events = parse_sse(response.text)
        assert [e["id"] for e in events] == list(range(1, len(events) + 1))
        assert events[0]["event"] == "started" and events[-1]["event"] == "done"
        assert events[-1]["data"]["report"]["processed"] == 3
        progress = [e["data"] for e in events if e["event"] == "progress"]
        assert [p["kind"] for p in progress] == [
            "started", "track_done", "track_done", "track_done", "finished",
        ]  # fmt: skip
        assert progress[1]["title"] == "New Track 1" and progress[1]["total"] == 3
        assert response.text.startswith("id: 1\nevent: started\ndata: {")

        replay = client.get(f"/api/jobs/{job_id}/events", headers={"Last-Event-ID": "3"})
        assert [e["id"] for e in parse_sse(replay.text)] == [e["id"] for e in events[3:]]
        query = client.get(f"/api/jobs/{job_id}/events", params={"after": len(events) - 1})
        assert [e["event"] for e in parse_sse(query.text)] == ["done"]
        junk = client.get(f"/api/jobs/{job_id}/events", headers={"Last-Event-ID": "x"})
        assert len(parse_sse(junk.text)) == len(events)
        assert client.get(f"/api/jobs/{job_id}/events", params={"after": -1}).status_code == 422
        assert client.get("/api/jobs/nope/events").status_code == 404


def test_cancel_during_a_run_ends_cancelled_with_the_partial_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = Gate()
    monkeypatch.setattr(pipeline, "analyze_audio", gate)
    with make_client(tmp_path, jamendo=IngestJamendo(5)) as client:
        job_id = start_jamendo(client, limit=5, embed=False)["id"]
        try:
            assert gate.reached.wait(20)
            response = client.post(f"/api/jobs/{job_id}/cancel")
            assert response.status_code == 202 and response.json()["job"]["cancel_requested"]
        finally:
            gate.go.set()
        done = wait_done(client, job_id)
        assert done["status"] == "cancelled"
        assert done["report"]["processed"] == 1 and done["report"]["aborted"] is not None
        events = parse_sse(client.get(f"/api/jobs/{job_id}/events").text)
        assert events[-1]["event"] == "cancelled"
        assert events[-1]["data"]["report"]["processed"] == 1
        assert [e["data"]["kind"] for e in events if e["event"] == "progress"][-1] == "finished"
        assert gate.calls == 1  # the later tracks were not analysed
        assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 409
        assert client.post("/api/jobs/nope/cancel").status_code == 404


def test_a_second_start_while_a_job_runs_is_409(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = Gate()
    monkeypatch.setattr(pipeline, "analyze_audio", gate)
    with make_client(tmp_path, jamendo=IngestJamendo(2)) as client:
        first = start_jamendo(client, limit=2, embed=False)["id"]
        try:
            assert gate.reached.wait(20)
            busy = client.post("/api/ingest/jamendo", json={"embed": False})
            assert busy.status_code == 409 and first in busy.json()["detail"]
            local = client.post("/api/ingest/reprocess", json={"what": "tag"})
            assert local.status_code == 409
            assert [j["id"] for j in client.get("/api/jobs").json()["jobs"]] == [first]
        finally:
            gate.go.set()
        assert wait_done(client, first)["status"] == "done"
        again = start_jamendo(client, limit=2, embed=False)
        assert wait_done(client, again["id"])["status"] == "done"
        jobs = client.get("/api/jobs").json()["jobs"]
        assert [j["id"] for j in jobs] == [again["id"], first]  # newest first
        assert "report" not in jobs[0] and jobs[0]["progress"]["index"] == 2


def test_missing_client_id_is_503_and_starts_no_job(tmp_path: Path) -> None:
    secret = JamendoError("JAMENDO client id is missing")
    with make_client(tmp_path, jamendo=secret) as client:
        response = client.post("/api/ingest/jamendo", json={"limit": 5})
        assert response.status_code == 503
        assert response.json() == {"detail": "Jamendo client id is not set"}
        assert client.get("/api/jobs").json() == {"jobs": []}


def test_a_bad_body_is_422(tmp_path: Path) -> None:
    with make_client(tmp_path, jamendo=IngestJamendo(1)) as client:
        for body in (
            {"limit": 0},
            {"limit": 1001},
            {"vocalinstrumental": "both"},
            {"unknown": 1},
            {"tags": "rock"},
        ):
            assert client.post("/api/ingest/jamendo", json=body).status_code == 422, body
        assert client.get("/api/jobs").json() == {"jobs": []}


def test_a_failing_search_ends_failed_without_leaking_details(tmp_path: Path) -> None:
    class Broken(IngestJamendo):
        def search_tracks(self, **kwargs: object):  # noqa: ANN201
            raise JamendoError("request to https://api.jamendo.com/?client_id=TOPSECRET failed")

    broken = Broken(1)
    with make_client(tmp_path, jamendo=broken) as client:
        job_id = start_jamendo(client, embed=False)["id"]
        done = wait_done(client, job_id)
        assert done["status"] == "failed"
        assert done["error"] == "JamendoError: request to <url> failed"
        assert done["report"]["aborted"] is not None
        assert "TOPSECRET" not in client.get(f"/api/jobs/{job_id}/events").text + str(done)
        assert broken.closed


# -- without torch -------------------------------------------------------------------------------


def test_without_torch_the_tracks_are_analysed_and_a_warning_says_embedding_was_skipped(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path, jamendo=IngestJamendo(2), torch=False) as client:
        job_id = start_jamendo(client, limit=2)["id"]
        done = wait_done(client, job_id)
        assert done["status"] == "done" and done["report"]["processed"] == 2
        events = parse_sse(client.get(f"/api/jobs/{job_id}/events").text)
        warnings = [e["data"]["message"] for e in events if e["event"] == "warning"]
        assert len(warnings) == 1 and "embedding skipped" in warnings[0]
        new = client.repo.get_track_by_source("jamendo", "9001")
        assert new is not None
        assert client.repo.get_features(new.id) is not None
        assert client.repo.get_embedding(new.id, MODEL_ID) is None
        assert client.loader.keys == []


def test_embed_false_is_analysis_only_without_a_warning(tmp_path: Path) -> None:
    with make_client(tmp_path, jamendo=IngestJamendo(1)) as client:
        job_id = start_jamendo(client, limit=1, embed=False)["id"]
        assert wait_done(client, job_id)["status"] == "done"
        events = parse_sse(client.get(f"/api/jobs/{job_id}/events").text)
        assert not [e for e in events if e["event"] == "warning"]
        assert client.loader.keys == []


# -- local folders -------------------------------------------------------------------------------


def make_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "music"
    write_wav(folder / "a.wav", freq=330.0)
    write_wav(folder / "sub" / "b.wav", freq=550.0)
    return folder


def test_local_ingest_of_a_folder(tmp_path: Path) -> None:
    folder = make_folder(tmp_path)
    with make_client(tmp_path) as client:
        response = client.post(
            "/api/ingest/local", json={"path": str(folder), "license": "CC BY 4.0"}
        )
        assert response.status_code == 202, response.text
        job = response.json()["job"]
        assert job["kind"] == "ingest-local" and job["params"]["path"] == str(folder.resolve())
        done = wait_done(client, job["id"])
        assert done["status"] == "done"
        assert (done["report"]["new"], done["report"]["processed"]) == (2, 2)
        local, _ = client.repo.list_tracks(source="local")
        assert len(local) == 4  # the two of the synthetic catalog and the two new ones
        root = str(folder.resolve())
        added = [t for t in local if t.local_path and t.local_path.startswith(root)]
        assert len(added) == 2
        assert {t.license_code for t in added} == {"CC BY 4.0"}
        assert all(client.repo.get_embedding(t.id, MODEL_ID) is not None for t in added)
        # a second run finds everything up to date
        again = wait_done(
            client,
            client.post("/api/ingest/local", json={"path": str(folder)}).json()["job"]["id"],
        )
        assert (again["report"]["processed"], again["report"]["skipped"]) == (0, 2)


@pytest.mark.parametrize("bad", ["missing", "relative", "file", "license"])
def test_local_ingest_rejects_bad_input_with_422(tmp_path: Path, bad: str) -> None:
    folder = make_folder(tmp_path)
    body: dict[str, object] = {
        "missing": {"path": str(tmp_path / "nope")},
        "relative": {"path": "music"},
        "file": {"path": str(folder / "a.wav")},
        "license": {"path": str(folder), "license": "not a licence at all"},
    }[bad]
    with make_client(tmp_path) as client:
        response = client.post("/api/ingest/local", json=body)
        assert response.status_code == 422, response.text
        assert client.get("/api/jobs").json() == {"jobs": []}


# -- reprocess -----------------------------------------------------------------------------------


def test_reprocess_embed_adds_the_missing_embeddings_of_local_tracks(tmp_path: Path) -> None:
    folder = make_folder(tmp_path)
    with make_client(tmp_path) as client:
        body = {"path": str(folder), "embed": False}
        wait_done(client, client.post("/api/ingest/local", json=body).json()["job"]["id"])
        response = client.post("/api/ingest/reprocess", json={"what": "embed", "source": "local"})
        assert response.status_code == 202, response.text
        done = wait_done(client, response.json()["job"]["id"])
        assert done["status"] == "done" and done["report"]["processed"] == 2
        assert client.loader.keys == ["clap"] and not client.embedder.closed
        # 20 of the 21 synthetic tracks were embedded already, plus the two new local ones
        assert client.repo.stats()["embeddings_by_model"][MODEL_ID] == 22


def test_reprocess_embed_without_torch_or_client_id_is_503(tmp_path: Path) -> None:
    with make_client(tmp_path, torch=False) as client:
        response = client.post("/api/ingest/reprocess", json={"what": "embed"})
        assert response.status_code == 503 and "torch" in response.json()["detail"]
        assert client.get("/api/jobs").json() == {"jobs": []}
    with make_client(tmp_path / "b", jamendo=JamendoError("no id")) as client:
        response = client.post("/api/ingest/reprocess", json={"what": "embed"})
        assert response.status_code == 503
        assert response.json() == {"detail": "Jamendo client id is not set"}
        # local tracks need no client
        ok = client.post("/api/ingest/reprocess", json={"what": "embed", "source": "local"})
        assert ok.status_code == 202
        assert wait_done(client, ok.json()["job"]["id"])["status"] == "done"


def test_reprocess_tag_without_installed_models_finishes_with_a_warning(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post("/api/ingest/reprocess", json={"what": "tag"})
        assert response.status_code == 202
        job_id = response.json()["job"]["id"]
        done = wait_done(client, job_id)
        assert done["status"] == "done" and done["report"]["processed"] == 0
        events = parse_sse(client.get(f"/api/jobs/{job_id}/events").text)
        assert [e["event"] for e in events] == ["started", "warning", "done"]


def test_reprocess_tag_runs_the_tagging_stages_without_audio_or_a_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[int] = []

    class Stage:
        name = "tag:fake"
        version = "v1"
        needs_audio = False

        def is_current(self, repo: object, track_id: int) -> bool:
            return False

        def run(self, repo: object, track_id: int, audio: object) -> None:
            assert audio is None
            seen.append(track_id)

    module = types.ModuleType("mcrar.ml.tagging")
    module.tagging_stages = lambda settings: [Stage()]  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mcrar.ml.tagging", module)
    with make_client(tmp_path, jamendo=JamendoError("no id")) as client:
        response = client.post("/api/ingest/reprocess", json={"what": "tag", "source": "local"})
        done = wait_done(client, response.json()["job"]["id"])
        assert done["status"] == "done" and done["report"]["processed"] == 2
        assert len(seen) == 2


def test_reprocess_rejects_unknown_choices(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        for body in ({"what": "all"}, {"what": "tag", "source": "spotify"}, {}):
            assert client.post("/api/ingest/reprocess", json=body).status_code == 422


# -- jobs ----------------------------------------------------------------------------------------


def test_unknown_job_is_404(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert client.get("/api/jobs/nope").status_code == 404
        assert client.get("/api/jobs").json() == {"jobs": []}


def test_closing_the_app_cancels_a_running_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reached = threading.Event()
    holder: list[Job] = []

    def analyze(source: object, *, max_seconds: float | None = None):  # noqa: ANN202
        """Holds the first track until the job is told to cancel (what closing the app does)."""
        reached.set()
        deadline = time.monotonic() + 20
        while not (holder and holder[0].cancel_requested) and time.monotonic() < deadline:
            time.sleep(0.005)
        return fake_features(source)

    monkeypatch.setattr(pipeline, "analyze_audio", analyze)
    with make_client(tmp_path, jamendo=IngestJamendo(4)) as client:
        job_id = start_jamendo(client, limit=4, embed=False)["id"]
        holder.append(client.app.state.mcrar.jobs.get(job_id))
        assert reached.wait(20)
    job = holder[0]  # the app has closed: the job was cancelled and joined
    assert job.status == "cancelled" and job.report is not None
    assert job.report["processed"] == 1


def test_the_stream_sends_keepalives_while_idle_and_ends_with_the_final_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingest_routes, "POLL_S", 0.01)
    monkeypatch.setattr(ingest_routes, "KEEPALIVE_S", 0.03)
    job = Job("k", {})
    job.append("started", {})

    async def collect() -> list[str]:
        chunks: list[str] = []
        async for chunk in ingest_routes.stream_events(job, 0):
            chunks.append(chunk)
            if chunk.startswith(":"):
                job.finish("done", {"processed": 0})
        return chunks

    chunks = asyncio.run(asyncio.wait_for(collect(), 20))
    assert chunks[0].startswith("id: 1\nevent: started")
    assert chunks[1] == ": keepalive\n\n"
    assert chunks[-1].startswith("id: 2\nevent: done\ndata: ")
    assert len(chunks) == 3
