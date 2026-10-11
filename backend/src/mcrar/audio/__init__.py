"""Audio decoding and DSP feature extraction (BPM, key, loudness, energy).

Everything here is pure: no network, no global state, no writes. Decoding goes through
`soundfile` only (bundled libsndfile); the system ffmpeg is never used.
"""

from mcrar.audio.analyze import ANALYSIS_VERSION, AudioFeatures, analyze_audio
from mcrar.audio.features import (
    KeyEstimate,
    Loudness,
    TempoEstimate,
    estimate_energy,
    estimate_key,
    estimate_loudness,
    estimate_tempo,
)
from mcrar.audio.io import (
    AudioClip,
    AudioDecodeError,
    AudioError,
    AudioInfo,
    UnsupportedAudioError,
    load_audio,
    probe_audio,
)

__all__ = [
    "ANALYSIS_VERSION",
    "AudioClip",
    "AudioDecodeError",
    "AudioError",
    "AudioFeatures",
    "AudioInfo",
    "KeyEstimate",
    "Loudness",
    "TempoEstimate",
    "UnsupportedAudioError",
    "analyze_audio",
    "estimate_energy",
    "estimate_key",
    "estimate_loudness",
    "estimate_tempo",
    "load_audio",
    "probe_audio",
]
