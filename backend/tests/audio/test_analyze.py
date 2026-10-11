from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
import synth
from typer.testing import CliRunner

from mcrar.audio import ANALYSIS_VERSION, analyze_audio
from mcrar.cli import app

runner = CliRunner()
EXPECTED_FIELDS = {
    "bpm", "bpm_raw", "bpm_confidence", "key", "mode", "key_confidence", "loudness_lufs",
    "rms_db", "energy", "duration_s", "sample_rate", "channels", "analysis_version",
}  # fmt: skip


def test_analyze_120_bpm_c_major(demo_wav: Path) -> None:
    f = analyze_audio(demo_wav)
    assert f.bpm == pytest.approx(120, abs=2)
    assert f.bpm_raw is not None
    assert 0.0 <= f.bpm_confidence <= 1.0
    assert (f.key, f.mode) == ("C", "major")
    assert 0.0 < f.key_confidence <= 1.0
    assert f.loudness_lufs is not None
    assert f.rms_db < 0
    assert 0.0 <= f.energy <= 1.0
    assert f.duration_s == pytest.approx(8.0, abs=0.01)
    assert f.sample_rate == synth.SR
    assert f.channels == 1
    assert f.analysis_version == ANALYSIS_VERSION == "audio-v1"


def test_analyze_is_deterministic(demo_wav: Path) -> None:
    assert analyze_audio(demo_wav) == analyze_audio(demo_wav)
    assert analyze_audio(demo_wav.read_bytes()) == analyze_audio(demo_wav)


def test_to_dict_is_json_safe(demo_wav: Path) -> None:
    d = analyze_audio(demo_wav).to_dict()
    assert json.loads(json.dumps(d, allow_nan=False)) == d
    assert set(d) == EXPECTED_FIELDS


def test_silent_file_gives_nones(tmp_path: Path) -> None:
    path = tmp_path / "silent.wav"
    sf.write(path, synth.silence(3.0), synth.SR)
    f = analyze_audio(path)
    assert f.bpm is None
    assert f.key is None
    assert f.loudness_lufs is None
    assert f.energy == pytest.approx(0.0, abs=0.01)
    json.dumps(f.to_dict(), allow_nan=False)


def test_max_seconds_keeps_whole_file_duration(demo_wav: Path) -> None:
    f = analyze_audio(demo_wav, max_seconds=3)
    assert f.duration_s == pytest.approx(8.0, abs=0.01)


def test_reports_original_format(tmp_path: Path, stereo_44k: np.ndarray) -> None:
    path = tmp_path / "s.wav"
    sf.write(path, stereo_44k, 44100)
    f = analyze_audio(path)
    assert (f.sample_rate, f.channels) == (44100, 2)


def test_cli_json(demo_wav: Path) -> None:
    result = runner.invoke(app, ["analyze", str(demo_wav), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["key"] == "C"
    assert data["analysis_version"] == "audio-v1"
    assert data["bpm"] == pytest.approx(120, abs=2)


def test_cli_table(demo_wav: Path) -> None:
    result = runner.invoke(app, ["analyze", str(demo_wav), "--max-seconds", "5"])
    assert result.exit_code == 0, result.output
    assert "BPM" in result.output
    assert "C major" in result.output
    assert "LUFS" in result.output


def test_cli_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyze", str(tmp_path / "nope.wav")])
    assert result.exit_code == 1
    assert "not found" in result.output
    assert "Traceback" not in result.output


def test_cli_unsupported_file(tmp_path: Path) -> None:
    path = tmp_path / "x.m4a"
    path.write_bytes(b"garbage" * 100)
    result = runner.invoke(app, ["analyze", str(path), "--json"])
    assert result.exit_code == 1
    assert "unsupported audio format" in result.output
    assert "garbage" not in result.output
    assert "Traceback" not in result.output
    assert len(result.output.strip().splitlines()) == 1


def test_cli_truncated_wav(tmp_path: Path) -> None:
    path = tmp_path / "g.wav"
    sf.write(path, synth.sine(440.0, 1.0), synth.SR)
    path.write_bytes(path.read_bytes()[:1000])
    result = runner.invoke(app, ["analyze", str(path)])
    assert result.exit_code == 1
    assert "truncated" in result.output
