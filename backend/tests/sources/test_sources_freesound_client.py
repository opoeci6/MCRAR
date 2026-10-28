"""Params, pagination, retries and error handling of FreesoundClient (no network)."""

from __future__ import annotations

import httpx
import pytest
from sources_support import (
    SECRET,
    Backend,
    FakeTime,
    fs_paged_backend,
    json_response,
    make_freesound_client,
    search_page,
    sound_json,
)

from mcrar.sources import FreesoundAuthError, FreesoundError, FreesoundRateLimitError
from mcrar.sources.freesound import FIELDS, MUSIC_LIKE_FILTER


@pytest.fixture
def fake() -> FakeTime:
    return FakeTime()


# -- params ----------------------------------------------------------------------------


def test_default_params(fake: FakeTime) -> None:
    backend = fs_paged_backend(3)
    client = make_freesound_client(backend, fake)
    tracks = list(client.search_tracks())
    assert [t.source_id for t in tracks] == ["1", "2", "3"]
    request = backend.requests[0]
    assert request.method == "GET"
    assert request.url.scheme == "https"
    assert request.url.host == "freesound.org"
    assert request.url.path == "/apiv2/search/"
    assert dict(backend.params()) == {
        "filter": (
            'duration:[10 TO 600] license:("Creative Commons 0" OR "Attribution") '
            + MUSIC_LIKE_FILTER
        ),
        "sort": "score",
        "page": "1",
        "page_size": "50",
        "fields": FIELDS,
    }
    assert FIELDS == (
        "id,url,name,tags,description,license,username,duration,previews,pack,category,"
        "gen_ai_preference,created,num_downloads,avg_rating,type,samplerate,channels"
    )


def test_music_like_filter_is_the_music_and_soundscape_categories() -> None:
    assert MUSIC_LIKE_FILTER == 'category:("Music" OR "Soundscapes")'


def test_filter_with_query_tags_licenses_durations_and_sort(fake: FakeTime) -> None:
    backend = fs_paged_backend(1)
    client = make_freesound_client(backend, fake)
    list(
        client.search_tracks(
            query="  warm   pad ",
            tags=["loop", "Dark_Ambient", "lo-fi"],
            licenses=("cc0", "by-nc", "sampling+"),
            duration_min_s=30,
            duration_max_s=120.5,
            sort="downloads_desc",
            limit=10,
        )
    )
    params = backend.params()
    assert params["query"] == "warm pad"
    assert params["filter"] == (
        "duration:[30 TO 120.5] "
        'license:("Creative Commons 0" OR "Attribution NonCommercial" OR "Sampling+") '
        "tag:loop tag:dark_ambient tag:lo-fi " + MUSIC_LIKE_FILTER
    )
    assert params["sort"] == "downloads_desc"
    assert params["page_size"] == "10"


def test_filter_without_music_like(fake: FakeTime) -> None:
    backend = fs_paged_backend(1)
    list(make_freesound_client(backend, fake).search_tracks(music_like=False, tags="loop"))
    assert backend.params()["filter"] == (
        'duration:[10 TO 600] license:("Creative Commons 0" OR "Attribution") tag:loop'
    )


def test_open_ended_and_missing_filter_clauses(fake: FakeTime) -> None:
    backend = fs_paged_backend(1)
    client = make_freesound_client(backend, fake)
    list(client.search_tracks(duration_max_s=None, licenses=(), music_like=False))
    assert backend.params()["filter"] == "duration:[10 TO *]"
    backend = fs_paged_backend(1)
    client = make_freesound_client(backend, fake)
    list(
        client.search_tracks(
            duration_min_s=None, duration_max_s=None, licenses=(), music_like=False
        )
    )
    assert "filter" not in backend.params()
    assert "query" not in backend.params()


@pytest.mark.parametrize(
    "bad_tag", ["a b", 'x"', "a)", "tag:evil", "a OR b", "", "  ", "café", "x*", "a\nb"]
)
def test_invalid_tags_are_rejected_before_any_request(fake: FakeTime, bad_tag: str) -> None:
    backend = fs_paged_backend(1)
    client = make_freesound_client(backend, fake)
    with pytest.raises(ValueError, match="tag"):
        client.search_tracks(tags=[bad_tag])
    assert backend.requests == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sort": "bogus"},
        {"sort": "duration"},
        {"limit": 0},
        {"limit": -3},
        {"licenses": ("by-sa",)},
        {"duration_min_s": -1},
        {"duration_min_s": 100, "duration_max_s": 10},
    ],
)
def test_invalid_arguments_are_rejected_eagerly(fake: FakeTime, kwargs: dict) -> None:
    backend = fs_paged_backend(1)
    client = make_freesound_client(backend, fake)
    with pytest.raises(ValueError):
        client.search_tracks(**kwargs)  # raises on the call, not when iterating
    assert backend.requests == []


@pytest.mark.parametrize("sort", ["score", "created_asc", "rating_desc", "duration_asc"])
def test_allowed_sorts(fake: FakeTime, sort: str) -> None:
    backend = fs_paged_backend(1)
    list(make_freesound_client(backend, fake).search_tracks(sort=sort, limit=1))
    assert backend.params()["sort"] == sort


# -- pagination ------------------------------------------------------------------------


def test_paging_stops_at_limit(fake: FakeTime) -> None:
    backend = fs_paged_backend(1000)
    client = make_freesound_client(backend, fake)
    tracks = list(client.search_tracks(limit=200))
    assert [t.source_id for t in tracks] == [str(i) for i in range(1, 201)]
    assert [p["page"] for p in (backend.params(i) for i in range(2))] == ["1", "2"]
    # the same page size on every page, otherwise page 2 would overlap page 1
    assert [backend.params(i)["page_size"] for i in range(2)] == ["150", "150"]
    assert len(backend.requests) == 2


def test_paging_stops_when_next_is_null(fake: FakeTime) -> None:
    backend = fs_paged_backend(7)
    tracks = list(make_freesound_client(backend, fake).search_tracks(limit=500))
    assert len(tracks) == 7
    assert len(backend.requests) == 1
    assert backend.params()["page_size"] == "150"


def test_paging_second_page_ends_at_null_next(fake: FakeTime) -> None:
    backend = fs_paged_backend(160)
    tracks = list(make_freesound_client(backend, fake).search_tracks(limit=400))
    assert [t.source_id for t in tracks] == [str(i) for i in range(1, 161)]
    assert [backend.params(i)["page"] for i in range(2)] == ["1", "2"]
    assert len(backend.requests) == 2


def test_limit_smaller_than_one_page_needs_one_request(fake: FakeTime) -> None:
    backend = fs_paged_backend(100)
    assert len(list(make_freesound_client(backend, fake).search_tracks(limit=5))) == 5
    assert len(backend.requests) == 1
    assert backend.params()["page_size"] == "5"


def test_empty_page_ends_the_search(fake: FakeTime) -> None:
    backend = Backend(lambda request, n: json_response(search_page([], next_page=2)))
    assert list(make_freesound_client(backend, fake).search_tracks(limit=10)) == []
    assert len(backend.requests) == 1


def test_sounds_without_preview_are_skipped_but_counted(fake: FakeTime) -> None:
    no_preview = sound_json(2)
    del no_preview["previews"]

    def respond(request: httpx.Request, n: int) -> httpx.Response:
        return json_response(search_page([sound_json(1), no_preview, sound_json(3)]))

    tracks = list(make_freesound_client(Backend(respond), fake).search_tracks(limit=3))
    assert [t.source_id for t in tracks] == ["1", "3"]


# -- auth header -----------------------------------------------------------------------


def test_token_header_is_sent_and_key_is_never_in_the_url(fake: FakeTime) -> None:
    backend = fs_paged_backend(3)
    client = make_freesound_client(backend, fake)
    list(client.search_tracks())
    client.get_tracks([1, 2])
    assert len(backend.requests) == 2
    for request in backend.requests:
        assert request.headers["Authorization"] == f"Token {SECRET}"
        assert SECRET not in str(request.url)
        assert "token" not in request.url.params
        assert "api_key" not in request.url.params
    assert "freesound client" in backend.requests[0].headers["User-Agent"]


# -- retries ---------------------------------------------------------------------------


def test_429_with_retry_after_waits_that_long_then_succeeds(fake: FakeTime) -> None:
    ok = fs_paged_backend(2)

    def respond(request: httpx.Request, n: int) -> httpx.Response:
        if n == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return ok.respond(request, n)

    backend = Backend(respond)
    tracks = list(make_freesound_client(backend, fake).search_tracks(limit=2))
    assert len(tracks) == 2
    assert fake.sleeps == [7.0]
    assert len(backend.requests) == 2


def test_retry_after_is_capped(fake: FakeTime) -> None:
    ok = fs_paged_backend(1)

    def respond(request: httpx.Request, n: int) -> httpx.Response:
        if n == 1:
            return httpx.Response(429, headers={"Retry-After": "3600"})
        return ok.respond(request, n)

    list(make_freesound_client(Backend(respond), fake).search_tracks(limit=1))
    assert fake.sleeps == [60.0]


@pytest.mark.parametrize("header", [None, "soon", "Wed, 21 Oct 2026 07:28:00 GMT", "-5", ""])
def test_429_without_usable_retry_after_uses_backoff(fake: FakeTime, header: str | None) -> None:
    ok = fs_paged_backend(1)

    def respond(request: httpx.Request, n: int) -> httpx.Response:
        if n <= 2:
            headers = {} if header is None else {"Retry-After": header}
            return httpx.Response(429, headers=headers)
        return ok.respond(request, n)

    list(make_freesound_client(Backend(respond), fake).search_tracks(limit=1))
    assert fake.sleeps == [1.0, 2.0]


def test_429_exhaustion_raises_rate_limit_error(fake: FakeTime) -> None:
    backend = Backend(lambda request, n: httpx.Response(429, headers={"Retry-After": "2"}))
    client = make_freesound_client(backend, fake)
    with pytest.raises(FreesoundRateLimitError, match="3 attempts"):
        list(client.search_tracks(limit=1))
    assert len(backend.requests) == 3
    assert fake.sleeps == [2.0, 2.0]  # no sleep after the last attempt


@pytest.mark.parametrize("status", [401, 403])
def test_bad_key_is_an_auth_error_without_retries(fake: FakeTime, status: int) -> None:
    backend = Backend(lambda request, n: httpx.Response(status, json={"detail": "nope"}))
    client = make_freesound_client(backend, fake)
    with pytest.raises(FreesoundAuthError, match="freesound_api_key"):
        list(client.search_tracks(limit=1))
    assert len(backend.requests) == 1
    assert fake.sleeps == []
    with pytest.raises(FreesoundAuthError):
        client.get_tracks([1])


def test_5xx_and_timeouts_are_retried_with_exponential_backoff(fake: FakeTime) -> None:
    ok = fs_paged_backend(1)

    def respond(request: httpx.Request, n: int) -> httpx.Response:
        if n == 1:
            raise httpx.ReadTimeout("slow", request=request)
        if n == 2:
            return httpx.Response(503)
        return ok.respond(request, n)

    backend = Backend(respond)
    assert len(list(make_freesound_client(backend, fake).search_tracks(limit=1))) == 1
    assert fake.sleeps == [1.0, 2.0]


def test_5xx_exhaustion_raises_freesound_error(fake: FakeTime) -> None:
    backend = Backend(lambda request, n: httpx.Response(500))
    with pytest.raises(FreesoundError, match="3 attempts") as info:
        list(make_freesound_client(backend, fake).search_tracks(limit=1))
    assert not isinstance(info.value, (FreesoundRateLimitError, FreesoundAuthError))
    assert len(backend.requests) == 3


def test_other_4xx_and_bad_bodies_are_not_retried(fake: FakeTime) -> None:
    for response in (
        httpx.Response(404),
        httpx.Response(400, json={"detail": "bad"}),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"results": "nope"}),
        httpx.Response(200, json=[1, 2]),
    ):
        backend = Backend(lambda request, n, r=response: r)
        with pytest.raises(FreesoundError):
            list(make_freesound_client(backend, fake).search_tracks(limit=1))
        assert len(backend.requests) == 1


def test_throttle_spaces_requests(fake: FakeTime) -> None:
    backend = fs_paged_backend(1000)
    client = make_freesound_client(backend, fake, min_interval_s=1.1)
    list(client.search_tracks(limit=300))
    assert len(backend.requests) == 2
    assert fake.sleeps == [pytest.approx(1.1)]


def test_default_throttle_is_1_1_seconds(fake: FakeTime) -> None:
    from mcrar.sources import FreesoundClient

    client = FreesoundClient(
        SECRET, transport=fs_paged_backend(1000).transport, clock=fake.clock, sleep=fake.sleep
    )
    list(client.search_tracks(limit=300))
    assert fake.sleeps == [pytest.approx(1.1)]


# -- get_tracks ------------------------------------------------------------------------


def test_get_tracks_builds_an_id_filter_and_keeps_order(fake: FakeTime) -> None:
    def respond(request: httpx.Request, n: int) -> httpx.Response:
        return json_response(search_page([sound_json(2), sound_json(7), sound_json(5)]))

    backend = Backend(respond)
    client = make_freesound_client(backend, fake)
    tracks = client.get_tracks([7, "5", 2, 7, 99])
    assert [t.source_id for t in tracks] == ["7", "5", "2"]  # 99 unknown, 7 deduplicated
    params = backend.params()
    assert params["filter"] == "id:(7 OR 5 OR 2 OR 99)"
    assert params["fields"] == FIELDS
    assert params["page_size"] == "4"
    assert params["page"] == "1"
    assert "query" not in params


def test_get_tracks_batches_of_100(fake: FakeTime) -> None:
    def respond(request: httpx.Request, n: int) -> httpx.Response:
        flt = request.url.params["filter"]
        ids = [int(i) for i in flt[len("id:(") : -1].split(" OR ")]
        return json_response(search_page([sound_json(i) for i in ids]))

    backend = Backend(respond)
    client = make_freesound_client(backend, fake)
    tracks = client.get_tracks(range(1, 251))
    assert [t.source_id for t in tracks] == [str(i) for i in range(1, 251)]
    assert [len(backend.params(i)["filter"].split(" OR ")) for i in range(3)] == [100, 100, 50]
    assert [backend.params(i)["page_size"] for i in range(3)] == ["100", "100", "50"]


def test_get_tracks_empty_makes_no_request(fake: FakeTime) -> None:
    backend = fs_paged_backend(1)
    assert make_freesound_client(backend, fake).get_tracks([]) == []
    assert backend.requests == []


@pytest.mark.parametrize(
    "bad", ["abc", "1 OR 2", "1) OR (2", "", "-1", "1.5", True, 1.5, None, "12;13", "١"]
)
def test_get_tracks_validates_ids(fake: FakeTime, bad: object) -> None:
    backend = fs_paged_backend(1)
    client = make_freesound_client(backend, fake)
    with pytest.raises(ValueError, match="id"):
        client.get_tracks([1, bad])  # type: ignore[list-item]
    assert backend.requests == []


def test_constructor_validation() -> None:
    from mcrar.sources import FreesoundClient

    for key in ("", "   "):
        with pytest.raises(ValueError):
            FreesoundClient(key)
    with pytest.raises(ValueError):
        FreesoundClient("k", max_attempts=0)
