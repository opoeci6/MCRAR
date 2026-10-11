"""Top-level audio analysis: decode once, run every DSP estimator, return one record."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from mcrar.audio.features import (
    ANALYSIS_SR,
    estimate_energy,
    estimate_key,
    estimate_loudness,
    estimate_tempo,
)
from mcrar.audio.io import AudioSource, load_audio

ANALYSIS_VERSION = "audio-v2"


@dataclass(frozen=True)
class AudioFeatures:
    bpm: float | None
    bpm_raw: float | None
    bpm_confidence: float
    key: str | None
    mode: str | None
    key_confidence: float
    loudness_lufs: float | None
    rms_db: float
    energy: float
    duration_s: float  # whole file, even if analysis was truncated by max_seconds
    sample_rate: int  # original file rate
    channels: int  # original channel count
    analysis_version: str = ANALYSIS_VERSION

    def to_dict(self) -> dict[str, float | int | str | None]:
        """JSON-safe dict (plain Python scalars and None)."""
        return asdict(self)


def analyze_audio(source: AudioSource, *, max_seconds: float | None = 240) -> AudioFeatures:
    """Decode `source` to 22050 Hz mono (first `max_seconds` only) and extract features."""
    clip = load_audio(source, sr=ANALYSIS_SR, mono=True, max_seconds=max_seconds)
    y = clip.samples
    tempo = estimate_tempo(y, clip.sr)
    key = estimate_key(y, clip.sr)
    loud = estimate_loudness(y, clip.sr)
    energy = estimate_energy(y, clip.sr, loud)
    return AudioFeatures(
        bpm=_round(tempo.bpm, 2),
        bpm_raw=_round(tempo.bpm_raw, 2),
        bpm_confidence=round(tempo.confidence, 4),
        key=key.tonic,
        mode=key.mode,
        key_confidence=round(key.confidence, 4),
        loudness_lufs=_round(loud.loudness_lufs, 2),
        rms_db=round(loud.rms_db, 2),
        energy=round(energy, 4),
        duration_s=round(clip.duration_s, 3),
        sample_rate=clip.original_sr,
        channels=clip.channels,
    )


def _round(value: float | None, ndigits: int) -> float | None:
    return None if value is None else round(float(value), ndigits)
