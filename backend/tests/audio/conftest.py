"""Fixtures for audio tests: short synthetic clips written to tmp_path."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
import synth


@pytest.fixture
def stereo_44k() -> np.ndarray:
    """2 s stereo at 44.1 kHz: left = 440 Hz, right = silence."""
    left = synth.sine(440.0, 2.0, sr=44100, amp=0.5)
    return np.stack([left, np.zeros_like(left)], axis=1)


@pytest.fixture
def demo_signal() -> np.ndarray:
    """120 BPM click track over a C-major progression, 8 s at 22.05 kHz."""
    return 0.5 * synth.click_track(120, 8.0) + synth.progression(synth.C_MAJOR)


@pytest.fixture
def demo_wav(tmp_path: Path, demo_signal: np.ndarray) -> Path:
    path = tmp_path / "demo.wav"
    sf.write(path, demo_signal, synth.SR)
    return path
