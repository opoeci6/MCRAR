"""Track list and detail, the audio stream (redirect or local file with Range) and credits."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from api_support import FakeStreamJamendo, make_client, register_tagging
from recommend_support import write_wav

from mcrar.catalog import TrackRecord
from mcrar.sources import JamendoAuthError, JamendoError, JamendoRateLimitError

STREAM = "https://prod-1.storage.jamendo.com/?trackid=1&format=mp31&from=abc"


# -- list and detail --------------------------------------------------------------------------


def test_list_pages_and_filters(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        first = client.get("/api/tracks", params={"limit": 5}).json()
        assert first["total"] == 21 and len(first["items"]) == 5
        assert first["items"][0] == {
            "id": client.ids["Shadow Walk"],
            "title": "Shadow Walk",
            "artist": "Ada",
            "source": "jamendo",
            "duration_s": 120.0,
            "risk": "green",
            "license_code": "CC BY 3.0",
        }
        second = client.get("/api/tracks", params={"limit": 5, "offset": 5}).json()
        ids = [t["id"] for t in first["items"] + second["items"]]
        assert ids == sorted(set(ids)) and len(ids) == 10
        local = client.get("/api/tracks", params={"source": "local"}).json()
        assert local["total"] == 2 and {t["source"] for t in local["items"]} == {"local"}
        red = client.get("/api/tracks", params={"risk": "red"}).json()
        assert {t["title"] for t in red["items"]} == {"Red Alert", "Metal Gods"}
        tail = client.get("/api/tracks", params={"offset": 20, "limit": 50}).json()
        assert len(tail["items"]) == 1 and tail["total"] == 21


def test_list_rejects_bad_arguments(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert client.get("/api/tracks", params={"source": "spotify"}).status_code == 422
        assert client.get("/api/tracks", params={"risk": "purple"}).status_code == 422
        assert client.get("/api/tracks", params={"limit": 0}).status_code == 422
        assert client.get("/api/tracks", params={"limit": 201}).status_code == 422
        assert client.get("/api/tracks", params={"offset": -1}).status_code == 422


def _titles(client, **params) -> tuple[set[str], int]:  # noqa: ANN001, ANN003
    body = client.get("/api/tracks", params={"limit": 200, **params}).json()
    return {t["title"] for t in body["items"]}, body["total"]


def _add_text_tracks(client) -> None:  # noqa: ANN001
    for source_id, title, artist, album in (
        ("t1", "Zebra Crossing", "Quiet Fox", "Night Drive"),
        ("t2", "Plain", "Zebra Quartet", None),
        ("t3", "100% Pure", "Fox", "Snake_Case"),
        ("t4", "Other", None, "Zebra Songs"),
        ("t5", "Étude", "Anon", None),
    ):
        client.repo.upsert_track(
            TrackRecord(
                source="local", source_id=source_id, title=title, artist=artist, album=album
            )
        )


def test_list_text_filter_matches_title_artist_or_album_case_insensitively(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        _add_text_tracks(client)
        assert _titles(client, q="zebra") == ({"Zebra Crossing", "Plain", "Other"}, 3)
        assert _titles(client, q="ZEBRA") == _titles(client, q="zebra")
        assert _titles(client, q="quartet") == ({"Plain"}, 1)  # artist
        assert _titles(client, q="drive") == ({"Zebra Crossing"}, 1)  # album
        assert _titles(client, q="plain") == ({"Plain"}, 1)  # title
        assert _titles(client, q="Étude") == ({"Étude"}, 1)  # non-ASCII: matched as written
        assert _titles(client, q="tude") == ({"Étude"}, 1)


def test_list_text_filter_needs_every_word_and_keeps_total_in_step(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        _add_text_tracks(client)
        assert _titles(client, q="zebra fox") == ({"Zebra Crossing"}, 1)  # title + artist
        assert _titles(client, q="  fox   zebra ") == ({"Zebra Crossing"}, 1)
        assert _titles(client, q="zebra nothing") == (set(), 0)
        page = client.get("/api/tracks", params={"q": "zebra", "limit": 1, "offset": 1}).json()
        assert page["total"] == 3 and len(page["items"]) == 1
        only_local = client.get("/api/tracks", params={"q": "zebra", "source": "jamendo"}).json()
        assert only_local["total"] == 0  # combines with the other filters


def test_list_text_filter_treats_like_wildcards_literally(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        _add_text_tracks(client)
        assert _titles(client, q="%") == ({"100% Pure"}, 1)
        assert _titles(client, q="_") == ({"100% Pure"}, 1)  # the album "Snake_Case"
        assert _titles(client, q="e_c") == ({"100% Pure"}, 1)  # not "any one character"
        assert _titles(client, q="\\") == (set(), 0)


def test_list_empty_text_filter_is_no_filter_and_too_long_is_422(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        _add_text_tracks(client)
        everything = client.get("/api/tracks").json()["total"]
        assert everything == 26
        for blank in ("", "   "):
            assert client.get("/api/tracks", params={"q": blank}).json()["total"] == everything
        assert client.get("/api/tracks", params={"q": "a" * 200}).status_code == 200
        assert client.get("/api/tracks", params={"q": "a" * 201}).status_code == 422


def test_detail_has_features_licence_and_a_download_url_only_when_allowed(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        quest = client.get(f"/api/tracks/{client.ids['Epic Quest']}").json()
        assert quest["title"] == "Epic Quest" and quest["source"] == "jamendo"
        assert quest["download_url"] == "https://example.test/10/download"
        assert quest["features"]["bpm"] == 110.0 and quest["features"]["key"] == "C"
        assert quest["license"]["code"] == "CC BY 3.0" and quest["license"]["risk"] == "green"
        assert quest["license"]["attribution_text"] == "Epic Quest by Gus"
        assert quest["stream_url"] == f"/api/tracks/{quest['id']}/stream"
        assert quest["local_path"] is None
        boss = client.get(f"/api/tracks/{client.ids['Boss Fight']}").json()
        assert boss["download_url"] is None


def test_detail_shows_the_local_path_only_for_local_tracks(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        wav = write_wav(tmp_path / "audio" / "a.wav")
        local_id = client.repo.upsert_track(
            TrackRecord(source="local", source_id="a.wav", title="A", local_path=str(wav))
        )
        assert client.get(f"/api/tracks/{local_id}").json()["local_path"] == str(wav)
        jamendo_id = client.ids["Shadow Walk"]
        client.repo.upsert_track(
            TrackRecord(source="jamendo", source_id="1", title="Shadow Walk", local_path="/x/y")
        )
        assert client.get(f"/api/tracks/{jamendo_id}").json()["local_path"] is None


def test_detail_unknown_id_is_404_and_a_bad_id_is_422(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert client.get("/api/tracks/9999").status_code == 404
        assert client.get("/api/tracks/abc").status_code == 422


@pytest.mark.parametrize("entry_commercial", [True, False])
def test_detail_shows_the_tags_of_the_selected_version_whatever_its_licence(
    tmp_path: Path, entry_commercial: bool
) -> None:
    client = make_client(tmp_path)
    registry = register_tagging(client.settings, commercial=entry_commercial)
    version = registry["label_sets"]["genre"]["entries"][0]["id"]
    with client:
        track = client.ids["Shadow Walk"]
        client.repo.set_tag_probs(track, "genre", "head", version, {"a": 0.7, "b": 0.2})
        tags = client.get(f"/api/tracks/{track}").json()["tags"]
        assert [(t["label_set"], t["label"], t["prob"]) for t in tags] == [
            ("genre", "a", 0.7),
            ("genre", "b", 0.2),
        ]


def test_with_no_registry_no_stored_tags_are_shown(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        track = client.ids["Shadow Walk"]
        client.repo.set_tag_probs(track, "genre", "head", "genre-logreg@aaaaaaa", {"jazz": 0.7})
        assert client.get(f"/api/tracks/{track}").json()["tags"] == []


# -- stream -----------------------------------------------------------------------------------


def jamendo_with_stream() -> FakeStreamJamendo:
    return FakeStreamJamendo({"1": STREAM})


def test_a_jamendo_stream_redirects_to_a_fresh_url_cached_for_later(tmp_path: Path) -> None:
    jamendo = jamendo_with_stream()
    with make_client(tmp_path, jamendo=jamendo) as client:
        url = f"/api/tracks/{client.ids['Shadow Walk']}/stream"
        first = client.get(url, follow_redirects=False)
        assert first.status_code == 307 and first.headers["location"] == STREAM
        assert first.content == b""  # no bytes are proxied
        second = client.get(url, follow_redirects=False)
        assert second.status_code == 307 and second.headers["location"] == STREAM
        assert jamendo.lookups == [["1"]]  # one lookup; the second came from the cache
        assert jamendo.closed == 1


def test_the_cached_stream_url_expires_after_thirty_minutes(tmp_path: Path) -> None:
    jamendo = jamendo_with_stream()
    with make_client(tmp_path, jamendo=jamendo) as client:
        now = [1000.0]
        cache = client.app.state.mcrar.stream_urls
        cache._clock = lambda: now[0]
        url = f"/api/tracks/{client.ids['Shadow Walk']}/stream"
        client.get(url, follow_redirects=False)
        now[0] += 29 * 60
        client.get(url, follow_redirects=False)
        assert len(jamendo.lookups) == 1
        now[0] += 2 * 60
        client.get(url, follow_redirects=False)
        assert len(jamendo.lookups) == 2


def test_a_missing_client_id_is_503(tmp_path: Path) -> None:
    missing = JamendoError("No Jamendo client id is configured. Get a free one ...")
    with make_client(tmp_path, jamendo=missing) as client:
        response = client.get(f"/api/tracks/{client.ids['Shadow Walk']}/stream")
        assert response.status_code == 503
        assert response.json() == {"detail": "Jamendo client id is not set"}


def test_jamendo_errors_are_502_with_the_redacted_message(tmp_path: Path) -> None:
    for error in (
        JamendoAuthError("Jamendo rejected the client id (HTTP 401); client_id=***"),
        JamendoRateLimitError("Jamendo rate limit reached; try again later"),
    ):
        with make_client(tmp_path, jamendo=FakeStreamJamendo(error=error)) as client:
            response = client.get(f"/api/tracks/{client.ids['Shadow Walk']}/stream")
            assert response.status_code == 502
            assert response.json() == {"detail": str(error)}


def test_unexpected_client_failures_do_not_leak_their_message(tmp_path: Path) -> None:
    error = RuntimeError("GET https://api.jamendo.com/v3.0/tracks/?client_id=SECRET failed")
    with make_client(tmp_path, jamendo=FakeStreamJamendo(error=error)) as client:
        response = client.get(f"/api/tracks/{client.ids['Shadow Walk']}/stream")
        assert response.status_code == 502
        assert "SECRET" not in response.text and "RuntimeError" in response.text


def test_a_track_gone_from_jamendo_is_404(tmp_path: Path) -> None:
    with make_client(tmp_path, jamendo=FakeStreamJamendo({})) as client:
        response = client.get(f"/api/tracks/{client.ids['Shadow Walk']}/stream")
        assert response.status_code == 404
        assert "no longer available" in response.json()["detail"]


def freesound_track(client, url: str | None, n: int = 1) -> int:
    return client.repo.upsert_track(
        TrackRecord(source="freesound", source_id=str(n), title="Rain", stream_url=url)
    )


def test_a_freesound_stream_redirects_to_the_stored_preview_without_any_lookup(
    tmp_path: Path,
) -> None:
    preview = "https://cdn.freesound.org/previews/1/1_1-hq.mp3"
    jamendo = FakeStreamJamendo(error=RuntimeError("must not be called"))
    # no Freesound key (the factory raises) and a Jamendo client that fails if asked
    with make_client(tmp_path, jamendo=jamendo) as client:
        track_id = freesound_track(client, preview)
        response = client.get(f"/api/tracks/{track_id}/stream", follow_redirects=False)
        assert response.status_code == 307 and response.headers["location"] == preview
        assert response.content == b""
        assert jamendo.lookups == []


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "http://cdn.freesound.org/previews/1/p.mp3",  # not https
        "https://evil.example/previews/1/p.mp3",
        "https://freesound.org.evil.example/p.mp3",
        "https://notfreesound.org/p.mp3",
        "https://cdn.freesound.org@evil.example/p.mp3",
        "file:///etc/passwd",
        "javascript:alert(1)",
    ],
)
def test_a_freesound_stream_to_another_host_is_404(tmp_path: Path, url: str | None) -> None:
    with make_client(tmp_path) as client:
        track_id = freesound_track(client, url)
        response = client.get(f"/api/tracks/{track_id}/stream", follow_redirects=False)
        assert response.status_code == 404
        assert "location" not in response.headers


def test_a_freesound_stream_on_the_bare_domain_or_a_subdomain_is_accepted(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        for n, url in enumerate(("https://freesound.org/p.mp3", "https://a.b.freesound.org/p.mp3")):
            track_id = freesound_track(client, url, n=n + 1)
            response = client.get(f"/api/tracks/{track_id}/stream", follow_redirects=False)
            assert response.status_code == 307 and response.headers["location"] == url


def local_track(client, tmp_path: Path, name: str = "a.wav") -> tuple[int, Path]:
    wav = write_wav(tmp_path / "audio" / name, seconds=1.0)
    track_id = client.repo.upsert_track(
        TrackRecord(source="local", source_id=name, title="A", local_path=str(wav))
    )
    return track_id, wav


def test_a_local_file_is_served_whole_and_by_range(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        track_id, wav = local_track(client, tmp_path)
        data = wav.read_bytes()
        whole = client.get(f"/api/tracks/{track_id}/stream")
        assert whole.status_code == 200 and whole.content == data
        assert whole.headers["content-type"] in ("audio/x-wav", "audio/wav", "audio/wave")
        assert whole.headers["accept-ranges"] == "bytes"
        part = client.get(f"/api/tracks/{track_id}/stream", headers={"Range": "bytes=10-99"})
        assert part.status_code == 206
        assert part.headers["content-range"] == f"bytes 10-99/{len(data)}"
        assert part.content == data[10:100]
        tail = client.get(f"/api/tracks/{track_id}/stream", headers={"Range": "bytes=-20"})
        assert tail.status_code == 206 and tail.content == data[-20:]
        beyond = client.get(
            f"/api/tracks/{track_id}/stream", headers={"Range": f"bytes={len(data) + 5}-"}
        )
        assert beyond.status_code == 416


def test_a_missing_local_file_is_404(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        track_id, wav = local_track(client, tmp_path)
        wav.unlink()
        response = client.get(f"/api/tracks/{track_id}/stream")
        assert response.status_code == 404 and "missing" in response.json()["detail"]
        no_path = client.repo.upsert_track(TrackRecord(source="local", source_id="b", title="B"))
        assert client.get(f"/api/tracks/{no_path}/stream").status_code == 404


def test_the_stream_route_takes_no_path_from_the_request(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        track_id, _ = local_track(client, tmp_path)
        secret = tmp_path / "secret.txt"
        secret.write_text("secret", encoding="utf-8")
        response = client.get(f"/api/tracks/{track_id}/stream", params={"path": str(secret)})
        assert b"secret" not in response.content
        assert client.get("/api/tracks/9999/stream").status_code == 404


# -- credits ----------------------------------------------------------------------------------


def test_credits_download_in_each_format(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        track = client.ids["Epic Quest"]
        txt = client.get(f"/api/tracks/{track}/credits")
        assert txt.status_code == 200
        assert txt.headers["content-type"].startswith("text/plain")
        assert txt.headers["content-disposition"] == 'attachment; filename="Epic-Quest-license.txt"'
        assert '"Epic Quest" by Gus' in txt.text and "CC BY 3.0" in txt.text

        md = client.get(f"/api/tracks/{track}/credits", params={"format": "md"})
        assert md.headers["content-type"].startswith("text/markdown")
        assert md.headers["content-disposition"].endswith('Epic-Quest-license.md"')
        assert md.text.startswith("# Music credits")

        as_json = client.get(f"/api/tracks/{track}/credits", params={"format": "json"})
        assert as_json.headers["content-type"] == "application/json"
        payload = json.loads(as_json.text)
        assert payload["items"][0]["title"] == "Epic Quest"
        assert payload["items"][0]["license"]["risk"] == "green"
        assert "disclaimer" in payload


def test_credits_errors(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        track = client.ids["Epic Quest"]
        assert (
            client.get(f"/api/tracks/{track}/credits", params={"format": "pdf"}).status_code == 422
        )
        assert client.get("/api/tracks/9999/credits").status_code == 404


def test_credits_filename_is_safe_for_awkward_titles(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        track = client.repo.upsert_track(
            TrackRecord(source="local", source_id="x", title='../"Odd" é title\r\n')
        )
        header = client.get(f"/api/tracks/{track}/credits").headers["content-disposition"]
        assert header == 'attachment; filename="Odd-title-license.txt"'
        blank = client.repo.upsert_track(TrackRecord(source="local", source_id="y"))
        header = client.get(f"/api/tracks/{blank}/credits").headers["content-disposition"]
        assert header == 'attachment; filename="track-license.txt"'
