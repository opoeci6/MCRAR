"""The client id must never leak: exceptions, logs, cache file names/contents, usage file."""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from sources_support import (
    REAL_TRACK,
    SECRET,
    Backend,
    FakeTime,
    envelope,
    error_envelope,
    json_response,
    make_client,
    paged_backend,
)

from mcrar.sources import JamendoError, parse_track

Respond = Callable[[httpx.Request, int], httpx.Response]


def _timeout(request: httpx.Request, n: int) -> httpx.Response:
    raise httpx.ReadTimeout(f"timed out: {request.url}", request=request)


def _connect(request: httpx.Request, n: int) -> httpx.Response:
    raise httpx.ConnectError(f"cannot connect to {request.url}", request=request)


def _protocol(request: httpx.Request, n: int) -> httpx.Response:
    raise httpx.TooManyRedirects(f"too many redirects for {request.url}", request=request)


API_ERROR_CASES: dict[str, Respond] = {
    "timeout": _timeout,
    "connect-error": _connect,
    "too-many-redirects": _protocol,
    "http-500": lambda r, n: httpx.Response(500, text=str(r.url)),
    "http-429": lambda r, n: httpx.Response(429, text=str(r.url)),
    "http-401": lambda r, n: httpx.Response(401, text=str(r.url)),
    "http-403": lambda r, n: httpx.Response(403),
    "http-404": lambda r, n: httpx.Response(404, text=str(r.url)),
    "bad-json": lambda r, n: httpx.Response(200, text=f"oops {r.url}"),
    "auth-envelope-echoing-id": lambda r, n: json_response(
        error_envelope(f"Invalid client_id {SECRET} for {r.url}", 10)
    ),
    "plain-envelope-echoing-id": lambda r, n: json_response(
        error_envelope(f"bad request client_id={SECRET}&limit=x")
    ),
    "rate-limit-envelope-echoing-id": lambda r, n: json_response(
        error_envelope(f"Rate limit exceeded for {SECRET}", 11)
    ),
}

AUDIO_ERROR_CASES: dict[str, Respond] = {
    "timeout": _timeout,
    "connect-error": _connect,
    "http-500": lambda r, n: httpx.Response(500, text=str(r.url)),
    "http-403": lambda r, n: httpx.Response(403, text=str(r.url)),
    "too-big": lambda r, n: httpx.Response(200, content=b"x" * 100),
}


@pytest.fixture
def fake() -> FakeTime:
    return FakeTime()


def assert_clean_exception(exc: BaseException) -> None:
    assert SECRET not in str(exc)
    assert SECRET not in repr(exc)
    assert exc.__cause__ is None
    assert exc.__context__ is None
    assert SECRET not in "".join(traceback.format_exception(exc))


def assert_clean_environment(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    for record in caplog.records:
        assert SECRET not in record.getMessage()
        assert SECRET not in str(record.args)
        assert SECRET not in (record.exc_text or "")
    assert SECRET not in caplog.text
    for path in tmp_path.rglob("*"):
        assert SECRET not in str(path.relative_to(tmp_path))
        if path.is_file():
            assert SECRET.encode() not in path.read_bytes(), path.name


@pytest.mark.parametrize("case", sorted(API_ERROR_CASES))
def test_api_error_paths_are_redacted(
    case: str, fake: FakeTime, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    backend = Backend(API_ERROR_CASES[case])
    client = make_client(backend, fake, tmp_path / "cache")
    with pytest.raises(JamendoError) as info:
        list(client.search_tracks(tags="rock", limit=5))
    assert backend.requests[0].url.params["client_id"] == SECRET  # it really was sent
    assert_clean_exception(info.value)
    assert_clean_environment(tmp_path, caplog)
    assert (tmp_path / "cache" / "usage.json").is_file()  # the usage file was exercised


@pytest.mark.parametrize("case", sorted(AUDIO_ERROR_CASES))
def test_audio_error_paths_are_redacted(
    case: str, fake: FakeTime, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    track = parse_track(REAL_TRACK)
    assert track is not None
    client = make_client(Backend(AUDIO_ERROR_CASES[case]), fake, tmp_path / "cache")
    with pytest.raises(JamendoError) as info:
        client.fetch_audio(track, max_bytes=10)
    assert_clean_exception(info.value)
    assert_clean_environment(tmp_path, caplog)


def test_missing_stream_url_error_is_redacted(
    fake: FakeTime, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    track = parse_track({**REAL_TRACK, "audio": ""})
    assert track is not None
    client = make_client(paged_backend(1), fake, tmp_path / "cache")
    with pytest.raises(JamendoError) as info:
        client.fetch_audio(track)
    assert_clean_exception(info.value)
    assert_clean_environment(tmp_path, caplog)


def test_success_path_files_and_logs_are_clean(
    fake: FakeTime, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    client = make_client(paged_backend(3), fake, tmp_path / "cache", min_interval_s=0.5)
    assert len(list(client.search_tracks(tags="rock", limit=3))) == 3
    assert len(list(client.search_tracks(tags="rock", limit=3))) == 3  # cache hit
    client.get_tracks(["1", "2"])
    assert client.usage()["requests"] == 2
    assert_clean_environment(tmp_path, caplog)
    assert SECRET not in repr(client)


def test_retry_and_empty_page_logs_are_clean(
    fake: FakeTime, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    def respond(request: httpx.Request, n: int) -> httpx.Response:
        if n == 1:
            raise httpx.ReadTimeout(f"timed out: {request.url}", request=request)
        if n == 2:
            return json_response(envelope([]))
        return json_response(envelope([{"id": "1", "name": "a"}]))

    client = make_client(Backend(respond), fake, tmp_path / "cache")
    assert len(list(client.search_tracks(limit=1))) == 1
    assert caplog.records  # retry and empty-page warnings were actually logged
    assert_clean_environment(tmp_path, caplog)


def test_httpx_request_log_lines_are_scrubbed(
    fake: FakeTime, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)  # httpx logs "HTTP Request: GET <full url>" at INFO
    client = make_client(paged_backend(1), fake, tmp_path / "cache")
    list(client.search_tracks(limit=1))
    httpx_lines = [r.getMessage() for r in caplog.records if r.name == "httpx"]
    assert httpx_lines
    assert all("client_id=***" in line for line in httpx_lines)
    assert_clean_environment(tmp_path, caplog)
    client.close()
