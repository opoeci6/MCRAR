"""`mcrar ingest ...` and `mcrar catalog ...` through the CLI runner (no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ingest_support import CC_BY_NC_ND, FakeAnalyzer, FakeClient, make_track, write_audio
from typer.testing import CliRunner

from mcrar import cli
from mcrar.audio import AudioDecodeError
from mcrar.catalog import TrackRecord, open_catalog
from mcrar.cli import app
from mcrar.config import get_settings
from mcrar.ingest import pipeline
from mcrar.sources import JamendoAuthError, JamendoStreamError

runner = CliRunner()


@pytest.fixture(autouse=True)
def analysis_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ingest` now embeds by default (M4); these tests are about analysis and must not load a
    model, so they run as if `--no-embed` were given. The default is tested in
    test_recommend_cli.py."""
    monkeypatch.setattr(cli, "_ingest_embed_keys", lambda embed, no_embed, settings: [])


@pytest.fixture
def analyzer(monkeypatch: pytest.MonkeyPatch) -> FakeAnalyzer:
    fake = FakeAnalyzer()
    monkeypatch.setattr(pipeline, "analyze_audio", fake)
    return fake


def _use_client(monkeypatch: pytest.MonkeyPatch, client: FakeClient) -> list[bool]:
    use_cache: list[bool] = []

    def factory(settings: object, cache: bool) -> FakeClient:
        use_cache.append(cache)
        return client

    monkeypatch.setattr(cli, "_jamendo_client", factory)
    return use_cache


def test_ingest_jamendo_prints_progress_and_summary(
    monkeypatch: pytest.MonkeyPatch, analyzer: FakeAnalyzer
) -> None:
    client = FakeClient([make_track(1), make_track(2, license_url=CC_BY_NC_ND)])
    use_cache = _use_client(monkeypatch, client)
    result = runner.invoke(
        app,
        ["ingest", "jamendo", "--tags", "rock, indie", "--instrumental", "--limit", "2",
         "--commercial-only", "--order", "popularity_month", "--no-cache"],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert "[1/2] ok  Track 1 — 120 BPM C major (green)" in result.output
    assert "[2/2] ok  Track 2 — 120 BPM C major (red)" in result.output
    assert "2 seen (2 new, 0 updated), 2 processed, 0 skipped, 0 failed" in result.output
    assert "Jamendo API requests in 2026-10: 7" in result.output
    assert use_cache == [False]
    assert client.closed
    assert client.search_kwargs == [
        {
            "tags": ["rock", "indie"],
            "vocalinstrumental": "instrumental",
            "commercial_only": True,
            "order": "popularity_month",
            "limit": 2,
        }
    ]
    # the rerun skips
    again = runner.invoke(app, ["ingest", "jamendo", "--limit", "2"])
    assert again.exit_code == 0
    assert "[1/2] skip  Track 1 — up to date" in again.output
    assert "2 skipped" in again.output


def test_ingest_jamendo_default_limit_and_cache(
    monkeypatch: pytest.MonkeyPatch, analyzer: FakeAnalyzer
) -> None:
    client = FakeClient([make_track(1)])
    use_cache = _use_client(monkeypatch, client)
    result = runner.invoke(app, ["ingest", "jamendo", "--search", "calm"])
    assert result.exit_code == 0, result.output
    assert client.search_kwargs == [{"search": "calm", "limit": 100}]
    assert use_cache == [True]


def test_ingest_jamendo_force(monkeypatch: pytest.MonkeyPatch, analyzer: FakeAnalyzer) -> None:
    _use_client(monkeypatch, FakeClient([make_track(1)]))
    runner.invoke(app, ["ingest", "jamendo", "--limit", "1"])
    forced = runner.invoke(app, ["ingest", "jamendo", "--limit", "1", "--force"])
    assert forced.exit_code == 0 and "1 processed" in forced.output
    assert analyzer.calls == 2


def test_per_track_failures_do_not_change_the_exit_code(
    monkeypatch: pytest.MonkeyPatch, analyzer: FakeAnalyzer
) -> None:
    client = FakeClient(
        [make_track(1), make_track(2), make_track(3)],
        fetch_errors={"2": JamendoStreamError("stream expired")},
    )
    _use_client(monkeypatch, client)
    result = runner.invoke(app, ["ingest", "jamendo", "--limit", "3"])
    assert result.exit_code == 0, result.output
    assert "[2/3] failed: Track 2 — JamendoStreamError: stream expired" in result.output
    assert "2 processed, 0 skipped, 1 failed" in result.output
    assert "failed [analysis] Track 2 (2): JamendoStreamError: stream expired" in result.output


def test_abort_exits_1_with_a_one_line_error(
    monkeypatch: pytest.MonkeyPatch, analyzer: FakeAnalyzer
) -> None:
    client = FakeClient(
        [make_track(1), make_track(2)], fetch_errors={"2": JamendoAuthError("client id rejected")}
    )
    _use_client(monkeypatch, client)
    result = runner.invoke(app, ["ingest", "jamendo", "--limit", "2"])
    assert result.exit_code == 1
    assert result.stderr.strip() == "error: client id rejected"
    assert "[1/2] ok  Track 1" in result.stdout  # the partial summary is still printed
    assert "1 processed" in result.stdout
    assert "Traceback" not in result.output
    assert client.closed


def test_missing_secret_gives_a_helpful_one_line_error() -> None:
    result = runner.invoke(app, ["ingest", "jamendo"])
    assert result.exit_code == 1
    lines = result.stderr.strip().splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("error: No Jamendo client id is configured")
    assert "mcrar secrets set jamendo_client_id" in lines[0]


def test_vocal_and_instrumental_are_exclusive() -> None:
    result = runner.invoke(app, ["ingest", "jamendo", "--vocal", "--instrumental"])
    assert result.exit_code == 2
    assert "mutually exclusive" in result.stderr


def test_keyboard_interrupt_exits_130_after_the_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline, "analyze_audio", FakeAnalyzer(errors={2: KeyboardInterrupt()}))
    _use_client(monkeypatch, FakeClient([make_track(1), make_track(2), make_track(3)]))
    result = runner.invoke(app, ["ingest", "jamendo", "--limit", "3"])
    assert result.exit_code == 130
    assert "Finished (interrupted)" in result.stdout
    assert "1 processed" in result.stdout


def test_ingest_local_with_license(tmp_path: Path) -> None:
    folder = tmp_path / "lib"
    write_audio(folder / "song.wav", 120, seconds=6)  # real analysis
    result = runner.invoke(app, ["ingest", "local", str(folder), "--license", "CC0"])
    assert result.exit_code == 0, result.output
    assert "[1/1] ok  song — " in result.output
    assert "BPM" in result.output and "(green)" in result.output
    assert "1 seen (1 new, 0 updated), 1 processed" in result.output
    again = runner.invoke(app, ["ingest", "local", str(folder), "--license", "CC0"])
    assert again.exit_code == 0 and "[1/1] skip  song — up to date" in again.output
    show = runner.invoke(app, ["catalog", "show", "1", "--json"])
    data = json.loads(show.stdout)
    assert data["track"]["license_family"] == "cc0"
    assert data["features"]["analysis_version"] == "audio-v2"


def test_ingest_local_reports_failures_but_exits_0(tmp_path: Path) -> None:
    folder = tmp_path / "lib"
    write_audio(folder / "good.wav", 120)
    (folder / "bad.wav").write_bytes(b"RIFF" + b"\x00" * 100)
    result = runner.invoke(app, ["ingest", "local", str(folder)])
    assert result.exit_code == 0, result.output
    assert "1 processed, 0 skipped, 1 failed" in result.output
    assert "failed: bad —" in result.output


def test_ingest_local_bad_arguments(tmp_path: Path) -> None:
    missing = runner.invoke(app, ["ingest", "local", str(tmp_path / "nope")])
    assert missing.exit_code == 1 and missing.stderr.startswith("error: folder not found")
    (tmp_path / "lib").mkdir()
    bad = runner.invoke(app, ["ingest", "local", str(tmp_path / "lib"), "--license", "bogus"])
    assert bad.exit_code == 2 and "unrecognised license" in bad.stderr


def test_ingest_local_keyboard_interrupt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "analyze_audio", FakeAnalyzer(errors={1: KeyboardInterrupt()}))
    write_audio(tmp_path / "lib" / "a.wav")
    result = runner.invoke(app, ["ingest", "local", str(tmp_path / "lib")])
    assert result.exit_code == 130
    assert "Finished (interrupted)" in result.stdout


# -- catalog -------------------------------------------------------------------------------------


def _seed() -> None:
    """Two tracks: one analysed, one with a failed analysis (written straight to the catalog)."""
    with open_catalog(get_settings()) as repo:
        ok = repo.upsert_track(
            TrackRecord(
                source="jamendo",
                source_id="11",
                title="Garnet",
                artist="Ken",
                duration_s=310.0,
                source_url="https://www.jamendo.com/track/11",
                license_url="https://creativecommons.org/licenses/by-nc-nd/3.0/",
                license_code="CC BY-NC-ND 3.0",
                license_family="cc-by-nc-nd",
                risk="red",
                commercial_ok=False,
                derivatives_ok=False,
                share_alike=False,
                attribution_required=True,
                attribution_text='"Garnet" by Ken',
                commercial_license_url="https://licensing.jamendo.com/track/11",
            )
        )
        repo.set_features(ok, _features())
        repo.log_ingest("jamendo", "11", "analysis", "ok", track_id=ok)
        bad = repo.upsert_track(TrackRecord(source="jamendo", source_id="12", title="Broken"))
        repo.log_ingest("jamendo", "12", "analysis", "failed", "AudioDecodeError: bad", bad)
        repo.log_ingest("jamendo", "12", "embedding", "failed", "RuntimeError: no gpu", bad)


def _features() -> dict:
    return FakeAnalyzer()(b"").to_dict()


def test_catalog_stats_plain_and_json() -> None:
    _seed()
    plain = runner.invoke(app, ["catalog", "stats"])
    assert plain.exit_code == 0, plain.output
    assert "Tracks:           2" in plain.stdout
    assert "jamendo=2" in plain.stdout
    assert "With features:    1 (50%)" in plain.stdout
    assert "analysis=1, embedding=1" in plain.stdout
    data = json.loads(runner.invoke(app, ["catalog", "stats", "--json"]).stdout)
    assert data["tracks"] == 2
    assert data["tracks_by_risk"] == {"red": 1, "unknown": 1}
    assert data["ingest_failures_by_stage"] == {"analysis": 1, "embedding": 1}


def test_catalog_stats_on_an_empty_catalog() -> None:
    result = runner.invoke(app, ["catalog", "stats"])
    assert result.exit_code == 0 and "Tracks:           0" in result.stdout


def test_catalog_show_plain_and_json() -> None:
    _seed()
    plain = runner.invoke(app, ["catalog", "show", "1"])
    assert plain.exit_code == 0, plain.output
    for expected in (
        "Track 1 (jamendo 11)",
        "Garnet",
        "CC BY-NC-ND 3.0  (cc-by-nc-nd)",
        "Risk:        red",
        "Commercial:  no",
        "https://licensing.jamendo.com/track/11",
        "BPM:         120.0",
        "Key:         C major",
        "Version:     audio-v2",
        "analysis: ok (attempts 1)",
    ):
        assert expected in plain.stdout
    data = json.loads(runner.invoke(app, ["catalog", "show", "1", "--json"]).stdout)
    assert data["track"]["title"] == "Garnet" and data["track"]["risk"] == "red"
    assert data["features"]["bpm"] == 120.0
    assert [(e["stage"], e["status"]) for e in data["ingest"]] == [("analysis", "ok")]
    unanalysed = runner.invoke(app, ["catalog", "show", "2"])
    assert "(not analysed)" in unanalysed.stdout
    assert "analysis: failed (attempts 1) - AudioDecodeError: bad" in unanalysed.stdout
    assert (
        json.loads(runner.invoke(app, ["catalog", "show", "2", "--json"]).stdout)["features"]
        is None
    )


def test_catalog_show_unknown_id() -> None:
    result = runner.invoke(app, ["catalog", "show", "99"])
    assert result.exit_code == 1 and result.stderr.strip() == "error: no track with id 99"


def test_catalog_failures_plain_json_and_stage_filter() -> None:
    _seed()
    plain = runner.invoke(app, ["catalog", "failures"])
    assert plain.exit_code == 0
    assert "analysis\tjamendo/12\tattempts=1\tAudioDecodeError: bad" in plain.stdout
    assert "embedding\tjamendo/12" in plain.stdout
    only = runner.invoke(app, ["catalog", "failures", "--stage", "embedding", "--json"])
    rows = json.loads(only.stdout)
    assert [(r["stage"], r["source_id"], r["message"]) for r in rows] == [
        ("embedding", "12", "RuntimeError: no gpu")
    ]
    assert "(no failures)" in runner.invoke(app, ["catalog", "failures", "--stage", "x"]).stdout


def test_ingest_failures_show_up_in_the_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline, "analyze_audio", FakeAnalyzer(errors={1: AudioDecodeError("corrupt")})
    )
    _use_client(monkeypatch, FakeClient([make_track(1)]))
    assert runner.invoke(app, ["ingest", "jamendo", "--limit", "1"]).exit_code == 0
    failures = runner.invoke(app, ["catalog", "failures"])
    assert "AudioDecodeError: corrupt" in failures.stdout
