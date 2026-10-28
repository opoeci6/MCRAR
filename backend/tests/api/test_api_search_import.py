"""POST /api/search/import: a Jamendo import for a text search (fakes, no network, no torch)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from api_support import IngestFreesound, IngestJamendo, make_client, parse_sse, wait_done
from recommend_support import MODEL_ID, fake_features

from mcrar.api.routes.ingest import (
    IMPORT_NO_REMOTE_SOURCE_MESSAGE,
    NO_FREESOUND_MESSAGE,
    NO_IMPORT_SOURCE_MESSAGE,
)
from mcrar.ingest import pipeline
from mcrar.sources import FreesoundAuthError, JamendoAuthError, JamendoError

URL = "/api/search/import"


@pytest.fixture(autouse=True)
def fast_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "analyze_audio", fake_features)


class Gate:
    """An analyser that stops inside the first track until the test lets it go."""

    def __init__(self, at: int = 1) -> None:
        self.reached = threading.Event()
        self.go = threading.Event()
        self.calls = 0
        self.at = at  # the call (1 = the first track) that waits

    def __call__(self, source: object, *, max_seconds: float | None = None):  # noqa: ANN204
        self.calls += 1
        if self.calls == self.at:
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
            "sources": ["jamendo"],  # the only one with a secret
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
        assert response.json() == {"detail": "describe the music to search for"}
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
        assert response.json() == {"detail": NO_IMPORT_SOURCE_MESSAGE}  # no source at all
        assert client.get("/api/jobs").json() == {"jobs": []}
        named = client.post(URL, json={"text": "calm", "sources": ["jamendo"]})
        assert named.status_code == 503
        assert named.json() == {"detail": "Jamendo client id is not set"}


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


# -- Jamendo and Freesound ---------------------------------------------------------------------


def _new(client, source: str, first: int, count: int) -> list:  # noqa: ANN001
    found = [client.repo.get_track_by_source(source, str(first + n)) for n in range(count)]
    assert all(t is not None for t in found)
    return found


def test_both_sources_split_the_limit_and_run_in_sequence(tmp_path: Path) -> None:
    jamendo, freesound = IngestJamendo(30), IngestFreesound(30)
    with make_client(tmp_path, jamendo=jamendo, freesound=freesound) as client:
        response = client.post(URL, json={"text": "tense stealth level", "limit": 11})
        assert response.status_code == 202, response.text
        job = response.json()["job"]
        assert job["params"]["sources"] == ["jamendo", "freesound"]
        assert "key" not in str(job["params"]).lower()
        done = wait_done(client, job["id"])
        assert done["status"] == "done" and done["error"] is None
        report = done["report"]
        assert (report["seen"], report["new"], report["processed"], report["failed"]) == (
            11,
            11,
            11,
            0,
        )
        # Jamendo takes ceil(11 / 2) = 6, Freesound what is left: 5.
        from_jamendo = _new(client, "jamendo", 9001, 6)
        from_freesound = _new(client, "freesound", 7001, 5)
        assert client.repo.get_track_by_source("jamendo", "9007") is None
        assert client.repo.get_track_by_source("freesound", "7006") is None
        assert report["new_track_ids"] == [t.id for t in from_jamendo + from_freesound]
        assert all(
            client.repo.get_embedding(t.id, MODEL_ID) is not None
            for t in from_jamendo + from_freesound
        )
        assert jamendo.closed and freesound.closed
        events = parse_sse(client.get(f"/api/jobs/{job['id']}/events").text)
        assert events[-1]["event"] == "done"
        assert events[-1]["data"]["report"]["new_track_ids"] == report["new_track_ids"]
        progress = [e["data"] for e in events if e["event"] == "progress"]
        assert {p["total"] for p in progress} == {11}  # one bar over the whole job
        done_indexes = [p["index"] for p in progress if p["kind"] == "track_done"]
        assert done_indexes == list(range(1, 12))
        # Jamendo's tracks all come before Freesound's.
        titles = [p["title"] for p in progress if p["kind"] == "track_done"]
        assert [t.split()[1] for t in titles] == ["Track"] * 6 + ["Sound"] * 5
        assert len(jamendo.queries) == 1 and len(freesound.queries) == 1


def test_a_source_that_finds_less_than_its_share_leaves_the_rest_to_the_next(
    tmp_path: Path,
) -> None:
    jamendo, freesound = IngestJamendo(2), IngestFreesound(30)
    with make_client(tmp_path, jamendo=jamendo, freesound=freesound) as client:
        job = client.post(URL, json={"text": "tense stealth level", "limit": 10}).json()["job"]
        report = wait_done(client, job["id"])["report"]
        assert report["new"] == 10  # 2 from Jamendo (share 5), 8 from Freesound
        assert len(report["new_track_ids"]) == 10
        _new(client, "jamendo", 9001, 2)
        _new(client, "freesound", 7001, 8)
        assert client.repo.get_track_by_source("freesound", "7009") is None


def test_the_second_source_is_skipped_when_the_first_filled_the_limit(tmp_path: Path) -> None:
    jamendo, freesound = IngestJamendo(30), IngestFreesound(30)
    with make_client(tmp_path, jamendo=jamendo, freesound=freesound) as client:
        job = client.post(URL, json={"text": "calm", "limit": 1}).json()["job"]
        report = wait_done(client, job["id"])["report"]
        assert report["new"] == 1  # Jamendo's share of 1 is 1, nothing is left for Freesound
        assert freesound.queries == []
        assert freesound.closed  # still closed


def test_only_freesound_when_it_is_the_only_source_with_a_secret(tmp_path: Path) -> None:
    freesound = IngestFreesound(5)
    with make_client(tmp_path, jamendo=JamendoError("no id"), freesound=freesound) as client:
        job = client.post(URL, json={"text": "tense stealth level", "limit": 3}).json()["job"]
        assert job["params"]["sources"] == ["freesound"]
        report = wait_done(client, job["id"])["report"]
        assert report["new"] == 3  # the whole limit
        _new(client, "freesound", 7001, 3)
        assert freesound.queries == [
            {
                "query": "tense stealth level",
                "licenses": ["cc0", "by"],
                "duration_min_s": 10.0,
                "duration_max_s": 600.0,
                "music_like": True,
                "sort": "score",
                "limit": 150,
            }
        ]


def test_the_freesound_queries_follow_the_search_filters(tmp_path: Path) -> None:
    freesound = IngestFreesound(1)
    filters = {"max_risk": "red", "duration_min_s": 30, "duration_max_s": 90, "vocal": "vocal"}
    with make_client(tmp_path, jamendo=JamendoError("no id"), freesound=freesound) as client:
        body = {"text": "lo-fi dark cave", "filters": filters, "limit": 5}
        wait_done(client, client.post(URL, json=body).json()["job"]["id"])
        # One sound exists, so every query runs; the text is searched once.
        assert [q["query"] for q in freesound.queries] == ["lo-fi dark cave"]
        query = freesound.queries[0]
        assert query["licenses"] == ["cc0", "by", "by-nc"]
        assert (query["duration_min_s"], query["duration_max_s"]) == (30.0, 90.0)


def test_explicit_sources_use_exactly_those(tmp_path: Path) -> None:
    jamendo, freesound = IngestJamendo(5), IngestFreesound(5)
    with make_client(tmp_path, jamendo=jamendo, freesound=freesound) as client:
        body = {"text": "calm", "limit": 4, "sources": ["freesound"]}
        job = client.post(URL, json=body).json()["job"]
        assert job["params"]["sources"] == ["freesound"]
        assert wait_done(client, job["id"])["report"]["new"] == 4
        assert jamendo.queries == []
        assert len(freesound.queries) == 1


def test_the_source_filter_limits_the_import_to_the_remote_sources_in_it(tmp_path: Path) -> None:
    jamendo, freesound = IngestJamendo(5), IngestFreesound(5)
    with make_client(tmp_path, jamendo=jamendo, freesound=freesound) as client:
        body = {"text": "calm", "limit": 4, "filters": {"sources": ["freesound", "local"]}}
        job = client.post(URL, json=body).json()["job"]
        assert job["params"]["sources"] == ["freesound"]
        assert wait_done(client, job["id"])["report"]["new"] == 4  # the whole limit
        assert jamendo.queries == [] and len(freesound.queries) == 1
        assert not jamendo.closed  # never even opened


def test_the_source_filter_keeps_only_the_sources_that_have_a_secret(tmp_path: Path) -> None:
    freesound = IngestFreesound(5)
    with make_client(tmp_path, jamendo=JamendoError("no id"), freesound=freesound) as client:
        body = {"text": "calm", "limit": 2, "filters": {"sources": ["jamendo", "freesound"]}}
        job = client.post(URL, json=body).json()["job"]
        assert job["params"]["sources"] == ["freesound"]
        assert wait_done(client, job["id"])["report"]["new"] == 2


def test_a_source_filter_naming_only_a_source_without_a_secret_is_503(tmp_path: Path) -> None:
    with make_client(tmp_path, jamendo=IngestJamendo(5)) as client:  # no Freesound key
        body = {"text": "calm", "filters": {"sources": ["freesound"]}}
        response = client.post(URL, json=body)
        assert response.status_code == 503
        assert response.json() == {"detail": NO_FREESOUND_MESSAGE}
        assert client.get("/api/jobs").json() == {"jobs": []}


def test_a_source_filter_without_a_remote_source_is_422(tmp_path: Path) -> None:
    jamendo = IngestJamendo(5)
    with make_client(tmp_path, jamendo=jamendo, freesound=IngestFreesound(5)) as client:
        body = {"text": "calm", "filters": {"sources": ["local"]}}
        response = client.post(URL, json=body)
        assert response.status_code == 422
        assert response.json() == {"detail": IMPORT_NO_REMOTE_SOURCE_MESSAGE}
        assert client.get("/api/jobs").json() == {"jobs": []}
        assert jamendo.queries == []


def test_explicit_sources_outside_the_source_filter_are_422(tmp_path: Path) -> None:
    with make_client(tmp_path, jamendo=IngestJamendo(5), freesound=IngestFreesound(5)) as client:
        body = {
            "text": "calm",
            "sources": ["jamendo", "freesound"],
            "filters": {"sources": ["freesound"]},
        }
        response = client.post(URL, json=body)
        assert response.status_code == 422 and "jamendo" in response.json()["detail"]
        assert client.get("/api/jobs").json() == {"jobs": []}
        inside = {**body, "sources": ["freesound"]}
        assert client.post(URL, json=inside).status_code == 202


def test_an_explicit_source_without_its_secret_is_503_and_nothing_stays_open(
    tmp_path: Path,
) -> None:
    jamendo = IngestJamendo(5)
    with make_client(tmp_path, jamendo=jamendo) as client:  # no Freesound key
        only = client.post(URL, json={"text": "calm", "sources": ["freesound"]})
        assert only.status_code == 503
        assert only.json() == {"detail": NO_FREESOUND_MESSAGE}
        both = client.post(URL, json={"text": "calm", "sources": ["jamendo", "freesound"]})
        assert both.status_code == 503
        assert both.json() == {"detail": NO_FREESOUND_MESSAGE}
        assert jamendo.closed  # opened first, closed again
        assert client.get("/api/jobs").json() == {"jobs": []}
        assert jamendo.queries == []


def test_no_source_with_a_secret_is_503_naming_both(tmp_path: Path) -> None:
    with make_client(tmp_path, jamendo=JamendoError("no id")) as client:
        response = client.post(URL, json={"text": "calm"})
        assert response.status_code == 503
        detail = response.json()["detail"]
        assert "Jamendo" in detail and "Freesound" in detail
        assert client.get("/api/jobs").json() == {"jobs": []}


@pytest.mark.parametrize("sources", [[], ["spotify"], ["jamendo", "jamendo", "freesound"]])
def test_a_bad_sources_list_is_422(tmp_path: Path, sources: list) -> None:
    with make_client(tmp_path, jamendo=IngestJamendo(1)) as client:
        assert client.post(URL, json={"text": "calm", "sources": sources}).status_code == 422


def test_the_usable_sources_are_listed_without_secrets(tmp_path: Path) -> None:
    url = "/api/search/import/sources"
    cases = [
        (IngestJamendo(1), IngestFreesound(1), ["jamendo", "freesound"]),
        (IngestJamendo(1), None, ["jamendo"]),
        (JamendoError("no id"), IngestFreesound(1), ["freesound"]),
        (JamendoError("no id"), None, []),
    ]
    for jamendo, freesound, expected in cases:
        with make_client(tmp_path, jamendo=jamendo, freesound=freesound) as client:
            assert client.get(url).json() == {"sources": expected}


class BrokenJamendo(IngestJamendo):
    def search_tracks(self, **kwargs):  # noqa: ANN003, ANN201
        raise JamendoAuthError("bad key")


class BrokenFreesound(IngestFreesound):
    def search_tracks(self, **kwargs):  # noqa: ANN003, ANN201
        raise FreesoundAuthError("bad key")


def _warnings(client, job_id: str) -> list[str]:  # noqa: ANN001
    events = parse_sse(client.get(f"/api/jobs/{job_id}/events").text)
    return [e["data"]["message"] for e in events if e["event"] == "warning"]


def test_a_failing_first_source_only_warns_and_the_next_gets_the_whole_budget(
    tmp_path: Path,
) -> None:
    jamendo, freesound = BrokenJamendo(5), IngestFreesound(30)
    with make_client(tmp_path, jamendo=jamendo, freesound=freesound) as client:
        job = client.post(URL, json={"text": "calm", "limit": 6}).json()["job"]
        done = wait_done(client, job["id"])
        assert done["status"] == "done" and done["error"] is None
        report = done["report"]
        assert report["new"] == 6  # Jamendo's share was 3; Freesound got all 6
        found = _new(client, "freesound", 7001, 6)
        assert report["new_track_ids"] == [t.id for t in found]
        warnings = _warnings(client, job["id"])
        assert len(warnings) == 1 and warnings[0].startswith("Jamendo failed:")
        assert jamendo.closed and freesound.closed


def test_a_failing_second_source_only_warns_and_keeps_the_first_ones_tracks(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path, jamendo=IngestJamendo(2), freesound=BrokenFreesound(1)) as client:
        job = client.post(URL, json={"text": "calm", "limit": 6}).json()["job"]
        done = wait_done(client, job["id"])
        assert done["status"] == "done" and done["error"] is None
        assert done["report"]["new"] == 2  # Jamendo's tracks are in the report
        found = _new(client, "jamendo", 9001, 2)
        assert done["report"]["new_track_ids"] == [t.id for t in found]
        warnings = _warnings(client, job["id"])
        assert len(warnings) == 1 and warnings[0].startswith("Freesound failed:")


def test_every_source_failing_fails_the_job_with_the_last_error(tmp_path: Path) -> None:
    with make_client(tmp_path, jamendo=BrokenJamendo(1), freesound=BrokenFreesound(1)) as client:
        job = client.post(URL, json={"text": "calm", "limit": 6}).json()["job"]
        done = wait_done(client, job["id"])
        assert done["status"] == "failed" and "FreesoundAuthError" in done["error"]
        assert len(_warnings(client, job["id"])) == 2


def test_a_source_failing_after_adding_tracks_keeps_them_in_the_failed_report(
    tmp_path: Path,
) -> None:
    class HalfBrokenJamendo(IngestJamendo):
        def search_tracks(self, **kwargs):  # noqa: ANN003, ANN201
            found = super().search_tracks(**kwargs)

            def tracks():  # noqa: ANN202
                yield from found
                raise JamendoAuthError("bad key")

            return tracks()

    with make_client(
        tmp_path, jamendo=HalfBrokenJamendo(2), freesound=BrokenFreesound(1)
    ) as client:
        job = client.post(URL, json={"text": "calm", "limit": 6}).json()["job"]
        done = wait_done(client, job["id"])
        assert done["status"] == "failed"
        assert done["report"]["new"] == 2  # what Jamendo added before it failed


def test_a_source_failing_midway_does_not_mark_a_done_job_aborted(tmp_path: Path) -> None:
    class HalfBrokenJamendo(IngestJamendo):
        def search_tracks(self, **kwargs):  # noqa: ANN003, ANN201
            found = super().search_tracks(**kwargs)

            def tracks():  # noqa: ANN202
                yield from found
                raise JamendoAuthError("bad key")

            return tracks()

    with make_client(
        tmp_path, jamendo=HalfBrokenJamendo(2), freesound=IngestFreesound(30)
    ) as client:
        job = client.post(URL, json={"text": "calm", "limit": 6}).json()["job"]
        done = wait_done(client, job["id"])
        assert done["status"] == "done" and done["report"]["aborted"] is None
        assert done["report"]["new"] == 6  # Jamendo's 2, then Freesound's 4
        assert _warnings(client, job["id"])[0].startswith("Jamendo failed:")


def test_cancelling_during_the_second_source_keeps_both_sources_tracks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = Gate(at=2)  # the first Freesound track (Jamendo has just one)
    monkeypatch.setattr(pipeline, "analyze_audio", gate)
    jamendo, freesound = IngestJamendo(1), IngestFreesound(5)
    with make_client(tmp_path, jamendo=jamendo, freesound=freesound) as client:
        job_id = client.post(URL, json={"text": "calm", "limit": 6}).json()["job"]["id"]
        try:
            assert gate.reached.wait(20)
            assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 202
        finally:
            gate.go.set()
        done = wait_done(client, job_id)
        assert done["status"] == "cancelled"
        assert done["report"]["aborted"] == "cancelled"
        ids = done["report"]["new_track_ids"]
        jamendo_track = client.repo.get_track_by_source("jamendo", "9001")
        assert jamendo_track is not None and ids[0] == jamendo_track.id
        assert 2 <= len(ids) <= 6
        assert jamendo.closed and freesound.closed


def test_cancelling_during_the_first_source_never_starts_the_second(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = Gate()
    monkeypatch.setattr(pipeline, "analyze_audio", gate)
    freesound = IngestFreesound(5)
    with make_client(tmp_path, jamendo=IngestJamendo(5), freesound=freesound) as client:
        job_id = client.post(URL, json={"text": "calm", "limit": 6}).json()["job"]["id"]
        try:
            assert gate.reached.wait(20)
            client.post(f"/api/jobs/{job_id}/cancel")
        finally:
            gate.go.set()
        assert wait_done(client, job_id)["status"] == "cancelled"
        assert freesound.queries == []


def test_the_report_lists_at_most_200_new_track_ids() -> None:
    from mcrar.api.jobs import MAX_NEW_TRACK_IDS, report_to_dict
    from mcrar.ingest import IngestReport

    report = IngestReport(300, 300, 0, 300, 0, 0, [], 1.0, new_track_ids=list(range(300)))
    assert report_to_dict(report)["new_track_ids"] == list(range(MAX_NEW_TRACK_IDS))
    assert MAX_NEW_TRACK_IDS == 200
    assert report_to_dict(IngestReport(0, 0, 0, 0, 0, 0, [], 0.0))["new_track_ids"] == []
