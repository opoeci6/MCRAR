"""The API key must never leak: exceptions, logs, cache file names/contents, usage file, repr."""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from sources_support import (
    FS_SOUND,
    SECRET,
    Backend,
    FakeTime,
    fs_paged_backend,
    json_response,
    make_freesound_client,
    search_page,
    sound_json,
)

from mcrar.sources import FreesoundError, parse_sound

Respond = Callable[[httpx.Request, int], httpx.Response]


def _timeout(request: httpx.Request, n: int) -> httpx.Response:
    raise httpx.ReadTimeout(f"timed out: {request.url} {request.headers}", request=request)


def _connect(request: httpx.Request, n: int) -> httpx.Response:
    raise httpx.ConnectError(f"cannot connect to {request.url} {request.headers}", request=request)


def _protocol(request: httpx.Request, n: int) -> httpx.Response:
    raise httpx.TooManyRedirects(f"too many redirects for {request.url}", request=request)


def _echo(request: httpx.Request) -> str:
    return f"{request.url} {request.headers.get('authorization', '')}"


API_ERROR_CASES: dict[str, Respond] = {
    "timeout": _timeout,
    "connect-error": _connect,
    "too-many-redirects": _protocol,
    "http-500": lambda r, n: httpx.Response(500, text=_echo(r)),
    "http-429": lambda r, n: httpx.Response(429, text=_echo(r), headers={"Retry-After": "1"}),
    "http-401": lambda r, n: httpx.Response(401, json={"detail": f"Invalid token {SECRET}"}),
    "http-403": lambda r, n: httpx.Response(403, text=_echo(r)),
    "http-404": lambda r, n: httpx.Response(404, text=_echo(r)),
    "http-400": lambda r, n: httpx.Response(400, json={"detail": f"bad Token {SECRET}"}),
    "bad-json": lambda r, n: httpx.Response(200, text=f"oops {_echo(r)}"),
}

AUDIO_ERROR_CASES: dict[str, Respond] = {
    "timeout": _timeout,
    "connect-error": _connect,
    "http-500": lambda r, n: httpx.Response(500, text=_echo(r)),
    "http-403": lambda r, n: httpx.Response(403, text=_echo(r)),
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
    client = make_freesound_client(backend, fake, tmp_path / "cache")
    with pytest.raises(FreesoundError) as info:
        list(client.search_tracks(tags="loop", limit=5))
    assert backend.requests[0].headers["Authorization"] == f"Token {SECRET}"  # it was sent
    assert SECRET not in str(backend.requests[0].url)
    assert_clean_exception(info.value)
    assert_clean_environment(tmp_path, caplog)
    assert (tmp_path / "cache" / "usage.json").is_file()  # the usage file was exercised


@pytest.mark.parametrize("case", sorted(AUDIO_ERROR_CASES))
def test_audio_error_paths_are_redacted(
    case: str, fake: FakeTime, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    track = parse_sound(FS_SOUND)
    assert track is not None
    client = make_freesound_client(Backend(AUDIO_ERROR_CASES[case]), fake, tmp_path / "cache")
    with pytest.raises(FreesoundError) as info:
        client.fetch_audio(track, max_bytes=10)
    assert_clean_exception(info.value)
    assert_clean_environment(tmp_path, caplog)


def test_invalid_stream_url_error_is_redacted(
    fake: FakeTime, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    track = parse_sound({**FS_SOUND, "previews": {"preview-hq-mp3": f"https://evil.test/{SECRET}"}})
    assert track is not None
    client = make_freesound_client(fs_paged_backend(1), fake, tmp_path / "cache")
    with pytest.raises(FreesoundError) as info:
        client.fetch_audio(track)
    assert_clean_exception(info.value)
    assert_clean_environment(tmp_path, caplog)


def test_key_echoed_in_a_message_is_scrubbed_by_the_error_builder(fake: FakeTime) -> None:
    client = make_freesound_client(fs_paged_backend(1), fake)
    error = client._error(FreesoundError, f"boom {SECRET} and Token {SECRET}")
    assert SECRET not in str(error)
    assert "***" in str(error)


def test_success_path_files_and_logs_are_clean(
    fake: FakeTime, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    client = make_freesound_client(
        fs_paged_backend(3), fake, tmp_path / "cache", min_interval_s=0.5
    )
    assert len(list(client.search_tracks(tags="loop", limit=3))) == 3
    assert len(list(client.search_tracks(tags="loop", limit=3))) == 3  # cache hit
    client.get_tracks([1, 2])
    assert client.usage()["requests"] == 2
    assert_clean_environment(tmp_path, caplog)
    assert SECRET not in repr(client)


def test_retry_logs_are_clean(
    fake: FakeTime, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    def respond(request: httpx.Request, n: int) -> httpx.Response:
        if n == 1:
            raise httpx.ReadTimeout(f"timed out: {request.url}", request=request)
        if n == 2:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return json_response(search_page([sound_json(1)]))

    client = make_freesound_client(Backend(respond), fake, tmp_path / "cache")
    assert len(list(client.search_tracks(limit=1))) == 1
    assert [r for r in caplog.records if r.levelno == logging.WARNING]  # retries were logged
    assert_clean_environment(tmp_path, caplog)


def test_httpx_request_log_lines_never_contain_the_key(
    fake: FakeTime, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)  # httpx logs "HTTP Request: GET <url>" at INFO
    client = make_freesound_client(fs_paged_backend(1), fake, tmp_path / "cache")
    list(client.search_tracks(limit=1))
    httpx_lines = [r.getMessage() for r in caplog.records if r.name == "httpx"]
    assert httpx_lines
    assert_clean_environment(tmp_path, caplog)
    client.close()


def test_httpx_logger_filter_scrubs_the_key_and_is_removed_on_close(
    fake: FakeTime, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    httpx_logger = logging.getLogger("httpx")
    before = list(httpx_logger.filters)
    client = make_freesound_client(fs_paged_backend(1), fake)
    assert len(httpx_logger.filters) == len(before) + 1
    httpx_logger.info("HTTP Request: GET https://x.test/?k=%s Token %s", SECRET, SECRET)
    assert SECRET not in caplog.text
    assert "***" in caplog.text
    client.close()
    assert httpx_logger.filters == before


def test_repr_hides_the_key(fake: FakeTime) -> None:
    client = make_freesound_client(fs_paged_backend(1), fake, Path("some") / "dir")
    assert SECRET not in repr(client)
    assert SECRET not in str(client)
