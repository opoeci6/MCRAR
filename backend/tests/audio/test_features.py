from __future__ import annotations

import numpy as np
import pytest
import synth

from mcrar.audio import (
    estimate_energy,
    estimate_key,
    estimate_loudness,
    estimate_tempo,
)
from mcrar.audio.features import fold_bpm

SR = synth.SR


@pytest.mark.parametrize("bpm", [90, 120, 140, 170])
def test_click_track_tempo(bpm: int) -> None:
    est = estimate_tempo(synth.click_track(bpm), SR)
    assert est.bpm == pytest.approx(bpm, abs=2)
    assert 0.0 <= est.confidence <= 1.0


def test_steady_click_confidence_is_high() -> None:
    assert estimate_tempo(synth.click_track(120), SR).confidence >= 0.6


def test_slow_tempo_folds_up() -> None:
    est = estimate_tempo(synth.click_track(60), SR)
    assert est.bpm == pytest.approx(120, abs=2)
    assert est.bpm_raw == pytest.approx(60, abs=2)


def test_fast_tempo_folds_down() -> None:
    est = estimate_tempo(synth.click_track(200), SR)
    assert est.bpm == pytest.approx(100, abs=2)


@pytest.mark.parametrize(
    ("raw", "folded"), [(60, 120), (35, 70), (70, 70), (179.9, 179.9), (180, 90), (400, 100)]
)
def test_fold_bpm(raw: float, folded: float) -> None:
    assert fold_bpm(raw) == pytest.approx(folded)
    assert 70 <= fold_bpm(raw) < 180


def test_noise_has_low_tempo_confidence() -> None:
    noise = estimate_tempo(synth.white_noise(), SR).confidence
    click = estimate_tempo(synth.click_track(120), SR).confidence
    assert noise < click
    assert noise < 0.5


def test_silence_has_no_tempo() -> None:
    est = estimate_tempo(synth.silence(), SR)
    assert (est.bpm, est.bpm_raw, est.confidence) == (None, None, 0.0)
    assert estimate_tempo(np.zeros(100, dtype=np.float32), SR).bpm is None


@pytest.mark.parametrize(
    ("chords", "tonic", "mode"),
    [
        (synth.C_MAJOR, "C", "major"),
        (synth.A_MINOR, "A", "minor"),  # guards against relative-major (C major) confusion
        (synth.D_MAJOR, "D", "major"),
    ],
)
def test_key_of_progressions(chords: list, tonic: str, mode: str) -> None:
    est = estimate_key(synth.progression(chords), SR)
    assert (est.tonic, est.mode) == (tonic, mode)
    assert 0.0 < est.confidence <= 1.0


def test_silence_has_no_key() -> None:
    est = estimate_key(synth.silence(), SR)
    assert est.tonic is None
    assert est.mode is None
    assert est.confidence == 0.0


def test_loud_dense_signal_has_more_energy_than_quiet_sparse() -> None:
    loud = estimate_energy(synth.dense_loud(), SR)
    quiet = estimate_energy(synth.quiet_sparse(), SR)
    assert 0.0 <= quiet < loud <= 1.0


def test_halving_amplitude_lowers_loudness_by_6_db() -> None:
    # The brief says "about -3 dB (+-1) ... (~ -6 dB)"; halving the amplitude is -6.02 dB.
    y = synth.click_track(120)
    full = estimate_loudness(y, SR)
    half = estimate_loudness(y * 0.5, SR)
    assert full.loudness_lufs is not None
    assert half.loudness_lufs is not None
    assert full.loudness_lufs - half.loudness_lufs == pytest.approx(6.02, abs=0.5)
    assert full.rms_db - half.rms_db == pytest.approx(6.02, abs=0.1)


def test_silence_loudness_and_energy() -> None:
    loud = estimate_loudness(synth.silence(), SR)
    assert loud.loudness_lufs is None
    assert loud.rms_db == -100.0
    assert estimate_energy(synth.silence(), SR) == pytest.approx(0.0, abs=0.01)


def test_too_short_clip_has_no_lufs() -> None:
    assert estimate_loudness(synth.sine(440.0, 0.2), SR).loudness_lufs is None


def test_estimators_reject_non_mono() -> None:
    with pytest.raises(ValueError, match="mono"):
        estimate_tempo(np.zeros((100, 2)), SR)
