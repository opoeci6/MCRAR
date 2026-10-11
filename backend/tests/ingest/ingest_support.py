"""Shared helpers for the ingest tests (not a test module; unique basename on purpose)."""

from __future__ import annotations

import io
import threading
import time
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from mcrar.audio import AudioFeatures
from mcrar.sources import SourceTrack

SR = 22050
CC_BY_NC_ND = "http://creativecommons.org/licenses/by-nc-nd/3.0/"
CC_BY = "https://creativecommons.org/licenses/by/4.0/"


def click_track(bpm: float = 120.0, seconds: float = 6.0, sr: int = SR) -> np.ndarray:
    """Short decaying 1.5 kHz bursts on every beat."""
    y = np.zeros(int(seconds * sr), dtype=np.float32)
    n = int(0.03 * sr)
    t = np.arange(n) / sr
    click = (0.8 * np.sin(2 * np.pi * 1500 * t) * np.exp(-t * 150)).astype(np.float32)
    k = 0
    while (start := int(round(k * 60.0 / bpm * sr))) < len(y):
        end = min(start + n, len(y))
        y[start:end] += click[: end - start]
        k += 1
    return y


def wav_bytes(bpm: float = 120.0, seconds: float = 6.0, fmt: str = "WAV") -> bytes:
    buf = io.BytesIO()
    sf.write(buf, click_track(bpm, seconds), SR, format=fmt)
    return buf.getvalue()


def write_audio(path: Path, bpm: float = 120.0, seconds: float = 6.0) -> Path:
    """Write a click track; the content (hence the file hash) depends on ``bpm``/``seconds``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt = "FLAC" if path.suffix.lower() == ".flac" else "WAV"
    path.write_bytes(wav_bytes(bpm, seconds, fmt))
    return path


def fake_features(bpm: float = 120.0) -> AudioFeatures:
    return AudioFeatures(
        bpm=bpm,
        bpm_raw=bpm,
        bpm_confidence=0.9,
        key="C",
        mode="major",
        key_confidence=0.5,
        loudness_lufs=-14.0,
        rms_db=-20.0,
        energy=0.5,
        duration_s=6.0,
        sample_rate=SR,
        channels=1,
    )


def make_track(
    n: int,
    *,
    license_url: str | None = CC_BY,
    stream_url: str | None = "default",
    **overrides: Any,
) -> SourceTrack:
    if stream_url == "default":
        stream_url = f"https://audio.example/{n}?token=a"
    fields: dict[str, Any] = {
        "source": "jamendo",
        "source_id": str(n),
        "title": f"Track {n}",
        "artist": f"Artist {n}",
        "album": "Album",
        "duration_s": 180.0,
        "source_url": f"https://www.jamendo.com/track/{n}",
        "stream_url": stream_url,
        "license_url": license_url,
        "tags": {"genres": ["ambient"]},
    }
    fields.update(overrides)
    return SourceTrack(**fields)


class FakeClient:
    """Stands in for JamendoClient: no network, synthetic WAV audio, recorded calls."""

    def __init__(
        self,
        tracks: list[SourceTrack],
        *,
        fetch_errors: Mapping[str, BaseException] | None = None,
        fetch_delay: float = 0.0,
        audio: bytes | None = None,
    ) -> None:
        self.tracks = tracks
        self.fetch_errors = dict(fetch_errors or {})
        self.fetch_delay = fetch_delay
        self.audio = audio if audio is not None else wav_bytes()
        self.search_kwargs: list[dict[str, Any]] = []
        self.fetched: list[str] = []
        self.fetch_spans: list[tuple[str, float, float]] = []
        self.closed = False
        self._lock = threading.Lock()

    def search_tracks(self, **kwargs: Any) -> Iterator[SourceTrack]:
        self.search_kwargs.append(kwargs)
        return iter(self.tracks[: kwargs["limit"]])

    def fetch_audio(self, track: SourceTrack) -> bytes:
        start = time.monotonic()
        with self._lock:
            self.fetched.append(track.source_id)
        if self.fetch_delay:
            time.sleep(self.fetch_delay)
        error = self.fetch_errors.get(track.source_id)
        with self._lock:
            self.fetch_spans.append((track.source_id, start, time.monotonic()))
        if error is not None:
            raise error
        return self.audio

    def usage(self) -> dict[str, Any]:
        return {"month": "2026-10", "requests": 7}

    def close(self) -> None:
        self.closed = True


class FakeAnalyzer:
    """Replaces analyze_audio: records calls, optionally slow or failing."""

    def __init__(
        self,
        *,
        delay: float = 0.0,
        errors: Mapping[int, BaseException] | None = None,
        on_call: Any = None,
    ) -> None:
        self.delay = delay
        self.errors = dict(errors or {})  # call number (1-based) -> exception to raise
        self.on_call = on_call
        self.calls = 0
        self.spans: list[tuple[float, float]] = []
        self.sources: list[object] = []

    def __call__(self, source: object, *, max_seconds: float | None = None) -> AudioFeatures:
        self.calls += 1
        self.sources.append(source)
        start = time.monotonic()
        if self.on_call is not None:
            self.on_call(self.calls)
        if self.delay:
            time.sleep(self.delay)
        self.spans.append((start, time.monotonic()))
        if self.calls in self.errors:
            raise self.errors[self.calls]
        return fake_features()


class RecordingStage:
    """A second stage (stands in for the M3a embedding stage)."""

    version = "rec-v1"

    def __init__(self, name: str = "embedding") -> None:
        self.name = name
        self.done: set[int] = set()
        self.audio_types: list[type] = []

    def is_current(self, repo: Any, track_id: int) -> bool:
        return track_id in self.done

    def run(self, repo: Any, track_id: int, audio: object) -> None:
        self.audio_types.append(type(audio))
        self.done.add(track_id)
