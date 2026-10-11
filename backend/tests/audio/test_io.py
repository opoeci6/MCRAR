from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
import synth

from mcrar.audio import (
    AudioDecodeError,
    UnsupportedAudioError,
    load_audio,
    probe_audio,
)

MP3 = "MP3" in sf.available_formats()


def _write(path: Path, y: np.ndarray, sr: int) -> Path:
    sf.write(path, y, sr)
    return path


@pytest.mark.parametrize(
    "ext",
    [
        "wav",
        "flac",
        "ogg",
        pytest.param(
            "mp3", marks=pytest.mark.skipif(not MP3, reason="libsndfile built without MP3")
        ),
    ],
)
def test_round_trip(tmp_path: Path, ext: str) -> None:
    y = synth.sine(440.0, 1.0, sr=44100, amp=0.5)
    path = _write(tmp_path / f"a.{ext}", y, 44100)
    clip = load_audio(path)
    assert clip.samples.dtype == np.float32
    assert clip.sr == clip.original_sr == 44100
    assert clip.channels == 1
    assert abs(len(clip.samples) - len(y)) <= 1200  # lossy codecs pad/trim a little
    assert abs(clip.duration_s - 1.0) < 0.05
    assert float(np.max(np.abs(clip.samples))) <= 1.0
    assert clip.format == ext.upper()
    if ext in ("wav", "flac"):  # lossless
        assert np.allclose(clip.samples, y, atol=1e-3)
    else:  # lossy: the dominant frequency survives
        seg = clip.samples[:44100]
        peak = np.argmax(np.abs(np.fft.rfft(seg))) * 44100 / len(seg)
        assert abs(peak - 440.0) < 5.0


def test_load_from_bytes_and_bytesio(tmp_path: Path) -> None:
    y = synth.sine(330.0, 0.5, sr=22050)
    path = _write(tmp_path / "a.wav", y, 22050)
    raw = path.read_bytes()
    reference = load_audio(path)
    for clip in (load_audio(raw), load_audio(io.BytesIO(raw)), load_audio(str(path))):
        assert np.array_equal(clip.samples, reference.samples)
    assert probe_audio(raw).sr == 22050


def test_stereo_downmixed_by_averaging(tmp_path: Path, stereo_44k: np.ndarray) -> None:
    path = _write(tmp_path / "s.wav", stereo_44k, 44100)
    clip = load_audio(path)
    assert clip.channels == 2
    assert clip.samples.ndim == 1
    assert np.allclose(clip.samples, stereo_44k.mean(axis=1), atol=1e-3)
    kept = load_audio(path, mono=False)
    assert kept.samples.shape == stereo_44k.shape


def test_resample_length(tmp_path: Path, stereo_44k: np.ndarray) -> None:
    path = _write(tmp_path / "s.wav", stereo_44k, 44100)
    clip = load_audio(path, sr=22050)
    assert clip.sr == 22050
    assert clip.original_sr == 44100
    assert abs(len(clip.samples) - len(stereo_44k) // 2) <= 1
    assert clip.samples.dtype == np.float32


def test_max_seconds_truncates_but_keeps_duration(tmp_path: Path) -> None:
    y = synth.sine(440.0, 6.0, sr=22050)
    path = _write(tmp_path / "long.wav", y, 22050)
    clip = load_audio(path, max_seconds=2.0)
    assert len(clip.samples) == 2 * 22050
    assert clip.duration_s == pytest.approx(6.0, abs=1e-3)
    both = load_audio(path, sr=11025, max_seconds=2.0)
    assert abs(len(both.samples) - 2 * 11025) <= 1


def test_probe_reports_header_facts(tmp_path: Path) -> None:
    path = _write(tmp_path / "p.flac", synth.sine(440.0, 3.0, sr=16000), 16000)
    info = probe_audio(path)
    assert (info.sr, info.channels, info.format) == (16000, 1, "FLAC")
    assert info.duration_s == pytest.approx(3.0, abs=1e-3)


def test_garbage_m4a_is_unsupported(tmp_path: Path) -> None:
    path = tmp_path / "song.m4a"
    path.write_bytes(b"SECRETCONTENTS" * 50)
    with pytest.raises(UnsupportedAudioError) as exc:
        load_audio(path)
    assert ".m4a" in str(exc.value)
    assert "SECRETCONTENTS" not in str(exc.value)


def test_unrecognised_bytes_are_unsupported() -> None:
    with pytest.raises(UnsupportedAudioError):
        load_audio(b"not audio at all" * 20)


def test_truncated_wav_is_decode_error(tmp_path: Path) -> None:
    good = _write(tmp_path / "good.wav", synth.sine(440.0, 1.0), synth.SR).read_bytes()
    bad = tmp_path / "bad.wav"
    bad.write_bytes(good[: len(good) // 2])
    with pytest.raises(AudioDecodeError) as exc:
        load_audio(bad)
    assert "truncated" in str(exc.value)
    with pytest.raises(AudioDecodeError):
        load_audio(good[: len(good) // 2])


def test_corrupt_wav_is_decode_error_without_contents(tmp_path: Path) -> None:
    path = tmp_path / "bad.wav"
    path.write_bytes(b"SECRETCONTENTS" * 50)
    with pytest.raises(AudioDecodeError) as exc:
        load_audio(path)
    assert "SECRETCONTENTS" not in str(exc.value)
    assert ".wav" in str(exc.value)


def test_missing_file_raises_audio_error(tmp_path: Path) -> None:
    with pytest.raises(AudioDecodeError):
        load_audio(tmp_path / "nope.wav")


def test_invalid_arguments() -> None:
    with pytest.raises(ValueError, match="max_seconds"):
        load_audio(b"", max_seconds=0)
    with pytest.raises(ValueError, match="sr"):
        load_audio(b"", sr=0)
    with pytest.raises(TypeError):
        load_audio(12345)  # type: ignore[arg-type]
