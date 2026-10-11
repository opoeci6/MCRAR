"""Synthetic audio fixtures (numpy only; nothing binary is committed)."""

from __future__ import annotations

import numpy as np

SR = 22050
_NOTE_INDEX = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8,
               "A": 9, "A#": 10, "B": 11}  # fmt: skip


def click_track(bpm: float, seconds: float = 12.0, sr: int = SR, amp: float = 0.8) -> np.ndarray:
    """Impulsive 1.5 kHz sine bursts (30 ms, exponential decay) on every beat."""
    y = np.zeros(int(seconds * sr), dtype=np.float32)
    n = int(0.03 * sr)
    t = np.arange(n) / sr
    click = (amp * np.sin(2 * np.pi * 1500 * t) * np.exp(-t * 150)).astype(np.float32)
    period = 60.0 / bpm
    k = 0
    while (start := int(round(k * period * sr))) < len(y):
        end = min(start + n, len(y))
        y[start:end] += click[: end - start]
        k += 1
    return y


def white_noise(seconds: float = 12.0, sr: int = SR, amp: float = 0.3, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (amp * rng.uniform(-1, 1, int(seconds * sr))).astype(np.float32)


def silence(seconds: float = 6.0, sr: int = SR) -> np.ndarray:
    return np.zeros(int(seconds * sr), dtype=np.float32)


def sine(freq: float = 440.0, seconds: float = 6.0, sr: int = SR, amp: float = 0.8) -> np.ndarray:
    t = np.arange(int(seconds * sr)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _midi_hz(midi: float) -> float:
    return 440.0 * 2.0 ** ((midi - 69) / 12.0)


def chord(root: str, minor: bool, seconds: float, sr: int = SR, amp: float = 0.2) -> np.ndarray:
    """Root-position triad (octave 3 root) with 4 harmonics and a gentle attack/release."""
    base = 48 + _NOTE_INDEX[root]
    t = np.arange(int(seconds * sr)) / sr
    y = np.zeros_like(t)
    for semis in (0, 3 if minor else 4, 7):
        f0 = _midi_hz(base + semis)
        for h in range(1, 5):
            y += (1.0 / h) * np.sin(2 * np.pi * f0 * h * t)
    fade = min(0.1, seconds / 4)
    env = np.minimum(1.0, np.minimum(t / fade, (seconds - t) / fade))
    y *= env
    return (amp * y / np.max(np.abs(y))).astype(np.float32)


def progression(chords: list[tuple[str, bool]], seconds_each: float = 2.0) -> np.ndarray:
    return np.concatenate([chord(r, m, seconds_each) for r, m in chords])


C_MAJOR = [("C", False), ("F", False), ("G", False), ("C", False)]
A_MINOR = [("A", True), ("D", True), ("E", False), ("A", True)]
D_MAJOR = [("D", False), ("G", False), ("A", False), ("D", False)]


def dense_loud(seconds: float = 8.0, sr: int = SR) -> np.ndarray:
    """Loud, busy signal: 8 clicks/s over a loud noise floor."""
    return np.clip(click_track(480, seconds, sr, amp=0.9) + white_noise(seconds, sr, 0.5), -1, 1)


def quiet_sparse(seconds: float = 8.0, sr: int = SR) -> np.ndarray:
    return sine(220.0, seconds, sr, amp=0.02)
