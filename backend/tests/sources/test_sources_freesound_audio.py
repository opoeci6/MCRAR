"""FreesoundClient.fetch_audio: preview streaming without the token, host check, size cap."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import httpx
import pytest
from sources_support import (
    FS_SOUND,
    Backend,
    FakeTime,
    fs_paged_backend,
    make_freesound_client,
)

from mcrar.sources import (
    FreesoundError,
    FreesoundRateLimitError,
    FreesoundStreamError,
    SourceTrack,
    parse_sound,
)

AUDIO = b"ID3" + bytes(range(256)) * 8


@pytest.fixture
def fake() -> FakeTime:
    return FakeTime()


@pytest.fixture
def track() -> SourceTrack:
    parsed = parse_sound(FS_SOUND)
    assert parsed is not None
    return parsed


def files_under(path: Path) -> list[Path]:
    return [p for p in path.rglob("*") if p.is_file()]


def test_fetch_audio_requests_the_preview_without_the_token(
    fake: FakeTime, track: SourceTrack
) -> None:
    backend = Backend(lambda request, n: httpx.Response(200, content=AUDIO))
    client = make_freesound_client(backend, fake)
    assert client.fetch_audio(track) == AUDIO
    request = backend.requests[0]
    assert str(request.url) == track.stream_url
    assert "authorization" not in request.headers
    assert "Token" not in str(request.headers)


def test_fetch_audio_writes_nothing_to_disk_and_is_not_counted(
    fake: FakeTime, track: SourceTrack, tmp_path: Path
) -> None:
    backend = Backend(lambda request, n: httpx.Response(200, content=AUDIO))
    client = make_freesound_client(backend, fake, tmp_path / "cache")
    client.fetch_audio(track)
    assert files_under(tmp_path) == []
    assert client.usage()["requests"] == 0

    api_backend = fs_paged_backend(2)

    def respond(request: httpx.Request, n: int) -> httpx.Response:
        if request.url.host == "freesound.org":
            return api_backend.respond(request, n)
        return httpx.Response(200, content=AUDIO)

    api = make_freesound_client(Backend(respond), fake, tmp_path / "cache")
    list(api.search_tracks(limit=2))
    assert api.fetch_audio(track) == AUDIO
    names = {p.name for p in files_under(tmp_path)}
    assert all(n == "usage.json" or (n.endswith(".json") and len(n) == 69) for n in names)
    assert api.usage()["requests"] == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://cdn.freesound.org/previews/1/1-hq.mp3",
        "https://freesound.org/data/previews/1/1-hq.mp3",
        "HTTPS://CDN.FREESOUND.ORG/x.mp3",
    ],
)
def test_freesound_hosts_are_accepted(fake: FakeTime, track: SourceTrack, url: str) -> None:
    backend = Backend(lambda request, n: httpx.Response(200, content=AUDIO))
    client = make_freesound_client(backend, fake)
    assert client.fetch_audio(dataclasses.replace(track, stream_url=url)) == AUDIO


@pytest.mark.parametrize(
    "url",
    [
        "http://cdn.freesound.org/previews/1/1-hq.mp3",
        "https://evil.example.com/x.mp3",
        "https://freesound.org.evil.com/x.mp3",
        "https://notfreesound.org/x.mp3",
        "https://cdn.freesound.org@evil.com/x.mp3",
        "https://evil.com/?u=cdn.freesound.org",
        "ftp://cdn.freesound.org/x.mp3",
        "file:///etc/passwd",
        "//cdn.freesound.org/x.mp3",
        "cdn.freesound.org/x.mp3",
        "https://[::1/x.mp3",
    ],
)
def test_other_hosts_and_schemes_are_refused(fake: FakeTime, track: SourceTrack, url: str) -> None:
    backend = Backend(lambda request, n: httpx.Response(200, content=AUDIO))
    client = make_freesound_client(backend, fake)
    with pytest.raises(FreesoundStreamError):
        client.fetch_audio(dataclasses.replace(track, stream_url=url))
    assert backend.requests == []


def test_missing_stream_url(fake: FakeTime, track: SourceTrack) -> None:
    backend = Backend(lambda request, n: httpx.Response(200, content=AUDIO))
    client = make_freesound_client(backend, fake)
    for missing in (None, ""):
        with pytest.raises(FreesoundError, match="stream_url"):
            client.fetch_audio(dataclasses.replace(track, stream_url=missing))
    assert backend.requests == []


def test_size_cap_by_content_length(fake: FakeTime, track: SourceTrack) -> None:
    backend = Backend(lambda request, n: httpx.Response(200, content=b"x" * 1000))
    client = make_freesound_client(backend, fake)
    with pytest.raises(FreesoundStreamError, match="larger than"):
        client.fetch_audio(track, max_bytes=999)
    assert client.fetch_audio(track, max_bytes=1000) == b"x" * 1000
    assert len(backend.requests) == 2  # the oversize failure was not retried


def test_size_cap_from_the_constructor(fake: FakeTime, track: SourceTrack) -> None:
    backend = Backend(lambda request, n: httpx.Response(200, content=b"x" * 1000))
    client = make_freesound_client(backend, fake, max_bytes=500)
    with pytest.raises(FreesoundStreamError, match="larger than"):
        client.fetch_audio(track)
    assert client.fetch_audio(track, max_bytes=2000) == b"x" * 1000


def test_size_cap_while_streaming(fake: FakeTime, track: SourceTrack) -> None:
    pulled: list[int] = []

    def chunks():  # no Content-Length: the cap must be enforced while streaming
        for i in range(100):
            pulled.append(i)
            yield b"y" * 100

    backend = Backend(lambda request, n: httpx.Response(200, content=chunks()))
    client = make_freesound_client(backend, fake)
    with pytest.raises(FreesoundStreamError, match="larger than"):
        client.fetch_audio(track, max_bytes=450)
    assert len(pulled) < 100
    assert len(backend.requests) == 1


def test_retries_5xx_timeouts_and_429_with_retry_after(fake: FakeTime, track: SourceTrack) -> None:
    def respond(request: httpx.Request, n: int) -> httpx.Response:
        if n == 1:
            raise httpx.ReadTimeout("slow", request=request)
        if n == 2:
            return httpx.Response(429, headers={"Retry-After": "4"})
        return httpx.Response(200, content=AUDIO)

    backend = Backend(respond)
    assert make_freesound_client(backend, fake).fetch_audio(track) == AUDIO
    assert fake.sleeps == [1.0, 4.0]
    assert all("authorization" not in r.headers for r in backend.requests)


def test_gives_up_after_max_attempts(fake: FakeTime, track: SourceTrack) -> None:
    backend = Backend(lambda request, n: httpx.Response(500))
    with pytest.raises(FreesoundError, match="3 attempts"):
        make_freesound_client(backend, fake).fetch_audio(track)
    assert len(backend.requests) == 3
    backend = Backend(lambda request, n: httpx.Response(429))
    with pytest.raises(FreesoundRateLimitError):
        make_freesound_client(backend, fake).fetch_audio(track)


def test_client_error_is_not_retried(fake: FakeTime, track: SourceTrack) -> None:
    backend = Backend(lambda request, n: httpx.Response(404))
    with pytest.raises(FreesoundStreamError, match="HTTP 404"):
        make_freesound_client(backend, fake).fetch_audio(track)
    assert len(backend.requests) == 1


def test_empty_body_is_an_error(fake: FakeTime, track: SourceTrack) -> None:
    backend = Backend(lambda request, n: httpx.Response(200, content=b""))
    with pytest.raises(FreesoundStreamError, match="empty"):
        make_freesound_client(backend, fake).fetch_audio(track)
