"""JamendoClient.fetch_audio: in-memory streaming, size cap, retries (no network)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import httpx
import pytest
from sources_support import (
    REAL_TRACK,
    Backend,
    FakeTime,
    make_client,
    paged_backend,
)

from mcrar.sources import (
    JamendoError,
    JamendoRateLimitError,
    JamendoStreamError,
    SourceTrack,
    parse_track,
)

AUDIO = b"ID3" + bytes(range(256)) * 8


@pytest.fixture
def fake() -> FakeTime:
    return FakeTime()


@pytest.fixture
def track() -> SourceTrack:
    parsed = parse_track(REAL_TRACK)
    assert parsed is not None
    return parsed


def files_under(path: Path) -> list[Path]:
    return [p for p in path.rglob("*") if p.is_file()]


def test_fetch_audio_success_requests_stream_url(
    fake: FakeTime, track: SourceTrack, tmp_path: Path
) -> None:
    backend = Backend(lambda request, n: httpx.Response(200, content=AUDIO))
    client = make_client(backend, fake, tmp_path / "cache")
    assert client.fetch_audio(track) == AUDIO
    assert str(backend.requests[0].url) == track.stream_url or (
        backend.requests[0].url.host == "prod-1.storage.jamendo.com"
        and backend.requests[0].url.params["trackid"] == "979853"
    )
    assert "client_id" not in backend.requests[0].url.params


def test_fetch_audio_writes_nothing_to_disk_and_is_not_counted(
    fake: FakeTime, track: SourceTrack, tmp_path: Path
) -> None:
    backend = Backend(lambda request, n: httpx.Response(200, content=AUDIO))
    cache_dir = tmp_path / "cache"
    client = make_client(backend, fake, cache_dir)
    client.fetch_audio(track)
    assert files_under(tmp_path) == []
    assert client.usage()["requests"] == 0
    # after API traffic, still only cache and usage files exist (never audio)
    api_backend = paged_backend(2)

    def respond(request: httpx.Request, n: int) -> httpx.Response:
        if request.url.host == "api.jamendo.com":
            return api_backend.respond(request, n)
        return httpx.Response(200, content=AUDIO)

    api = make_client(Backend(respond), fake, cache_dir)
    list(api.search_tracks(limit=2))
    assert api.fetch_audio(track) == AUDIO
    names = {p.name for p in files_under(tmp_path)}
    assert "usage.json" in names
    assert all(n == "usage.json" or (n.endswith(".json") and len(n) == 69) for n in names)
    assert api.usage()["requests"] == 1


def test_fetch_audio_size_cap_by_content_length(fake: FakeTime, track: SourceTrack) -> None:
    backend = Backend(lambda request, n: httpx.Response(200, content=b"x" * 1000))
    client = make_client(backend, fake)
    with pytest.raises(JamendoStreamError, match="larger than"):
        client.fetch_audio(track, max_bytes=999)
    assert client.fetch_audio(track, max_bytes=1000) == b"x" * 1000
    assert len(backend.requests) == 2  # the oversize failure was not retried


def test_fetch_audio_size_cap_while_streaming(fake: FakeTime, track: SourceTrack) -> None:
    pulled: list[int] = []

    def chunks():  # no Content-Length: the cap must be enforced while streaming
        for i in range(100):
            pulled.append(i)
            yield b"y" * 100

    backend = Backend(lambda request, n: httpx.Response(200, content=chunks()))
    client = make_client(backend, fake)
    with pytest.raises(JamendoStreamError, match="larger than"):
        client.fetch_audio(track, max_bytes=450)
    assert len(pulled) < 100  # aborted early instead of reading everything
    assert len(backend.requests) == 1


def test_fetch_audio_missing_stream_url(fake: FakeTime, track: SourceTrack) -> None:
    backend = Backend(lambda request, n: httpx.Response(200, content=AUDIO))
    client = make_client(backend, fake)
    bare = dataclasses.replace(track, stream_url=None)
    with pytest.raises(JamendoError, match="stream_url"):
        client.fetch_audio(bare)
    with pytest.raises(JamendoError, match="stream_url"):
        client.fetch_audio(dataclasses.replace(track, stream_url=""))
    assert backend.requests == []


def test_fetch_audio_retries_like_the_api(fake: FakeTime, track: SourceTrack) -> None:
    def respond(request: httpx.Request, n: int) -> httpx.Response:
        if n == 1:
            raise httpx.ReadTimeout("slow", request=request)
        if n == 2:
            return httpx.Response(503)
        return httpx.Response(200, content=AUDIO)

    backend = Backend(respond)
    assert make_client(backend, fake).fetch_audio(track) == AUDIO
    assert fake.sleeps == [1.0, 2.0]


def test_fetch_audio_gives_up_after_max_attempts(fake: FakeTime, track: SourceTrack) -> None:
    backend = Backend(lambda request, n: httpx.Response(500))
    with pytest.raises(JamendoError, match="3 attempts"):
        make_client(backend, fake).fetch_audio(track)
    assert len(backend.requests) == 3

    backend = Backend(lambda request, n: httpx.Response(429))
    with pytest.raises(JamendoRateLimitError):
        make_client(backend, fake).fetch_audio(track)


def test_fetch_audio_http_error_is_not_retried_and_hints_expiry(
    fake: FakeTime, track: SourceTrack
) -> None:
    backend = Backend(lambda request, n: httpx.Response(403))
    with pytest.raises(JamendoStreamError, match="expired"):
        make_client(backend, fake).fetch_audio(track)
    assert len(backend.requests) == 1


def test_fetch_audio_empty_body_is_error(fake: FakeTime, track: SourceTrack) -> None:
    backend = Backend(lambda request, n: httpx.Response(200, content=b""))
    with pytest.raises(JamendoStreamError, match="empty"):
        make_client(backend, fake).fetch_audio(track)
