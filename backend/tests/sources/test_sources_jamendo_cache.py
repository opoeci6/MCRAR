"""Disk cache, usage counter and from_settings of JamendoClient (no network)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
import pytest
from sources_support import (
    SECRET,
    Backend,
    FakeTime,
    envelope,
    json_response,
    make_client,
    paged_backend,
    track_json,
)

from mcrar.config import Settings
from mcrar.secrets import SecretStore
from mcrar.sources import JamendoClient, JamendoError


@pytest.fixture
def fake() -> FakeTime:
    return FakeTime()


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    return tmp_path / "cache" / "jamendo"


def cache_files(cache_dir: Path) -> list[Path]:
    if not cache_dir.is_dir():
        return []
    return sorted(p for p in cache_dir.iterdir() if p.name != "usage.json")


# -- cache -----------------------------------------------------------------------------


def test_cache_hit_avoids_network(fake: FakeTime, cache_dir: Path) -> None:
    backend = paged_backend(5)
    client = make_client(backend, fake, cache_dir)
    first = list(client.search_tracks(tags="rock", limit=5))
    second = list(client.search_tracks(tags="rock", limit=5))
    assert first == second
    assert len(first) == 5
    assert len(backend.requests) == 1
    assert len(cache_files(cache_dir)) == 1
    assert client.usage()["requests"] == 1


def test_different_query_is_a_cache_miss(fake: FakeTime, cache_dir: Path) -> None:
    backend = paged_backend(5)
    client = make_client(backend, fake, cache_dir)
    list(client.search_tracks(tags="rock", limit=5))
    list(client.search_tracks(tags="jazz", limit=5))
    assert len(backend.requests) == 2
    assert len(cache_files(cache_dir)) == 2


def test_cache_key_ignores_client_id(fake: FakeTime, cache_dir: Path) -> None:
    backend = paged_backend(5)
    list(make_client(backend, fake, cache_dir, client_id="AAAA1111").search_tracks(limit=5))
    list(make_client(backend, fake, cache_dir, client_id="BBBB2222").search_tracks(limit=5))
    assert len(backend.requests) == 1
    assert len(cache_files(cache_dir)) == 1


def test_cache_ttl_expiry(fake: FakeTime, cache_dir: Path) -> None:
    backend = paged_backend(5)
    client = make_client(backend, fake, cache_dir, cache_ttl_s=100)
    list(client.search_tracks(limit=5))
    fake.now += 99
    list(client.search_tracks(limit=5))
    assert len(backend.requests) == 1
    fake.now += 2  # 101 s old now
    list(client.search_tracks(limit=5))
    assert len(backend.requests) == 2
    fake.now += 50
    list(client.search_tracks(limit=5))  # the refetch rewrote the entry
    assert len(backend.requests) == 2


@pytest.mark.parametrize(
    "garbage",
    [
        "not json at all",
        "",
        "[]",
        '{"fetched_at": "x", "results": []}',
        '{"fetched_at": 1, "results": "nope"}',
        '{"results": [{"id": "1"}]}',
    ],
)
def test_corrupt_cache_file_is_ignored(fake: FakeTime, cache_dir: Path, garbage: str) -> None:
    backend = paged_backend(5)
    client = make_client(backend, fake, cache_dir)
    list(client.search_tracks(limit=5))
    (entry,) = cache_files(cache_dir)
    entry.write_text(garbage, encoding="utf-8")
    assert len(list(client.search_tracks(limit=5))) == 5
    assert len(backend.requests) == 2
    json.loads(entry.read_text(encoding="utf-8"))  # healed with valid JSON


def test_empty_pages_are_never_cached(fake: FakeTime, cache_dir: Path) -> None:
    backend = Backend(lambda request, n: json_response(envelope([])))
    client = make_client(backend, fake, cache_dir)
    assert list(client.search_tracks(limit=5)) == []
    assert cache_files(cache_dir) == []
    assert list(client.search_tracks(limit=5)) == []
    assert len(backend.requests) == 8  # two calls, each with 3 empty-first-page retries


def test_use_cache_false_disables_read_and_write(fake: FakeTime, cache_dir: Path) -> None:
    backend = paged_backend(5)
    client = make_client(backend, fake, cache_dir, use_cache=False)
    list(client.search_tracks(limit=5))
    list(client.search_tracks(limit=5))
    assert len(backend.requests) == 2
    assert cache_files(cache_dir) == []


def test_no_cache_dir_means_no_files(fake: FakeTime, tmp_path: Path) -> None:
    backend = paged_backend(5)
    client = make_client(backend, fake, None)
    list(client.search_tracks(limit=5))
    list(client.search_tracks(limit=5))
    assert len(backend.requests) == 2
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


def test_get_tracks_bypasses_cache_by_default(fake: FakeTime, cache_dir: Path) -> None:
    def respond(request: httpx.Request, n: int) -> httpx.Response:
        return json_response(envelope([track_json(1)]))

    backend = Backend(respond)
    client = make_client(backend, fake, cache_dir)
    client.get_tracks(["1"])
    client.get_tracks(["1"])
    assert len(backend.requests) == 2
    assert cache_files(cache_dir) == []
    client.get_tracks(["1"], use_cache=True)
    client.get_tracks(["1"], use_cache=True)
    assert len(backend.requests) == 3


def test_cache_write_is_atomic_no_leftovers(fake: FakeTime, cache_dir: Path) -> None:
    list(make_client(paged_backend(5), fake, cache_dir).search_tracks(limit=5))
    assert not [p for p in cache_dir.iterdir() if p.suffix == ".part"]
    (entry,) = cache_files(cache_dir)
    assert entry.suffix == ".json"
    assert len(entry.stem) == 64  # sha256 hex


# -- usage counter ---------------------------------------------------------------------


def test_usage_counts_real_requests_per_month(fake: FakeTime, cache_dir: Path) -> None:
    backend = paged_backend(1000)
    client = make_client(backend, fake, cache_dir)
    assert client.usage() == {"month": "2025-10", "requests": 0}
    list(client.search_tracks(limit=400))
    assert client.usage() == {"month": "2025-10", "requests": 2}
    assert json.loads((cache_dir / "usage.json").read_text()) == client.usage()
    fake.now += 31 * 24 * 3600  # into the next month
    assert client.usage() == {"month": "2025-11", "requests": 0}
    list(client.search_tracks(limit=5))
    assert client.usage() == {"month": "2025-11", "requests": 1}


def test_usage_counts_failed_attempts_and_persists_across_clients(
    fake: FakeTime, cache_dir: Path
) -> None:
    backend = Backend(lambda request, n: httpx.Response(500))
    client = make_client(backend, fake, cache_dir)
    with pytest.raises(JamendoError):
        list(client.search_tracks(limit=1))
    assert client.usage()["requests"] == 3
    other = make_client(paged_backend(1), fake, cache_dir)
    assert other.usage()["requests"] == 3
    list(other.search_tracks(limit=1))
    assert other.usage()["requests"] == 4


def test_usage_in_memory_without_cache_dir(fake: FakeTime) -> None:
    client = make_client(paged_backend(1), fake, None)
    list(client.search_tracks(limit=1))
    assert client.usage()["requests"] == 1


def test_corrupt_usage_file_resets(fake: FakeTime, cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True)
    (cache_dir / "usage.json").write_text("{{{", encoding="utf-8")
    client = make_client(paged_backend(1), fake, cache_dir)
    assert client.usage()["requests"] == 0
    list(client.search_tracks(limit=1))
    assert client.usage()["requests"] == 1


def test_usage_warning_when_passing_threshold(
    fake: FakeTime, cache_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cache_dir.mkdir(parents=True)
    (cache_dir / "usage.json").write_text(
        json.dumps({"month": "2025-10", "requests": 30_000}), encoding="utf-8"
    )
    client = make_client(paged_backend(1000), fake, cache_dir)
    with caplog.at_level(logging.WARNING, logger="mcrar.sources.jamendo"):
        list(client.search_tracks(limit=400))
    warnings = [r for r in caplog.records if "usage" in r.getMessage().lower()]
    assert len(warnings) == 1  # warned once, not on every request
    assert "30001" in warnings[0].getMessage()
    assert warnings[0].levelno == logging.WARNING


def test_no_usage_warning_below_threshold(
    fake: FakeTime, cache_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cache_dir.mkdir(parents=True)
    (cache_dir / "usage.json").write_text(
        json.dumps({"month": "2025-10", "requests": 29_998}), encoding="utf-8"
    )
    client = make_client(paged_backend(1000), fake, cache_dir)
    with caplog.at_level(logging.DEBUG, logger="mcrar.sources.jamendo"):
        list(client.search_tracks(limit=400))  # reaches exactly 30,000: not past it yet
    assert not [r for r in caplog.records if "usage" in r.getMessage().lower()]


def test_custom_usage_threshold(
    fake: FakeTime, cache_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    client = make_client(paged_backend(1000), fake, cache_dir, usage_warn_threshold=1)
    with caplog.at_level(logging.WARNING, logger="mcrar.sources.jamendo"):
        list(client.search_tracks(limit=400))
    assert len([r for r in caplog.records if "usage" in r.getMessage().lower()]) == 1


# -- from_settings ---------------------------------------------------------------------


def test_from_settings_missing_secret_is_helpful(fake: FakeTime) -> None:
    settings = Settings()
    with pytest.raises(JamendoError) as info:
        JamendoClient.from_settings(settings, SecretStore(settings))
    assert "mcrar secrets set jamendo_client_id" in str(info.value)


def test_from_settings_uses_secret_and_cache_dir(
    fake: FakeTime, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCRAR_SECRET_JAMENDO_CLIENT_ID", SECRET)
    settings = Settings()
    backend = paged_backend(3)
    client = JamendoClient.from_settings(
        settings, transport=backend.transport, clock=fake.clock, sleep=fake.sleep
    )
    assert SECRET not in repr(client)
    assert len(list(client.search_tracks(limit=3))) == 3
    assert backend.params()["client_id"] == SECRET
    expected = settings.cache_dir / "jamendo"
    assert (expected / "usage.json").is_file()
    assert len(cache_files(expected)) == 1


def test_from_settings_default_secret_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCRAR_SECRET_JAMENDO_CLIENT_ID", SECRET)
    client = JamendoClient.from_settings(Settings())
    client.close()
    monkeypatch.delenv("MCRAR_SECRET_JAMENDO_CLIENT_ID")
    with pytest.raises(JamendoError, match="mcrar secrets set jamendo_client_id"):
        JamendoClient.from_settings(Settings())
