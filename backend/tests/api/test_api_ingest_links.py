"""POST /api/ingest/links: add tracks by Jamendo / Freesound link (fakes, no network, no torch)."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from api_support import ApiClient, IngestFreesound, IngestJamendo, make_client, wait_done
from recommend_support import MODEL_ID, fake_features

from mcrar.api.routes.ingest import NO_FREESOUND_MESSAGE, NO_JAMENDO_MESSAGE
from mcrar.catalog import TrackRecord
from mcrar.ingest import pipeline
from mcrar.sources import FreesoundAuthError, JamendoAuthError, JamendoError, SourceTrack

URL = "/api/ingest/links"


@pytest.fixture(autouse=True)
def fast_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "analyze_audio", fake_features)


class LinksJamendo(IngestJamendo):
    """Knows the tracks of ``known`` (source ids); ``get_tracks`` returns those asked for."""

    def __init__(self, known: Sequence[str] = ("101", "102")) -> None:
        super().__init__(0)
        self.known = set(known)
        self.lookups: list[list[str]] = []

    def get_tracks(self, ids: Sequence[str | int], **kwargs: Any) -> list[SourceTrack]:
        self.lookups.append([str(i) for i in ids])
        return [
            SourceTrack(
                source="jamendo",
                source_id=str(i),
                title=f"Linked Track {i}",
                artist="Linked Artist",
                stream_url=f"https://audio.example/{i}",
                license_url="https://creativecommons.org/licenses/by/4.0/",
            )
            for i in ids
            if str(i) in self.known
        ]


class LinksFreesound(IngestFreesound):
    def __init__(self, known: Sequence[str] = ("201",)) -> None:
        super().__init__(0)
        self.known = set(known)
        self.lookups: list[list[str]] = []

    def get_tracks(self, ids: Sequence[str | int], **kwargs: Any) -> list[SourceTrack]:
        self.lookups.append([str(i) for i in ids])
        return [
            SourceTrack(
                source="freesound",
                source_id=str(i),
                title=f"Linked Sound {i}",
                artist="linkeduser",
                stream_url=f"https://cdn.freesound.org/previews/{i}/p.mp3",
                license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                tags={"category": ["Music"]},
            )
            for i in ids
            if str(i) in self.known
        ]


def start(client: ApiClient, text: str, **body: object) -> dict[str, Any]:
    response = client.post(URL, json={"text": text, **body})
    assert response.status_code == 202, response.text
    return response.json()["job"]


def add_jamendo_track(client: ApiClient, source_id: str) -> int:
    return client.repo.upsert_track(
        TrackRecord(source="jamendo", source_id=source_id, title="Old Track", risk="green")
    )


MIXED = """
https://www.jamendo.com/track/101/some-slug
jamen.do/t/102, https://www.jamendo.com/track/999
https://freesound.org/people/someone/sounds/201/
freesound:202
not a link
"""


def test_mixed_links_add_the_tracks_and_report_already_missing_and_invalid(
    tmp_path: Path,
) -> None:
    jamendo, freesound = LinksJamendo(), LinksFreesound()
    with make_client(tmp_path, jamendo=jamendo, freesound=freesound) as client:
        old = add_jamendo_track(client, "102")
        job = start(client, MIXED)
        assert job["kind"] == "ingest-links"
        assert job["params"] == {"jamendo": 3, "freesound": 2}
        done = wait_done(client, job["id"])
        assert done["status"] == "done" and done["error"] is None
        report = done["report"]
        assert report["already"] == ["jamendo:102"]
        assert report["not_found"] == ["jamendo:999", "freesound:202"]
        assert report["invalid"] == ["not", "a", "link"]
        assert (report["seen"], report["new"], report["updated"], report["failed"]) == (3, 2, 1, 0)
        new_jamendo = client.repo.get_track_by_source("jamendo", "101")
        new_freesound = client.repo.get_track_by_source("freesound", "201")
        assert new_jamendo is not None and new_jamendo.title == "Linked Track 101"
        assert new_freesound is not None and new_freesound.license_family == "cc0"
        assert report["new_track_ids"] == [new_jamendo.id, new_freesound.id]
        assert old not in report["new_track_ids"]
        assert client.repo.get_track_by_source("jamendo", "102").title == "Linked Track 102"
        assert all(
            client.repo.get_embedding(t, MODEL_ID) is not None
            for t in (new_jamendo.id, new_freesound.id)
        )
        assert client.repo.get_track_by_source("jamendo", "999") is None
        assert jamendo.lookups == [["101", "102", "999"]]
        assert freesound.lookups == [["201", "202"]]
        assert jamendo.closed and freesound.closed


def test_progress_is_one_bar_over_both_sources(tmp_path: Path) -> None:
    from api_support import parse_sse

    with make_client(tmp_path, jamendo=LinksJamendo(), freesound=LinksFreesound()) as client:
        job = start(client, "jamendo:101 jamendo:102 freesound:201")
        wait_done(client, job["id"])
        events = parse_sse(client.get(f"/api/jobs/{job['id']}/events").text)
        progress = [e["data"] for e in events if e["event"] == "progress"]
        assert {p["total"] for p in progress} == {3}
        assert [p["index"] for p in progress if p["kind"] == "track_done"] == [1, 2, 3]
        titles = [p["title"] for p in progress if p["kind"] == "track_done"]
        assert [t.split()[1] for t in titles] == ["Track", "Track", "Sound"]


def test_only_the_sources_with_links_are_opened(tmp_path: Path) -> None:
    jamendo = LinksJamendo()
    with make_client(tmp_path, jamendo=jamendo) as client:  # no Freesound key
        report = wait_done(client, start(client, "jamendo:101")["id"])["report"]
        assert report["new"] == 1 and report["already"] == [] and report["not_found"] == []
    freesound = LinksFreesound()
    with make_client(tmp_path / "b", jamendo=JamendoError("no id"), freesound=freesound) as client:
        report = wait_done(client, start(client, "freesound:201")["id"])["report"]
        assert report["new"] == 1
        assert freesound.closed


def test_embed_false_skips_embedding(tmp_path: Path) -> None:
    with make_client(tmp_path, jamendo=LinksJamendo()) as client:
        job = start(client, "jamendo:101", embed=False)
        assert wait_done(client, job["id"])["report"]["processed"] == 1
        track = client.repo.get_track_by_source("jamendo", "101")
        assert track is not None and client.repo.get_features(track.id) is not None
        assert client.repo.get_embedding(track.id, MODEL_ID) is None
        assert client.loader.keys == []


def test_an_existing_track_is_skipped_by_the_stages_unless_forced(tmp_path: Path) -> None:
    with make_client(tmp_path, jamendo=LinksJamendo()) as client:
        wait_done(client, start(client, "jamendo:101")["id"])
        second = wait_done(client, start(client, "jamendo:101")["id"])["report"]
        assert second["already"] == ["jamendo:101"] and second["new"] == 0
        assert second["skipped"] == 1 and second["not_found"] == []
        forced = wait_done(client, start(client, "jamendo:101", force=True)["id"])["report"]
        assert forced["already"] == ["jamendo:101"] and forced["processed"] == 1


def test_nothing_valid_is_422_and_lists_some_of_the_junk(tmp_path: Path) -> None:
    with make_client(tmp_path, jamendo=LinksJamendo(), freesound=LinksFreesound()) as client:
        junk = "one two three four https://example.com/track/1"
        response = client.post(URL, json={"text": junk})
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "no Jamendo or Freesound track link" in detail
        assert "one, two, three and 2 more" in detail
        assert client.get("/api/jobs").json() == {"jobs": []}
        blank = client.post(URL, json={"text": " \n , "})
        assert blank.status_code == 422 and "not recognised" not in blank.json()["detail"]


def test_more_than_fifty_ids_is_422(tmp_path: Path) -> None:
    with make_client(tmp_path, jamendo=LinksJamendo()) as client:
        text = " ".join(f"jamendo:{n}" for n in range(51))
        response = client.post(URL, json={"text": text})
        assert response.status_code == 422 and "at most 50" in response.json()["detail"]
        assert client.get("/api/jobs").json() == {"jobs": []}


@pytest.mark.parametrize(
    "body",
    [{}, {"text": ""}, {"text": "x" * 10001}, {"text": "jamendo:1", "unknown": 1}],
)
def test_a_bad_body_is_422(tmp_path: Path, body: dict) -> None:
    with make_client(tmp_path, jamendo=LinksJamendo()) as client:
        assert client.post(URL, json=body).status_code == 422
        assert client.get("/api/jobs").json() == {"jobs": []}


def test_a_link_for_a_source_without_its_key_is_503_and_closes_what_was_opened(
    tmp_path: Path,
) -> None:
    jamendo = LinksJamendo()
    with make_client(tmp_path, jamendo=jamendo) as client:  # no Freesound key
        response = client.post(URL, json={"text": "jamendo:101 freesound:201"})
        assert response.status_code == 503
        assert response.json() == {"detail": NO_FREESOUND_MESSAGE}
        assert jamendo.closed  # opened first, closed again
        assert client.get("/api/jobs").json() == {"jobs": []}
        assert client.repo.get_track_by_source("jamendo", "101") is None
    with make_client(
        tmp_path / "b", jamendo=JamendoError("no id"), freesound=LinksFreesound()
    ) as c:
        response = c.post(URL, json={"text": "jamendo:101"})
        assert response.status_code == 503 and response.json() == {"detail": NO_JAMENDO_MESSAGE}


def test_a_second_job_while_one_runs_is_409_and_closes_its_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reached, go = threading.Event(), threading.Event()

    def gate(source: object, *, max_seconds: float | None = None):  # noqa: ANN202
        reached.set()
        assert go.wait(20), "the test never opened the gate"
        return fake_features(source)

    monkeypatch.setattr(pipeline, "analyze_audio", gate)
    jamendo = LinksJamendo()
    with make_client(tmp_path, jamendo=jamendo) as client:
        first = start(client, "jamendo:101")["id"]
        try:
            assert reached.wait(20)
            assert jamendo.closed is False  # the running job holds the (shared fake) client
            busy = client.post(URL, json={"text": "jamendo:102"})
            assert busy.status_code == 409 and first in busy.json()["detail"]
            assert jamendo.closed  # the refused request closed its own client
        finally:
            go.set()
        assert wait_done(client, first)["status"] == "done"


def test_a_failing_source_only_warns_and_the_other_one_runs(tmp_path: Path) -> None:
    from api_support import parse_sse

    class BrokenJamendo(LinksJamendo):
        def get_tracks(self, ids, **kwargs):  # noqa: ANN001, ANN003, ANN201
            raise JamendoAuthError("bad key")

    with make_client(tmp_path, jamendo=BrokenJamendo(), freesound=LinksFreesound()) as client:
        job = start(client, "jamendo:101 freesound:201")
        done = wait_done(client, job["id"])
        assert done["status"] == "done" and done["error"] is None
        report = done["report"]
        assert report["new"] == 1 and report["not_found"] == ["jamendo:101"]
        events = parse_sse(client.get(f"/api/jobs/{job['id']}/events").text)
        warnings = [e["data"]["message"] for e in events if e["event"] == "warning"]
        assert len(warnings) == 1 and warnings[0].startswith("Jamendo failed:")


def test_every_source_failing_fails_the_job(tmp_path: Path) -> None:
    class BrokenJamendo(LinksJamendo):
        def get_tracks(self, ids, **kwargs):  # noqa: ANN001, ANN003, ANN201
            raise JamendoAuthError("bad key")

    class BrokenFreesound(LinksFreesound):
        def get_tracks(self, ids, **kwargs):  # noqa: ANN001, ANN003, ANN201
            raise FreesoundAuthError("bad key")

    jamendo, freesound = BrokenJamendo(), BrokenFreesound()
    with make_client(tmp_path, jamendo=jamendo, freesound=freesound) as client:
        job = start(client, "jamendo:101 freesound:201")
        done = wait_done(client, job["id"])
        assert done["status"] == "failed" and "FreesoundAuthError" in done["error"]
        assert jamendo.closed and freesound.closed


def test_cancelling_ends_cancelled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reached, go = threading.Event(), threading.Event()

    def gate(source: object, *, max_seconds: float | None = None):  # noqa: ANN202
        reached.set()
        assert go.wait(20), "the test never opened the gate"
        return fake_features(source)

    monkeypatch.setattr(pipeline, "analyze_audio", gate)
    with make_client(tmp_path, jamendo=LinksJamendo(), freesound=LinksFreesound()) as client:
        job_id = start(client, "jamendo:101 jamendo:102 freesound:201")["id"]
        try:
            assert reached.wait(20)
            assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 202
        finally:
            go.set()
        done = wait_done(client, job_id)
        assert done["status"] == "cancelled" and done["report"]["aborted"] == "cancelled"
        assert client.repo.get_track_by_source("freesound", "201") is None  # never started


def test_the_links_report_serialises_its_extra_fields() -> None:
    from mcrar.api.jobs import report_to_dict
    from mcrar.ingest import LinksReport, combine_reports

    report = LinksReport(1, 1, 0, 1, 0, 0, [], 0.5, already=["jamendo:1"], invalid=["x"])
    data = report_to_dict(report)
    assert data["already"] == ["jamendo:1"] and data["not_found"] == [] and data["invalid"] == ["x"]
    assert data["failures_total"] == 0
    assert combine_reports([report, report]).new == 2
