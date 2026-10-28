"""Disk cache, daily usage counter and from_settings of FreesoundClient (no network)."""

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
    fs_paged_backend,
    json_response,
    make_freesound_client,
    search_page,
    sound_json,
)

from mcrar.config import Settings
from mcrar.secrets import SecretStore
from mcrar.sources import FreesoundClient, FreesoundError


@pytest.fixture
def fake() -> FakeTime:
    return FakeTime()  # 2025-10-09 08:53:20 UTC


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    return tmp_path / "cache" / "freesound"


def cache_files(cache_dir: Path) -> list[Path]:
    if not cache_dir.is_dir():
        return []
    return sorted(p for p in cache_dir.iterdir() if p.name != "usage.json")


# -- cache -----------------------------------------------------------------------------


def test_cache_hit_avoids_network(fake: FakeTime, cache_dir: Path) -> None:
    backend = fs_paged_backend(5)
    client = make_freesound_client(backend, fake, cache_dir)
    first = list(client.search_tracks(tags="loop", limit=5))
    second = list(client.search_tracks(tags="loop", limit=5))
    assert first == second
    assert len(first) == 5
    assert len(backend.requests) == 1
    assert len(cache_files(cache_dir)) == 1
    assert client.usage()["requests"] == 1
    assert client.usage()["cache_hits"] == 1


def test_cache_file_has_no_key_and_a_hashed_name(fake: FakeTime, cache_dir: Path) -> None:
    client = make_freesound_client(fs_paged_backend(5), fake, cache_dir)
    list(client.search_tracks(tags="loop", limit=5))
    (entry,) = cache_files(cache_dir)
    assert entry.suffix == ".json"
    assert len(entry.stem) == 64  # sha256 hex
    assert SECRET not in entry.name
    assert SECRET.encode() not in entry.read_bytes()
    assert SECRET.encode() not in (cache_dir / "usage.json").read_bytes()
    data = json.loads(entry.read_text(encoding="utf-8"))
    assert set(data) == {"fetched_at", "results", "has_next"}
    assert data["has_next"] is False
    assert not [p for p in cache_dir.iterdir() if p.suffix == ".part"]


def test_cache_keeps_has_next_so_paging_works_from_cache(fake: FakeTime, cache_dir: Path) -> None:
    backend = fs_paged_backend(160)
    client = make_freesound_client(backend, fake, cache_dir)
    first = list(client.search_tracks(limit=400))
    assert len(first) == 160 and len(backend.requests) == 2
    assert list(client.search_tracks(limit=400)) == first
    assert len(backend.requests) == 2


def test_different_query_is_a_cache_miss(fake: FakeTime, cache_dir: Path) -> None:
    backend = fs_paged_backend(5)
    client = make_freesound_client(backend, fake, cache_dir)
    list(client.search_tracks(tags="loop", limit=5))
    list(client.search_tracks(tags="drone", limit=5))
    list(client.search_tracks(tags="loop", sort="created_desc", limit=5))
    list(client.search_tracks(query="rain", tags="loop", limit=5))
    assert len(backend.requests) == 4
    assert len(cache_files(cache_dir)) == 4


def test_cache_key_ignores_the_api_key(fake: FakeTime, cache_dir: Path) -> None:
    backend = fs_paged_backend(5)
    list(make_freesound_client(backend, fake, cache_dir, api_key="AAAA1111").search_tracks(limit=5))
    list(make_freesound_client(backend, fake, cache_dir, api_key="BBBB2222").search_tracks(limit=5))
    assert len(backend.requests) == 1
    assert len(cache_files(cache_dir)) == 1


def test_cache_ttl_expiry(fake: FakeTime, cache_dir: Path) -> None:
    backend = fs_paged_backend(5)
    client = make_freesound_client(backend, fake, cache_dir, cache_ttl_s=100)
    list(client.search_tracks(limit=5))
    fake.now += 99
    list(client.search_tracks(limit=5))
    assert len(backend.requests) == 1
    fake.now += 2
    list(client.search_tracks(limit=5))
    assert len(backend.requests) == 2


def test_default_ttl_is_seven_days(fake: FakeTime, cache_dir: Path) -> None:
    backend = fs_paged_backend(5)
    client = make_freesound_client(backend, fake, cache_dir)
    list(client.search_tracks(limit=5))
    fake.now += 7 * 24 * 3600 - 1
    list(client.search_tracks(limit=5))
    assert len(backend.requests) == 1
    fake.now += 2
    list(client.search_tracks(limit=5))
    assert len(backend.requests) == 2


@pytest.mark.parametrize(
    "garbage",
    [
        "not json at all",
        "",
        "[]",
        '{"fetched_at": "x", "results": []}',
        '{"fetched_at": 1, "results": "nope"}',
        '{"results": [{"id": 1}]}',
    ],
)
def test_corrupt_cache_file_is_ignored(fake: FakeTime, cache_dir: Path, garbage: str) -> None:
    backend = fs_paged_backend(5)
    client = make_freesound_client(backend, fake, cache_dir)
    list(client.search_tracks(limit=5))
    (entry,) = cache_files(cache_dir)
    entry.write_text(garbage, encoding="utf-8")
    assert len(list(client.search_tracks(limit=5))) == 5
    assert len(backend.requests) == 2
    json.loads(entry.read_text(encoding="utf-8"))  # healed with valid JSON


def test_empty_pages_are_never_cached(fake: FakeTime, cache_dir: Path) -> None:
    backend = Backend(lambda request, n: json_response(search_page([])))
    client = make_freesound_client(backend, fake, cache_dir)
    assert list(client.search_tracks(limit=5)) == []
    assert cache_files(cache_dir) == []
    assert list(client.search_tracks(limit=5)) == []
    assert len(backend.requests) == 2


def test_use_cache_false_disables_read_and_write(fake: FakeTime, cache_dir: Path) -> None:
    backend = fs_paged_backend(5)
    client = make_freesound_client(backend, fake, cache_dir, use_cache=False)
    list(client.search_tracks(limit=5))
    list(client.search_tracks(limit=5))
    assert len(backend.requests) == 2
    assert cache_files(cache_dir) == []


def test_no_cache_dir_means_no_files(fake: FakeTime, tmp_path: Path) -> None:
    backend = fs_paged_backend(5)
    client = make_freesound_client(backend, fake, None)
    list(client.search_tracks(limit=5))
    list(client.search_tracks(limit=5))
    assert len(backend.requests) == 2
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


def test_get_tracks_bypasses_cache_by_default(fake: FakeTime, cache_dir: Path) -> None:
    backend = Backend(lambda request, n: json_response(search_page([sound_json(1)])))
    client = make_freesound_client(backend, fake, cache_dir)
    client.get_tracks([1])
    client.get_tracks([1])
    assert len(backend.requests) == 2
    assert cache_files(cache_dir) == []
    client.get_tracks([1], use_cache=True)
    client.get_tracks([1], use_cache=True)
    assert len(backend.requests) == 3


# -- usage counter ---------------------------------------------------------------------


def test_usage_counts_real_requests_per_day(fake: FakeTime, cache_dir: Path) -> None:
    backend = fs_paged_backend(1000)
    client = make_freesound_client(backend, fake, cache_dir)
    assert client.usage() == {"day": "2025-10-09", "requests": 0, "cache_hits": 0}
    list(client.search_tracks(limit=300))
    assert client.usage() == {"day": "2025-10-09", "requests": 2, "cache_hits": 0}
    assert json.loads((cache_dir / "usage.json").read_text()) == client.usage()


def test_usage_resets_when_the_day_changes(fake: FakeTime, cache_dir: Path) -> None:
    backend = fs_paged_backend(1000)
    client = make_freesound_client(backend, fake, cache_dir)
    list(client.search_tracks(limit=5))
    list(client.search_tracks(limit=5))  # a cache hit
    assert client.usage() == {"day": "2025-10-09", "requests": 1, "cache_hits": 1}
    # 08:53:20 UTC + 16 h: after midnight UTC, still inside the 7-day cache ttl
    fake.now += 16 * 3600
    assert client.usage() == {"day": "2025-10-10", "requests": 0, "cache_hits": 0}
    list(client.search_tracks(limit=7))
    assert client.usage() == {"day": "2025-10-10", "requests": 1, "cache_hits": 0}
    list(client.search_tracks(limit=7))
    assert client.usage() == {"day": "2025-10-10", "requests": 1, "cache_hits": 1}


def test_usage_stays_within_the_same_day(fake: FakeTime, cache_dir: Path) -> None:
    client = make_freesound_client(fs_paged_backend(1000), fake, cache_dir)
    list(client.search_tracks(limit=5))
    fake.now += 10 * 3600  # 18:53, same day
    list(client.search_tracks(limit=6))
    assert client.usage()["requests"] == 2


def test_usage_counts_failed_attempts_and_persists_across_clients(
    fake: FakeTime, cache_dir: Path
) -> None:
    backend = Backend(lambda request, n: httpx.Response(500))
    client = make_freesound_client(backend, fake, cache_dir)
    with pytest.raises(FreesoundError):
        list(client.search_tracks(limit=1))
    assert client.usage()["requests"] == 3
    other = make_freesound_client(fs_paged_backend(1), fake, cache_dir)
    assert other.usage()["requests"] == 3
    list(other.search_tracks(limit=1))
    assert other.usage()["requests"] == 4


def test_usage_in_memory_without_cache_dir(fake: FakeTime) -> None:
    client = make_freesound_client(fs_paged_backend(1), fake, None)
    list(client.search_tracks(limit=1))
    assert client.usage() == {"day": "2025-10-09", "requests": 1, "cache_hits": 0}


@pytest.mark.parametrize(
    "content",
    [
        "{{{",
        "[]",
        '{"day": "2025-10-09", "requests": -4}',
        '{"day": "2025-10-09", "requests": "x"}',
        '{"day": "2025-10-08", "requests": 50}',
    ],
)
def test_corrupt_or_old_usage_file_resets(fake: FakeTime, cache_dir: Path, content: str) -> None:
    cache_dir.mkdir(parents=True)
    (cache_dir / "usage.json").write_text(content, encoding="utf-8")
    client = make_freesound_client(fs_paged_backend(1), fake, cache_dir)
    assert client.usage()["requests"] == 0
    list(client.search_tracks(limit=1))
    assert client.usage()["requests"] == 1


def test_usage_warning_when_passing_threshold(
    fake: FakeTime, cache_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cache_dir.mkdir(parents=True)
    (cache_dir / "usage.json").write_text(
        json.dumps({"day": "2025-10-09", "requests": 1_499, "cache_hits": 0}), encoding="utf-8"
    )
    client = make_freesound_client(fs_paged_backend(1000), fake, cache_dir)
    with caplog.at_level(logging.WARNING, logger="mcrar.sources.freesound"):
        list(client.search_tracks(limit=300))  # request 1,500 is not over yet, 1,501 is
    warnings = [r for r in caplog.records if "usage" in r.getMessage().lower()]
    assert len(warnings) == 1
    assert "1501" in warnings[0].getMessage()


def test_custom_usage_threshold(
    fake: FakeTime, cache_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    client = make_freesound_client(fs_paged_backend(1000), fake, cache_dir, usage_warn_threshold=1)
    with caplog.at_level(logging.WARNING, logger="mcrar.sources.freesound"):
        list(client.search_tracks(limit=300))
    assert len([r for r in caplog.records if "usage" in r.getMessage().lower()]) == 1


# -- from_settings ---------------------------------------------------------------------


def test_from_settings_missing_secret_is_helpful() -> None:
    settings = Settings()
    with pytest.raises(FreesoundError) as info:
        FreesoundClient.from_settings(settings, SecretStore(settings))
    assert "mcrar secrets set freesound_api_key" in str(info.value)


def test_from_settings_uses_secret_and_cache_dir(
    fake: FakeTime, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCRAR_SECRET_FREESOUND_API_KEY", SECRET)
    settings = Settings()
    backend = fs_paged_backend(3)
    client = FreesoundClient.from_settings(
        settings, transport=backend.transport, clock=fake.clock, sleep=fake.sleep
    )
    assert SECRET not in repr(client)
    assert len(list(client.search_tracks(limit=3))) == 3
    assert backend.requests[0].headers["Authorization"] == f"Token {SECRET}"
    expected = settings.cache_dir / "freesound"
    assert (expected / "usage.json").is_file()
    assert len(cache_files(expected)) == 1


def test_from_settings_default_secret_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCRAR_SECRET_FREESOUND_API_KEY", SECRET)
    client = FreesoundClient.from_settings(Settings())
    client.close()
    monkeypatch.delenv("MCRAR_SECRET_FREESOUND_API_KEY")
    with pytest.raises(FreesoundError, match="mcrar secrets set freesound_api_key"):
        FreesoundClient.from_settings(Settings())
