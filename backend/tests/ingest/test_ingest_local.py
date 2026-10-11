"""Local-folder source: scan_local (sidecars, hashing, ordering) and ingest_local."""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path

import pytest
from ingest_support import FakeAnalyzer, RecordingStage, write_audio

from mcrar.audio import ANALYSIS_VERSION
from mcrar.catalog import CatalogRepository
from mcrar.ingest import AnalysisStage, IngestEvent, IngestReport, ingest_local
from mcrar.sources import scan_local

SIDECAR = "mcrar-license.toml"


def _sidecar(folder: Path, text: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / SIDECAR
    path.write_text(text, encoding="utf-8")
    return path


def _by_name(root: Path, **kwargs: str | None) -> dict:
    return {item.path.name: item for item in scan_local(root, **kwargs)}


def _ingest(root: Path, repo: CatalogRepository, analyzer: FakeAnalyzer, **kwargs) -> IngestReport:  # noqa: ANN003
    return ingest_local(root, repo, stages=[AnalysisStage(analyzer)], **kwargs)


# -- scan_local: licences -------------------------------------------------------------------


def test_nearest_sidecar_wins(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    _sidecar(root, 'license = "CC0"\n')
    _sidecar(root / "sub", 'license = "CC-BY-4.0"\n')
    write_audio(root / "a.wav", 100)
    write_audio(root / "sub" / "b.wav", 110)
    write_audio(root / "sub" / "deeper" / "c.wav", 120)
    write_audio(root / "other" / "d.wav", 130)
    items = _by_name(root)
    assert items["a.wav"].license.family == "cc0"
    assert items["b.wav"].license.family == "cc-by"
    assert items["c.wav"].license.family == "cc-by"  # inherited from sub/
    assert items["d.wav"].license.family == "cc0"  # inherited from the root
    assert items["a.wav"].license.risk == "green"


def test_sidecar_above_the_root_is_ignored(tmp_path: Path) -> None:
    _sidecar(tmp_path, 'license = "CC0"\n')
    write_audio(tmp_path / "lib" / "a.wav")
    (item,) = scan_local(tmp_path / "lib")
    assert item.license.family == "unknown"


def test_no_sidecar_means_unknown_license(tmp_path: Path) -> None:
    write_audio(tmp_path / "a.wav")
    (item,) = scan_local(tmp_path)
    assert item.license.family == "unknown" and item.license.risk == "unknown"
    assert item.attribution_extra is None


def test_license_url_and_metadata_from_sidecar(tmp_path: Path) -> None:
    _sidecar(
        tmp_path / "pack",
        'license = "https://creativecommons.org/licenses/by/4.0/"\n'
        'artist = "X"\npack = "Pack name"\nsource_url = "https://x.example/pack"\n'
        'attribution = "Music by X (https://x.example)"\n',
    )
    write_audio(tmp_path / "pack" / "song.flac")
    (item,) = scan_local(tmp_path)
    assert item.license.family == "cc-by" and item.license.version == "4.0"
    track = item.source_track
    assert (track.artist, track.album) == ("X", "Pack name")
    assert track.source_url == "https://x.example/pack"
    assert item.attribution_extra == "Music by X (https://x.example)"


@pytest.mark.parametrize(
    ("flags", "risk"),
    [
        ("commercial_ok = true\nderivatives_ok = true\nattribution_required = false", "green"),
        ("commercial_ok = true\nderivatives_ok = false\nattribution_required = false", "red"),
        ("commercial_ok = false\nderivatives_ok = true\nattribution_required = true", "red"),
        (
            "commercial_ok = true\nderivatives_ok = true\nattribution_required = true\n"
            "share_alike = true",
            "amber",
        ),
    ],
)
def test_custom_license_risk(tmp_path: Path, flags: str, risk: str) -> None:
    body = 'license = "custom"\nname = "Unity Asset Store EULA"\nshare_alike = false\n'
    if "share_alike" in flags:
        body = 'license = "custom"\nname = "Unity Asset Store EULA"\n'
    _sidecar(tmp_path, body + flags + "\n")
    write_audio(tmp_path / "a.wav")
    (item,) = scan_local(tmp_path)
    lic = item.license
    assert (lic.family, lic.code, lic.risk) == ("custom", "Unity Asset Store EULA", risk)
    assert lic.attribution_required is ("attribution_required = true" in flags)


def test_license_override_replaces_licenses_but_keeps_metadata(tmp_path: Path) -> None:
    _sidecar(tmp_path / "pack", 'license = "CC-BY-NC-4.0"\nartist = "X"\npack = "P"\n')
    write_audio(tmp_path / "pack" / "a.wav", 100)
    write_audio(tmp_path / "loose" / "b.wav", 110)  # no sidecar: the override still applies
    items = _by_name(tmp_path, license_override="CC0")
    assert items["a.wav"].license.family == "cc0"
    assert items["b.wav"].license.family == "cc0"
    assert (items["a.wav"].source_track.artist, items["a.wav"].source_track.album) == ("X", "P")


def test_license_override_applies_over_an_invalid_sidecar(tmp_path: Path) -> None:
    _sidecar(tmp_path, "this is = not [toml")
    write_audio(tmp_path / "a.wav")
    (item,) = scan_local(tmp_path, license_override="CC0")
    assert item.license.family == "cc0"


def test_unrecognised_override_and_missing_folder_fail_immediately(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unrecognised license"):
        scan_local(tmp_path, license_override="not-a-license")
    with pytest.raises(NotADirectoryError):
        scan_local(tmp_path / "missing")


@pytest.mark.parametrize(
    "text",
    [
        "this is = not [toml",
        "license = 5\n",
        'license = "CC0"\nartist = 7\n',
        'license = "custom"\ncommercial_ok = true\nderivatives_ok = true\n',  # flags missing
        'license = "custom"\ncommercial_ok = "yes"\nderivatives_ok = true\n'
        "attribution_required = false\nshare_alike = false\n",
    ],
)
def test_invalid_sidecar_gives_unknown_and_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, text: str
) -> None:
    _sidecar(tmp_path, 'license = "CC0"\n')  # the parent's valid sidecar must not leak down
    bad = _sidecar(tmp_path / "bad", text)
    write_audio(tmp_path / "bad" / "inner" / "a.wav", 100)
    write_audio(tmp_path / "good.wav", 110)
    with caplog.at_level(logging.WARNING, logger="mcrar.sources.local_folder"):
        items = _by_name(tmp_path)
    assert items["a.wav"].license.risk == "unknown"
    assert items["a.wav"].license.family == "unknown"
    assert items["a.wav"].source_track.artist is None
    assert items["good.wav"].license.family == "cc0"  # the rest of the scan is unaffected
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and str(bad) in warnings[0]


def test_unrecognised_license_code_warns_but_keeps_the_metadata(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _sidecar(tmp_path, 'license = "whatever"\nartist = "X"\n')
    write_audio(tmp_path / "a.wav")
    with caplog.at_level(logging.WARNING, logger="mcrar.sources.local_folder"):
        (item,) = scan_local(tmp_path)
    assert item.license.family == "unknown" and item.source_track.artist == "X"
    assert "whatever" in caplog.text


# -- scan_local: files -----------------------------------------------------------------------


def test_source_track_fields(tmp_path: Path) -> None:
    path = write_audio(tmp_path / "Pack One" / "My Song.WAV", 100, seconds=6)
    (item,) = scan_local(tmp_path)
    track = item.source_track
    assert item.path == path.resolve()
    assert track.source == "local"
    assert track.source_id == hashlib.sha256(path.read_bytes()).hexdigest()
    assert (track.title, track.album, track.artist) == ("My Song", "Pack One", None)
    assert track.local_path == str(path.resolve())
    assert track.duration_s == pytest.approx(6.0, abs=0.01)
    assert (track.stream_url, track.download_url, track.license_url) == (None, None, None)


def test_non_audio_and_hidden_files_are_ignored(tmp_path: Path) -> None:
    write_audio(tmp_path / "keep.wav", 100)
    write_audio(tmp_path / "upper.FLAC", 101)
    write_audio(tmp_path / ".hidden.wav", 102)
    write_audio(tmp_path / ".hiddendir" / "x.wav", 103)
    write_audio(tmp_path / "sub" / ".also" / "y.wav", 104)
    (tmp_path / "notes.txt").write_text("hello")
    (tmp_path / "cover.jpg").write_bytes(b"\xff\xd8")
    (tmp_path / "song.m4a").write_bytes(b"x")
    assert sorted(_by_name(tmp_path)) == ["keep.wav", "upper.FLAC"]


def test_unreadable_file_is_skipped_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mcrar.sources import local_folder

    write_audio(tmp_path / "a.wav", 100)
    write_audio(tmp_path / "b.wav", 110)
    real = local_folder.file_sha256

    def flaky(path: Path) -> str:
        if path.name == "a.wav":
            raise PermissionError("denied")
        return real(path)

    monkeypatch.setattr(local_folder, "file_sha256", flaky)
    with caplog.at_level(logging.WARNING, logger="mcrar.sources.local_folder"):
        names = [i.path.name for i in scan_local(tmp_path)]
    assert names == ["b.wav"]
    assert "a.wav" in caplog.text


def test_scan_order_is_deterministic_and_sorted(tmp_path: Path) -> None:
    for i, rel in enumerate(["z.wav", "b/2.wav", "a.flac", "b/1.wav", "a/x/deep.wav", "m.wav"]):
        write_audio(tmp_path / rel, 100 + i)
    first = [i.path.relative_to(tmp_path.resolve()).as_posix() for i in scan_local(tmp_path)]
    second = [i.path.relative_to(tmp_path.resolve()).as_posix() for i in scan_local(tmp_path)]
    assert first == second == ["a.flac", "m.wav", "z.wav", "a/x/deep.wav", "b/1.wav", "b/2.wav"]


# -- ingest_local ----------------------------------------------------------------------------


def test_ingest_stores_license_attribution_and_features(
    tmp_path: Path, repo: CatalogRepository
) -> None:
    root = tmp_path / "lib"
    _sidecar(root, 'license = "CC-BY-4.0"\nartist = "X"\nattribution = "Music by X"\n')
    write_audio(root / "song.wav", 100)
    analyzer = FakeAnalyzer()
    report = _ingest(root, repo, analyzer)
    assert (report.seen, report.new, report.processed, report.failed) == (1, 1, 1, 0)
    (track,) = list(repo.iter_tracks("local"))
    assert (track.title, track.artist, track.album) == ("song", "X", "lib")
    assert (track.risk, track.license_family) == ("green", "cc-by")
    assert track.attribution_text is not None
    assert track.attribution_text.endswith(
        "licensed under CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/) Music by X"
    )  # noqa: E501
    assert track.audiodownload_allowed is False or track.audiodownload_allowed is None
    assert repo.features_version(track.id) == ANALYSIS_VERSION
    assert analyzer.sources == [(root / "song.wav").resolve()]  # analysed straight from the path


def test_license_override_through_ingest(tmp_path: Path, repo: CatalogRepository) -> None:
    write_audio(tmp_path / "lib" / "a.wav")
    _ingest(tmp_path / "lib", repo, FakeAnalyzer(), license_override="CC0")
    (track,) = list(repo.iter_tracks("local"))
    assert (track.license_family, track.risk, track.commercial_ok) == ("cc0", "green", True)


def test_duplicate_content_gives_one_track(tmp_path: Path, repo: CatalogRepository) -> None:
    write_audio(tmp_path / "a" / "song.wav", 100)
    shutil.copy(tmp_path / "a" / "song.wav", tmp_path / "copy.wav")
    analyzer = FakeAnalyzer()
    report = _ingest(tmp_path, repo, analyzer)
    assert repo.stats()["tracks"] == 1
    assert (report.seen, report.new, report.processed, report.skipped) == (2, 1, 1, 1)
    assert analyzer.calls == 1


def test_moved_file_updates_local_path_and_is_not_reanalysed(
    tmp_path: Path, repo: CatalogRepository
) -> None:
    old = write_audio(tmp_path / "old" / "song.wav", 100)
    _ingest(tmp_path, repo, FakeAnalyzer())
    (before,) = list(repo.iter_tracks("local"))
    new = tmp_path / "new" / "renamed.wav"
    new.parent.mkdir()
    old.rename(new)
    analyzer = FakeAnalyzer()
    report = _ingest(tmp_path, repo, analyzer)
    (after,) = list(repo.iter_tracks("local"))
    assert after.id == before.id
    assert after.local_path == str(new.resolve())
    assert after.title == "renamed"
    assert (report.new, report.updated, report.skipped, analyzer.calls) == (0, 1, 1, 0)


def test_changed_content_is_a_new_track(tmp_path: Path, repo: CatalogRepository) -> None:
    write_audio(tmp_path / "song.wav", 100)
    _ingest(tmp_path, repo, FakeAnalyzer())
    write_audio(tmp_path / "song.wav", 140)
    report = _ingest(tmp_path, repo, FakeAnalyzer())
    assert (report.new, report.processed) == (1, 1)
    assert repo.stats()["tracks"] == 2


def test_rerun_skips_and_force_reanalyses(tmp_path: Path, repo: CatalogRepository) -> None:
    write_audio(tmp_path / "a.wav", 100)
    write_audio(tmp_path / "b.wav", 110)
    _ingest(tmp_path, repo, FakeAnalyzer())
    again = FakeAnalyzer()
    assert _ingest(tmp_path, repo, again).skipped == 2 and again.calls == 0
    forced = FakeAnalyzer()
    report = _ingest(tmp_path, repo, forced, force=True)
    assert (report.processed, report.skipped, forced.calls) == (2, 0, 2)


def test_corrupt_audio_is_failed_and_the_run_continues(
    tmp_path: Path, repo: CatalogRepository
) -> None:
    write_audio(tmp_path / "a_good.wav", 100, seconds=6)
    (tmp_path / "b_corrupt.wav").write_bytes(b"RIFF" + b"\x00" * 200)
    (tmp_path / "c_junk.flac").write_bytes(b"this is not audio at all" * 20)
    write_audio(tmp_path / "d_good.flac", 120, seconds=6)
    # Real analysis here: the failure comes from the real decoder.
    report = ingest_local(tmp_path, repo)
    assert (report.seen, report.processed, report.failed) == (4, 2, 2), report.failures
    assert {f.title for f in report.failures} == {"b_corrupt", "c_junk"}
    assert all(f.stage == "analysis" and f.message.startswith("Audio") for f in report.failures)
    assert len(repo.failed_items("analysis")) == 2
    corrupt = next(t for t in repo.iter_tracks("local") if t.title == "b_corrupt")
    assert corrupt.duration_s is None  # probing failed; the failure surfaced at analysis time
    good = next(t for t in repo.iter_tracks("local") if t.title == "a_good")
    features = repo.get_features(good.id)
    assert features is not None and features["analysis_version"] == ANALYSIS_VERSION
    assert good.duration_s == pytest.approx(6.0, abs=0.01)


def test_progress_events_and_total(tmp_path: Path, repo: CatalogRepository) -> None:
    write_audio(tmp_path / "a.wav", 100)
    write_audio(tmp_path / "b.wav", 110)
    events: list[IngestEvent] = []
    _ingest(tmp_path, repo, FakeAnalyzer(), on_progress=events.append)
    assert [e.kind for e in events] == ["started", "track_done", "track_done", "finished"]
    assert [e.title for e in events[1:3]] == ["a", "b"]
    assert all(e.total == 2 for e in events)


def test_interrupt_returns_partial_report_and_rerun_resumes(
    tmp_path: Path, repo: CatalogRepository
) -> None:
    for i, name in enumerate(["a", "b", "c"]):
        write_audio(tmp_path / f"{name}.wav", 100 + 10 * i)
    report = _ingest(tmp_path, repo, FakeAnalyzer(errors={2: KeyboardInterrupt()}))
    assert report.aborted == "interrupted" and report.processed == 1
    resumed = _ingest(tmp_path, repo, FakeAnalyzer())
    assert (resumed.skipped, resumed.processed) == (1, 2)


def test_second_stage_gets_the_path(tmp_path: Path, repo: CatalogRepository) -> None:
    write_audio(tmp_path / "a.wav")
    analyzer = FakeAnalyzer()
    extra = RecordingStage()
    ingest_local(tmp_path, repo, stages=[AnalysisStage(analyzer), extra])
    assert analyzer.calls == 1 and len(extra.done) == 1
    assert extra.audio_types and issubclass(extra.audio_types[0], Path)


def test_empty_folder(tmp_path: Path, repo: CatalogRepository) -> None:
    report = _ingest(tmp_path, repo, FakeAnalyzer())
    assert (report.seen, report.processed, report.failed, report.aborted) == (0, 0, 0, None)
