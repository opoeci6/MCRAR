"""Params, pagination, retries and error handling of JamendoClient (no network)."""

from __future__ import annotations

import httpx
import pytest
from sources_support import (
    SECRET,
    Backend,
    FakeTime,
    envelope,
    error_envelope,
    json_response,
    make_client,
    paged_backend,
    track_json,
)

from mcrar.sources import JamendoAuthError, JamendoError, JamendoRateLimitError


@pytest.fixture
def fake() -> FakeTime:
    return FakeTime()


# -- params ----------------------------------------------------------------------------


def test_default_params(fake: FakeTime) -> None:
    backend = paged_backend(3)
    client = make_client(backend, fake)
    tracks = list(client.search_tracks())
    assert [t.source_id for t in tracks] == ["1", "2", "3"]
    request = backend.requests[0]
    assert request.method == "GET"
    assert request.url.scheme == "https"
    assert request.url.host == "api.jamendo.com"
    assert request.url.path == "/v3.0/tracks/"
    params = backend.params()
    assert params["format"] == "json"
    assert params["include"] == "musicinfo licenses"
    assert params["audioformat"] == "mp32"
    assert params["limit"] == "200"
    assert params["offset"] == "0"
    assert params["client_id"] == SECRET
    for absent in ("ccnc", "ccnd", "tags", "fuzzytags", "search", "order", "boost"):
        assert absent not in params


def test_filter_params(fake: FakeTime) -> None:
    backend = paged_backend(1)
    client = make_client(backend, fake)
    list(
        client.search_tracks(
            tags=["rock", "indie"],
            fuzzytags="calm sad",
            search="dawn",
            vocalinstrumental="instrumental",
            speed="high",
            duration_between=(60, 240),
            order="popularity_month",
            boost="popularity_month",
            limit=10,
            offset=20,
        )
    )
    params = backend.params()
    assert params["tags"] == "rock indie"
    assert params["fuzzytags"] == "calm sad"
    assert params["search"] == "dawn"
    assert params["vocalinstrumental"] == "instrumental"
    assert params["speed"] == "high"
    assert params["durationbetween"] == "60_240"
    assert params["order"] == "popularity_month"
    assert params["boost"] == "popularity_month"
    assert params["limit"] == "10"
    assert params["offset"] == "20"


def test_duration_between_string_passthrough(fake: FakeTime) -> None:
    backend = paged_backend(1)
    list(make_client(backend, fake).search_tracks(duration_between="30_90", limit=5))
    assert backend.params()["durationbetween"] == "30_90"


def test_commercial_only_adds_cc_filters(fake: FakeTime) -> None:
    backend = paged_backend(1)
    list(make_client(backend, fake).search_tracks(commercial_only=True))
    params = backend.params()
    assert params["ccnc"] == "false"
    assert params["ccnd"] == "false"
    assert params["include"] == "musicinfo licenses"
    assert params["audioformat"] == "mp32"


def test_negative_limit_rejected(fake: FakeTime) -> None:
    with pytest.raises(ValueError):
        make_client(paged_backend(1), fake).search_tracks(limit=-1)


def test_limit_zero_makes_no_request(fake: FakeTime) -> None:
    backend = paged_backend(5)
    assert list(make_client(backend, fake).search_tracks(limit=0)) == []
    assert backend.requests == []


# -- pagination ------------------------------------------------------------------------


def test_pagination_450_makes_three_requests(fake: FakeTime) -> None:
    backend = paged_backend(1000)
    tracks = list(make_client(backend, fake).search_tracks(limit=450, offset=10))
    assert len(tracks) == 450
    assert [t.source_id for t in tracks] == [str(i) for i in range(11, 461)]
    assert [(p["limit"], p["offset"]) for p in (backend.params(i) for i in range(3))] == [
        ("200", "10"),
        ("200", "210"),
        ("50", "410"),
    ]
    assert len(backend.requests) == 3


def test_short_page_stops_early(fake: FakeTime) -> None:
    backend = paged_backend(250)
    tracks = list(make_client(backend, fake).search_tracks(limit=1000))
    assert len(tracks) == 250
    assert len(backend.requests) == 2  # 200 then a short page of 50


def test_search_is_lazy(fake: FakeTime) -> None:
    backend = paged_backend(1000)
    iterator = make_client(backend, fake).search_tracks(limit=400)
    assert backend.requests == []
    next(iterator)
    assert len(backend.requests) == 1


def test_rate_limit_interval_between_requests(fake: FakeTime) -> None:
    backend = paged_backend(1000)
    client = make_client(backend, fake, min_interval_s=0.5)
    list(client.search_tracks(limit=400))
    assert fake.sleeps == [0.5]  # nothing before the first request, throttle before the second


# -- retries ---------------------------------------------------------------------------


def test_retry_on_timeout_then_success(fake: FakeTime) -> None:
    def respond(request: httpx.Request, n: int) -> httpx.Response:
        if n < 3:
            raise httpx.ReadTimeout(f"timed out for {request.url}", request=request)
        return json_response(envelope([track_json(1)]))

    backend = Backend(respond)
    tracks = list(make_client(backend, fake).search_tracks(limit=1))
    assert len(tracks) == 1
    assert len(backend.requests) == 3
    assert fake.sleeps == [1.0, 2.0]


def test_retry_on_connect_error_and_500_and_429(fake: FakeTime) -> None:
    def respond(request: httpx.Request, n: int) -> httpx.Response:
        if n == 1:
            raise httpx.ConnectError("refused", request=request)
        if n == 2:
            return httpx.Response(500)
        if n == 3:
            return httpx.Response(429)
        return json_response(envelope([track_json(1)]))

    backend = Backend(respond)
    tracks = list(make_client(backend, fake, max_attempts=4).search_tracks(limit=1))
    assert len(tracks) == 1
    assert fake.sleeps == [1.0, 2.0, 4.0]


@pytest.mark.parametrize(
    ("status", "error"),
    [(500, JamendoError), (503, JamendoError), (429, JamendoRateLimitError)],
)
def test_gives_up_after_max_attempts(fake: FakeTime, status: int, error: type[Exception]) -> None:
    backend = Backend(lambda request, n: httpx.Response(status))
    client = make_client(backend, fake, max_attempts=3)
    with pytest.raises(error) as info:
        list(client.search_tracks(limit=1))
    assert type(info.value) is error
    assert "3 attempts" in str(info.value)
    assert len(backend.requests) == 3
    assert fake.sleeps == [1.0, 2.0]


def test_gives_up_after_repeated_timeouts(fake: FakeTime) -> None:
    def respond(request: httpx.Request, n: int) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    backend = Backend(respond)
    with pytest.raises(JamendoError, match="timeout"):
        list(make_client(backend, fake, max_attempts=2).search_tracks(limit=1))
    assert len(backend.requests) == 2
    assert fake.sleeps == [1.0]


def test_custom_backoff(fake: FakeTime) -> None:
    backend = Backend(lambda request, n: httpx.Response(500))
    client = make_client(backend, fake, backoff_s=0.25)
    with pytest.raises(JamendoError):
        list(client.search_tracks(limit=1))
    assert fake.sleeps == [0.25, 0.5]


def test_client_error_is_not_retried(fake: FakeTime) -> None:
    backend = Backend(lambda request, n: httpx.Response(404, text="nope"))
    with pytest.raises(JamendoError, match="HTTP 404"):
        list(make_client(backend, fake).search_tracks(limit=1))
    assert len(backend.requests) == 1
    assert fake.sleeps == []


# -- empty first page ------------------------------------------------------------------


def test_empty_first_page_is_retried(fake: FakeTime) -> None:
    def respond(request: httpx.Request, n: int) -> httpx.Response:
        if n == 1:
            return json_response(envelope([]))
        return json_response(envelope([track_json(1), track_json(2), track_json(3)]))

    backend = Backend(respond)
    tracks = list(make_client(backend, fake).search_tracks(limit=200))
    assert len(tracks) == 3
    assert len(backend.requests) == 2
    assert fake.sleeps == [2.0]


def test_empty_first_page_retried_with_doubling_backoff_until_results(fake: FakeTime) -> None:
    # Live, the same query stayed empty on the retry 2 s later and only answered on the third try.
    def respond(request: httpx.Request, n: int) -> httpx.Response:
        if n < 3:
            return json_response(envelope([]))
        return json_response(envelope([track_json(1)]))

    backend = Backend(respond)
    assert len(list(make_client(backend, fake).search_tracks(limit=200))) == 1
    assert len(backend.requests) == 3
    assert fake.sleeps == [2.0, 4.0]


def test_empty_first_page_gives_up_after_empty_retries(fake: FakeTime) -> None:
    backend = Backend(lambda request, n: json_response(envelope([])))
    assert list(make_client(backend, fake).search_tracks(limit=200)) == []
    assert len(backend.requests) == 4  # first request + 3 retries
    assert fake.sleeps == [2.0, 4.0, 8.0]


def test_empty_later_page_is_not_retried(fake: FakeTime) -> None:
    def respond(request: httpx.Request, n: int) -> httpx.Response:
        if n == 1:
            return json_response(envelope([track_json(i) for i in range(200)]))
        return json_response(envelope([]))

    backend = Backend(respond)
    tracks = list(make_client(backend, fake).search_tracks(limit=400))
    assert len(tracks) == 200
    assert len(backend.requests) == 2
    assert fake.sleeps == []


# -- API errors ------------------------------------------------------------------------


def test_api_error_envelope_raises_jamendo_error(fake: FakeTime) -> None:
    backend = Backend(lambda request, n: json_response(error_envelope("Invalid parameter foo")))
    with pytest.raises(JamendoError, match="Invalid parameter foo") as info:
        list(make_client(backend, fake).search_tracks(limit=1))
    assert not isinstance(info.value, JamendoAuthError)
    assert len(backend.requests) == 1


def test_api_error_status_without_code_is_error(fake: FakeTime) -> None:
    payload = envelope([track_json(1)], status="failed")
    backend = Backend(lambda request, n: json_response(payload))
    with pytest.raises(JamendoError):
        list(make_client(backend, fake).search_tracks(limit=1))


def test_api_error_mentioning_client_id_is_auth_error(fake: FakeTime) -> None:
    backend = Backend(lambda request, n: json_response(error_envelope("Invalid client_id", 10)))
    with pytest.raises(JamendoAuthError):
        list(make_client(backend, fake).search_tracks(limit=1))
    assert len(backend.requests) == 1  # auth errors are not retried


@pytest.mark.parametrize("status", [401, 403])
def test_http_401_403_is_auth_error(fake: FakeTime, status: int) -> None:
    backend = Backend(lambda request, n: httpx.Response(status))
    with pytest.raises(JamendoAuthError):
        list(make_client(backend, fake).search_tracks(limit=1))
    assert len(backend.requests) == 1


def test_api_rate_limit_message_is_retried_then_rate_limit_error(fake: FakeTime) -> None:
    backend = Backend(lambda request, n: json_response(error_envelope("Rate limit exceeded", 11)))
    with pytest.raises(JamendoRateLimitError):
        list(make_client(backend, fake).search_tracks(limit=1))
    assert len(backend.requests) == 3


def test_non_json_response_is_error(fake: FakeTime) -> None:
    backend = Backend(lambda request, n: httpx.Response(200, text="<html>oops</html>"))
    with pytest.raises(JamendoError, match="unexpected response"):
        list(make_client(backend, fake).search_tracks(limit=1))


def test_invalid_client_id_rejected_in_constructor(fake: FakeTime) -> None:
    with pytest.raises(ValueError):
        make_client(paged_backend(1), fake, client_id="  ")


# -- get_tracks ------------------------------------------------------------------------


def test_get_tracks_batches_of_200_in_requested_order(fake: FakeTime) -> None:
    def respond(request: httpx.Request, n: int) -> httpx.Response:
        ids = request.url.params["id"].split(" ")
        return json_response(envelope([track_json(int(i)) for i in reversed(ids)]))

    backend = Backend(respond)
    wanted = list(range(1, 451))
    tracks = make_client(backend, fake).get_tracks(wanted)
    assert [t.source_id for t in tracks] == [str(i) for i in wanted]
    assert [len(backend.params(i)["id"].split(" ")) for i in range(3)] == [200, 200, 50]
    assert [backend.params(i)["limit"] for i in range(3)] == ["200", "200", "50"]
    assert backend.params()["include"] == "musicinfo licenses"
    assert backend.params()["audioformat"] == "mp32"


def test_get_tracks_dedupes_and_skips_unknown(fake: FakeTime) -> None:
    def respond(request: httpx.Request, n: int) -> httpx.Response:
        return json_response(envelope([track_json(2)]))

    backend = Backend(respond)
    tracks = make_client(backend, fake).get_tracks(["1", 2, "2", "1"])
    assert [t.source_id for t in tracks] == ["2"]
    assert backend.params()["id"] == "1 2"


def test_get_tracks_empty_input_makes_no_request(fake: FakeTime) -> None:
    backend = paged_backend(1)
    assert make_client(backend, fake).get_tracks([]) == []
    assert backend.requests == []
