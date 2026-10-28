"""`mcrar ingest freesound` through the CLI runner (fake client, no network)."""

from __future__ import annotations

from typing import Any

import pytest
from ingest_support import FakeAnalyzer, FakeClient
from test_ingest_freesound_pipeline import CC0, fs_track
from typer.testing import CliRunner

from mcrar import cli
from mcrar.cli import app
from mcrar.ingest import pipeline
from mcrar.sources import FreesoundAuthError

runner = CliRunner()


class FreesoundFake(FakeClient):
    def usage(self) -> dict[str, Any]:
        return {"day": "2026-10-27", "requests": 4, "cache_hits": 1}


@pytest.fixture(autouse=True)
def analysis_only(monkeypatch: pytest.MonkeyPatch) -> FakeAnalyzer:
    monkeypatch.setattr(cli, "_ingest_embed_keys", lambda embed, no_embed, settings: [])
    fake = FakeAnalyzer()
    monkeypatch.setattr(pipeline, "analyze_audio", fake)
    return fake


def _use_client(monkeypatch: pytest.MonkeyPatch, client: FakeClient) -> list[bool]:
    use_cache: list[bool] = []

    def factory(settings: object, cache: bool) -> FakeClient:
        use_cache.append(cache)
        return client

    monkeypatch.setattr(cli, "_freesound_client", factory)
    return use_cache


def test_the_options_become_the_client_search(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FreesoundFake([fs_track(1), fs_track(2, license_url=CC0)])
    use_cache = _use_client(monkeypatch, client)
    result = runner.invoke(
        app,
        ["ingest", "freesound", "--query", "calm pad", "--tag", "Loop", "--tag", "warm",
         "--license", "cc0", "--license", "sampling+", "--min-duration", "20",
         "--max-duration", "90", "--sort", "downloads_desc", "--limit", "2", "--no-cache"],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert client.search_kwargs == [
        {
            "query": "calm pad",
            "tags": ["Loop", "warm"],
            "licenses": ["cc0", "sampling+"],
            "duration_min_s": 20.0,
            "duration_max_s": 90.0,
            "sort": "downloads_desc",
            "limit": 2,
        }
    ]
    assert use_cache == [False] and client.closed
    assert "[1/2] ok  Sound 1 — 120 BPM C major (green)" in result.output
    assert "[2/2] ok  Sound 2 — 120 BPM C major (green)" in result.output
    assert "2 seen (2 new, 0 updated), 2 processed, 0 skipped, 0 failed" in result.output
    assert "Freesound API requests on 2026-10-27: 4" in result.output


def test_the_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FreesoundFake([fs_track(1)])
    use_cache = _use_client(monkeypatch, client)
    result = runner.invoke(app, ["ingest", "freesound", "--tag", "ambient"])
    assert result.exit_code == 0, result.output
    assert client.search_kwargs == [
        {
            "query": "",
            "tags": ["ambient"],
            "licenses": ["cc0", "by"],
            "duration_min_s": 10.0,
            "duration_max_s": 600.0,
            "sort": "score",
            "limit": 50,
        }
    ]
    assert use_cache == [True]
    again = runner.invoke(app, ["ingest", "freesound", "--tag", "ambient"])
    assert "[1/50] skip  Sound 1 — up to date" in again.output  # the total is the limit


def test_force_reanalyses(monkeypatch: pytest.MonkeyPatch, analysis_only: FakeAnalyzer) -> None:
    _use_client(monkeypatch, FreesoundFake([fs_track(1)]))
    runner.invoke(app, ["ingest", "freesound", "--query", "rain"])
    forced = runner.invoke(app, ["ingest", "freesound", "--query", "rain", "--force"])
    assert forced.exit_code == 0 and "1 processed" in forced.output
    assert analysis_only.calls == 2


def test_a_search_needs_a_query_or_a_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_client(monkeypatch, FreesoundFake([]))
    result = runner.invoke(app, ["ingest", "freesound"])
    assert result.exit_code == 2 and "--query or at least one --tag" in result.stderr


@pytest.mark.parametrize(
    "args",
    [
        ["--license", "gpl"],
        ["--tag", "has space"],
        ["--sort", "random"],
        ["--min-duration", "100", "--max-duration", "50"],
    ],
)
def test_bad_options_fail_before_the_client_is_built(args: list[str]) -> None:
    # No client is faked: building the real one without a key would give another error.
    result = runner.invoke(app, ["ingest", "freesound", "--query", "rain", *args])
    assert result.exit_code == 2, result.output
    assert "API key" not in result.stderr and "Traceback" not in result.output


def test_a_missing_key_gives_a_helpful_one_line_error() -> None:
    result = runner.invoke(app, ["ingest", "freesound", "--query", "rain"])
    assert result.exit_code == 1
    lines = result.stderr.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("error: No Freesound API key is configured")
    assert "mcrar secrets set freesound_api_key" in lines[0]


def test_an_auth_error_exits_1_after_the_partial_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FreesoundFake(
        [fs_track(1), fs_track(2)], fetch_errors={"2": FreesoundAuthError("key rejected")}
    )
    _use_client(monkeypatch, client)
    result = runner.invoke(app, ["ingest", "freesound", "--query", "rain", "--limit", "2"])
    assert result.exit_code == 1
    assert result.stderr.strip() == "error: key rejected"
    assert "[1/2] ok  Sound 1" in result.stdout and "1 processed" in result.stdout
    assert "Traceback" not in result.output and client.closed


def test_the_command_is_listed_and_documents_its_options() -> None:
    listed = runner.invoke(app, ["ingest", "--help"])
    assert "freesound" in listed.output
    helped = runner.invoke(app, ["ingest", "freesound", "--help"])
    for option in ("--query", "--tag", "--license", "--min-duration", "--max-duration", "--sort"):
        assert option in helped.output
    for option in ("--limit", "--force", "--no-cache", "--embed", "--no-embed"):
        assert option in helped.output
