"""Shared helpers for the sources tests (not a test module; unique basename on purpose)."""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from mcrar.sources.freesound import FreesoundClient
from mcrar.sources.jamendo import JamendoClient

SECRET = "SECRET123"

REAL_TRACK: dict[str, Any] = {
    "id": "979853",
    "name": "Garnet",
    "duration": 310,
    "artist_id": "427108",
    "artist_name": "Ken Elkinson",
    "artist_idstr": "Ken_Elkinson",
    "album_name": "Elemental Volume 1",
    "album_id": "115409",
    "license_ccurl": "http://creativecommons.org/licenses/by-nc-nd/3.0/",
    "position": 5,
    "releasedate": "2012-11-15",
    "album_image": "https://usercontent.jamendo.com?type=album&id=115409&width=300&trackid=979853",
    "audio": "https://prod-1.storage.jamendo.com/?trackid=979853&format=mp32&from=vkqu...%3D%3D",
    "audiodownload": "https://prod-1.storage.jamendo.com/download/track/979853/mp32/",
    "prourl": "https://licensing.jamendo.com/track/979853",
    "shorturl": "https://jamen.do/t/979853",
    "shareurl": "https://www.jamendo.com/track/979853",
    "waveform": '{"peaks":[0,0]}',
    "image": "https://usercontent.jamendo.com?type=album&id=115409&width=300&trackid=979853",
    "musicinfo": {
        "vocalinstrumental": "instrumental",
        "lang": "",
        "gender": "neutral",
        "acousticelectric": "electric",
        "speed": "medium",
        "tags": {
            "genres": ["ambient"],
            "instruments": ["synthesizer"],
            "vartags": ["peaceful", "spa"],
        },
    },
    "licenses": {
        "ccnc": "true",
        "ccnd": "true",
        "ccsa": "false",
        "prolicensing": "true",
        "probackground": "true",
    },
    "audiodownload_allowed": True,
    "content_id_free": False,
}


def track_json(n: int) -> dict[str, Any]:
    data = copy.deepcopy(REAL_TRACK)
    data["id"] = str(n)
    data["name"] = f"Track {n}"
    return data


def envelope(results: list[dict[str, Any]], **header_overrides: Any) -> dict[str, Any]:
    headers = {
        "status": "success",
        "code": 0,
        "error_message": "",
        "warnings": "",
        "results_count": len(results),
    }
    headers.update(header_overrides)
    return {"headers": headers, "results": results}


def error_envelope(message: str, code: int = 5) -> dict[str, Any]:
    return {
        "headers": {"status": "failed", "code": code, "error_message": message, "warnings": ""},
        "results": [],
    }


FS_SOUND: dict[str, Any] = {
    "id": 456789,
    "url": "https://freesound.org/people/someone/sounds/456789/",
    "name": "Warm pad loop",
    "tags": ["loop", "pad", "ambient"],
    "description": "A slowly evolving warm pad.",
    "license": "https://creativecommons.org/licenses/by/4.0/",
    "username": "someone",
    "duration": 42.5,
    "previews": {
        "preview-hq-mp3": "https://cdn.freesound.org/previews/456/456789_1-hq.mp3",
        "preview-lq-mp3": "https://cdn.freesound.org/previews/456/456789_1-lq.mp3",
        "preview-hq-ogg": "https://cdn.freesound.org/previews/456/456789_1-hq.ogg",
        "preview-lq-ogg": "https://cdn.freesound.org/previews/456/456789_1-lq.ogg",
    },
    "pack": "https://freesound.org/apiv2/packs/9999/",
    "category": "Music",
    "gen_ai_preference": "no-preference",
    "created": "2019-03-04T12:34:56.789",
    "num_downloads": 12,
    "avg_rating": 4.5,
    "type": "wav",
    "samplerate": 44100,
    "channels": 2,
}


def sound_json(n: int) -> dict[str, Any]:
    data = copy.deepcopy(FS_SOUND)
    data["id"] = n
    data["name"] = f"Sound {n}"
    data["previews"]["preview-hq-mp3"] = f"https://cdn.freesound.org/previews/0/{n}-hq.mp3"
    return data


def search_page(results: list[dict[str, Any]], *, next_page: int | None = None) -> dict[str, Any]:
    return {
        "count": len(results),
        "next": f"https://freesound.org/apiv2/search/?page={next_page}" if next_page else None,
        "previous": None,
        "results": results,
    }


def fs_paged_backend(total: int) -> Backend:
    """A fake Freesound catalog of ``total`` sounds honouring page and page_size."""

    def respond(request: httpx.Request, _n: int) -> httpx.Response:
        params = request.url.params
        size, page = int(params["page_size"]), int(params.get("page", "1"))
        first = (page - 1) * size
        ids = list(range(first + 1, min(total, first + size) + 1))
        more = page + 1 if first + size < total else None
        return json_response(search_page([sound_json(i) for i in ids], next_page=more))

    return Backend(respond)


class FakeTime:
    """Injectable clock and sleep: sleeping advances the clock and records the delay."""

    def __init__(self, start: float = 1_760_000_000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class Backend:
    """A MockTransport handler that records requests and delegates to ``respond``."""

    def __init__(self, respond: Callable[[httpx.Request, int], httpx.Response]) -> None:
        self.respond = respond
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.respond(request, len(self.requests))

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def params(self, index: int = 0) -> httpx.QueryParams:
        return self.requests[index].url.params


def json_response(payload: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


def paged_backend(total: int) -> Backend:
    """A fake catalog of ``total`` tracks honouring limit and offset."""

    def respond(request: httpx.Request, _n: int) -> httpx.Response:
        params = request.url.params
        limit, offset = int(params["limit"]), int(params.get("offset", "0"))
        ids = range(offset + 1, min(total, offset + limit) + 1)
        return json_response(envelope([track_json(i) for i in ids]))

    return Backend(respond)


def make_client(
    backend: Backend,
    fake: FakeTime,
    cache_dir: Path | None = None,
    client_id: str = SECRET,
    **kwargs: Any,
) -> JamendoClient:
    kwargs.setdefault("min_interval_s", 0)
    return JamendoClient(
        client_id,
        cache_dir=cache_dir,
        transport=backend.transport,
        clock=fake.clock,
        sleep=fake.sleep,
        **kwargs,
    )


def make_freesound_client(
    backend: Backend,
    fake: FakeTime,
    cache_dir: Path | None = None,
    api_key: str = SECRET,
    **kwargs: Any,
) -> FreesoundClient:
    kwargs.setdefault("min_interval_s", 0)
    return FreesoundClient(
        api_key,
        cache_dir=cache_dir,
        transport=backend.transport,
        clock=fake.clock,
        sleep=fake.sleep,
        **kwargs,
    )
