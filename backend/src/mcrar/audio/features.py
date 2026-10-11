"""DSP features: tempo, key, loudness and a heuristic energy score.

All estimators expect mono float32/float64 audio (`analyze_audio` runs them at
`ANALYSIS_SR` = 22050 Hz), are deterministic and have no side effects. Silence yields "no
answer" (None) rather than a made-up value.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import librosa
import numpy as np
import pyloudnorm

ANALYSIS_SR = 22050
HOP_LENGTH = 512

# Tempo octave folding: bpm is folded into [BPM_MIN, BPM_MAX).
BPM_MIN = 70.0
BPM_MAX = 180.0
# Below this mean frame RMS (dBFS) a clip is treated as silent: no tempo/key/loudness.
SILENCE_RMS_DB = -70.0
# Tempo confidence: a coefficient of variation of beat intervals at/above this gives
# regularity 0 (regularity = 1 - cv / TEMPO_CV_LIMIT).
TEMPO_CV_LIMIT = 0.25
# The mean-beat-spacing tempo replaces the tracker's tempo only if within this fraction of it.
TEMPO_REFINE_TOLERANCE = 0.1
# Absolute peak-picking threshold on the (un-normalised) onset-strength envelope.
ONSET_DELTA = 0.3
# Key confidence: a margin (best - runner-up correlation) of this size gives confidence 1.
KEY_MARGIN_FULL = 0.15

# Energy heuristic constants (placeholder; ML may refine later).
ENERGY_LUFS_QUIET = -40.0  # maps to 0
ENERGY_LUFS_LOUD = -5.0  # maps to 1
ENERGY_ONSET_RATE_MAX = 8.0  # onsets/second mapped to 1

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

# Krumhansl-Kessler probe-tone profiles (tonic first).
KK_MAJOR = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88], dtype=np.float64
)
KK_MINOR = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17], dtype=np.float64
)


@dataclass(frozen=True)
class TempoEstimate:
    bpm: float | None  # folded into [70, 180)
    bpm_raw: float | None  # as returned by the tracker, before octave folding
    confidence: float  # [0, 1]


@dataclass(frozen=True)
class KeyEstimate:
    tonic: str | None  # C, C#, D, ... B
    mode: str | None  # "major" | "minor"
    confidence: float  # [0, 1]


@dataclass(frozen=True)
class Loudness:
    loudness_lufs: float | None  # integrated, BS.1770; None if too short or silent
    rms_db: float  # mean frame RMS in dBFS (-100.0 for digital silence)


def _as_mono(y: np.ndarray) -> np.ndarray:
    y = np.asarray(y, dtype=np.float32)
    if y.ndim != 1:
        raise ValueError("expected mono audio with shape (n,)")
    return y


def _mean_rms_db(y: np.ndarray) -> float:
    if y.size == 0:
        return -100.0
    rms = float(np.mean(librosa.feature.rms(y=y, frame_length=2048, hop_length=HOP_LENGTH)))
    return max(20.0 * float(np.log10(max(rms, 1e-12))), -100.0)


def _is_silent(y: np.ndarray) -> bool:
    return y.size < 2048 or _mean_rms_db(y) < SILENCE_RMS_DB


def fold_bpm(bpm: float) -> float:
    """Double while < 70, halve while >= 180, so the result lies in [70, 180)."""
    if not np.isfinite(bpm) or bpm <= 0:
        raise ValueError("bpm must be positive and finite")
    while bpm < BPM_MIN:
        bpm *= 2.0
    while bpm >= BPM_MAX:
        bpm /= 2.0
    return bpm


def estimate_tempo(y: np.ndarray, sr: int = ANALYSIS_SR) -> TempoEstimate:
    """Tempo from onset strength + dynamic-programming beat tracking.

    `bpm_raw` is the tracker's tempo; `bpm` is `bpm_raw` folded into [70, 180).

    confidence = regularity * pulse, both in [0, 1]:
      regularity = clip(1 - cv / TEMPO_CV_LIMIT, 0, 1) where cv = std/mean of the tracked
        beat intervals (needs >= 4 beats, else 0);
      pulse = unbiased normalised autocorrelation of the onset-strength envelope (zero lag
        = 1), taken as the best value within one frame of the beat period, clipped to [0, 1].
    The DP beat tracker always produces evenly spaced beats, even on noise, so regularity
    alone is not discriminative; the autocorrelation peak is what is low for arrhythmic input.
    """
    y = _as_mono(y)
    if _is_silent(y):
        return TempoEstimate(None, None, 0.0)
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP_LENGTH)
    if not np.any(env > 0):
        return TempoEstimate(None, None, 0.0)
    tempo, beats = librosa.beat.beat_track(onset_envelope=env, sr=sr, hop_length=HOP_LENGTH)
    raw = float(np.atleast_1d(tempo)[0])
    if not np.isfinite(raw) or raw <= 0:
        return TempoEstimate(None, None, 0.0)

    regularity = 0.0
    if len(beats) >= 4:
        intervals = np.diff(beats).astype(np.float64)
        cv = float(np.std(intervals) / np.mean(intervals))
        regularity = float(np.clip(1.0 - cv / TEMPO_CV_LIMIT, 0.0, 1.0))
        # The tracker's tempo is quantised to onset-envelope frames (~3 BPM at 120); the mean
        # beat spacing over the whole clip has sub-frame precision.
        span = float(beats[-1] - beats[0]) / (len(beats) - 1)
        refined = 60.0 * sr / (HOP_LENGTH * span)
        if abs(refined / raw - 1.0) < TEMPO_REFINE_TOLERANCE:
            raw = refined

    centred = env - env.mean()
    ac = np.correlate(centred, centred, mode="full")[len(centred) - 1 :]
    pulse = 0.0
    if ac[0] > 0:
        n = len(ac)
        ac = ac / ac[0] * (n / (n - np.arange(n)))  # unbiased: undo the triangular decay
        lag = 60.0 * sr / (HOP_LENGTH * raw)
        lo, hi = int(np.floor(lag)) - 1, int(np.ceil(lag)) + 1
        lo = max(lo, 1)
        if lo < min(hi + 1, len(ac)):
            pulse = float(np.clip(ac[lo : hi + 1].max(), 0.0, 1.0))

    return TempoEstimate(
        bpm=fold_bpm(raw), bpm_raw=raw, confidence=float(np.clip(regularity * pulse, 0.0, 1.0))
    )


def estimate_key(y: np.ndarray, sr: int = ANALYSIS_SR) -> KeyEstimate:
    """Key from the mean CQT chroma vs. the 24 rotated Krumhansl-Kessler profiles.

    The Pearson correlation of the mean chroma vector with each rotated major/minor profile is
    computed; the best match gives tonic and mode.

    confidence = clip((r_best - r_second) / KEY_MARGIN_FULL, 0, 1): how far the best match
    beats the runner-up (e.g. the relative major/minor or the dominant key).
    """
    y = _as_mono(y)
    if _is_silent(y):
        return KeyEstimate(None, None, 0.0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)  # n_fft > len(y) on very short clips
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=HOP_LENGTH)
    mean = chroma.mean(axis=1).astype(np.float64)
    if not np.all(np.isfinite(mean)) or np.ptp(mean) < 1e-9:
        return KeyEstimate(None, None, 0.0)
    scores: list[tuple[float, int, str]] = []
    for mode, profile in (("major", KK_MAJOR), ("minor", KK_MINOR)):
        for tonic in range(12):
            r = float(np.corrcoef(mean, np.roll(profile, tonic))[0, 1])
            scores.append((r, tonic, mode))
    scores.sort(key=lambda s: (-s[0], s[1], s[2]))
    best, second = scores[0], scores[1]
    confidence = float(np.clip((best[0] - second[0]) / KEY_MARGIN_FULL, 0.0, 1.0))
    return KeyEstimate(NOTE_NAMES[best[1]], best[2], confidence)


def estimate_loudness(y: np.ndarray, sr: int = ANALYSIS_SR) -> Loudness:
    """Integrated loudness (BS.1770 via pyloudnorm) and mean RMS in dBFS.

    `loudness_lufs` is None for clips shorter than the 400 ms gating block or silent
    (pyloudnorm would return -inf).
    """
    y = _as_mono(y)
    rms_db = _mean_rms_db(y)
    lufs: float | None = None
    if y.size >= int(0.4 * sr) + 1 and float(np.max(np.abs(y))) > 0.0:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            value = float(pyloudnorm.Meter(sr).integrated_loudness(y.astype(np.float64)))
        if np.isfinite(value):
            lufs = value
    return Loudness(loudness_lufs=lufs, rms_db=rms_db)


def onset_rate(y: np.ndarray, sr: int = ANALYSIS_SR) -> float:
    """Detected onsets per second."""
    y = _as_mono(y)
    if y.size == 0 or _is_silent(y):
        return 0.0
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP_LENGTH)
    # Un-normalised envelope + absolute delta, so a steady tone is not "full of onsets".
    onsets = librosa.onset.onset_detect(
        onset_envelope=env, sr=sr, hop_length=HOP_LENGTH, normalize=False, delta=ONSET_DELTA
    )
    return float(len(onsets)) / (y.size / sr)


def _scale(value: float, lo: float, hi: float) -> float:
    return float(np.clip((value - lo) / (hi - lo), 0.0, 1.0))


def estimate_energy(
    y: np.ndarray, sr: int = ANALYSIS_SR, loudness: Loudness | None = None
) -> float:
    """Heuristic perceived energy in [0, 1] (placeholder that ML may refine later).

    energy = mean(loudness_term, onset_term) where
      loudness_term = LUFS mapped ENERGY_LUFS_QUIET..ENERGY_LUFS_LOUD (-40..-5) to 0..1
        (mean RMS dBFS is used when LUFS is unavailable);
      onset_term = onsets/second mapped 0..ENERGY_ONSET_RATE_MAX (8) to 0..1.
    """
    y = _as_mono(y)
    loud = loudness if loudness is not None else estimate_loudness(y, sr)
    level = loud.loudness_lufs if loud.loudness_lufs is not None else loud.rms_db
    loudness_term = _scale(level, ENERGY_LUFS_QUIET, ENERGY_LUFS_LOUD)
    onset_term = _scale(onset_rate(y, sr), 0.0, ENERGY_ONSET_RATE_MAX)
    return float((loudness_term + onset_term) / 2.0)
