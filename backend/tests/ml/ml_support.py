"""Shared helpers for the ML tests (not a test module; unique basename on purpose).

Nothing here imports torch: the default suite runs without the ``ml`` extra.
"""

from __future__ import annotations

import io
import threading
import zlib
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from mcrar.catalog import CatalogRepository, TrackRecord
from mcrar.sources import SourceTrack

STAT_COUNT = 8


class FakeEmbedder:
    """A deterministic stand-in for a real model: a seeded random projection of simple audio
    statistics (so different audio gives different vectors) and of a hash of the text."""

    def __init__(
        self,
        key: str = "fake",
        *,
        dim: int = 8,
        sample_rate: int = 8000,
        window_s: float = 1.0,
        commercial_ok: bool = True,
        revision: str = "abcdef0123456789",
        seed: int = 0,
        fail_text: str | None = None,
    ) -> None:
        self.key = key
        self.model_id = f"{key}@{revision[:7]}"
        self.dim = dim
        self.sample_rate = sample_rate
        self.window_s = window_s
        self.commercial_ok = commercial_ok
        self.device = "cpu"
        self.dtype = "fp32"
        self.dtype_note = "fp32 (fake)"
        self.load_seconds = 0.0
        self.audio_calls: list[list[np.ndarray]] = []
        self.text_calls: list[list[str]] = []
        self.closed = False
        self.fail_text = fail_text
        self._seed = seed
        self._projection = np.random.default_rng(seed).standard_normal((STAT_COUNT, dim))

    @staticmethod
    def stats(clip: np.ndarray) -> np.ndarray:
        spectrum = np.abs(np.fft.rfft(clip)) if clip.size else np.zeros(1)
        bands = np.array_split(spectrum, 4)
        return np.array(
            [
                1.0,  # constant: silence still gives a non-zero vector
                float(clip.mean()),
                float(clip.std()),
                float(np.abs(clip).max()),
                *(float(b.mean()) if b.size else 0.0 for b in bands),
            ]
        )

    def embed_audio(self, clips: Sequence[np.ndarray]) -> np.ndarray:
        self.audio_calls.append([np.asarray(c) for c in clips])
        rows = np.stack(
            [self.stats(np.asarray(c, dtype=np.float32)) @ self._projection for c in clips]
        )
        return _unit(rows)

    def embed_text(self, texts: Sequence[str]) -> np.ndarray:
        self.text_calls.append(list(texts))
        rows = [
            np.random.default_rng([self._seed, zlib.crc32(t.encode())]).standard_normal(self.dim)
            for t in texts
        ]
        return _unit(np.stack(rows))

    def close(self) -> None:
        self.closed = True


class BrokenDimEmbedder(FakeEmbedder):
    """Claims ``dim`` but returns vectors one element shorter."""

    def embed_audio(self, clips: Sequence[np.ndarray]) -> np.ndarray:
        return super().embed_audio(clips)[:, :-1]


def _unit(rows: np.ndarray) -> np.ndarray:
    rows = np.asarray(rows, dtype=np.float32)
    return rows / np.linalg.norm(rows, axis=1, keepdims=True)


# -- audio files -------------------------------------------------------------------------------


def tone(seconds: float, sr: int, freq: float = 440.0) -> np.ndarray:
    t = np.arange(round(seconds * sr)) / sr
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def wav_bytes(seconds: float = 3.0, sr: int = 22050, freq: float = 440.0) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, tone(seconds, sr, freq), sr, format="WAV")
    return buf.getvalue()


def write_wav(path: Path, seconds: float = 3.0, sr: int = 22050, freq: float = 440.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(wav_bytes(seconds, sr, freq))
    return path


# -- catalog rows and a Jamendo stand-in -----------------------------------------------------------


def add_jamendo(repo: CatalogRepository, n: int, *, stream_url: str | None = None) -> int:
    """A stored Jamendo track whose stream URL is the stale one (token ``old``)."""
    return repo.upsert_track(
        TrackRecord(
            source="jamendo",
            source_id=str(n),
            title=f"Track {n}",
            stream_url=stream_url or f"https://audio.example/{n}?token=old",
            risk="green",
        )
    )


def add_local(repo: CatalogRepository, name: str, path: Path | None) -> int:
    return repo.upsert_track(
        TrackRecord(
            source="local",
            source_id=name,
            title=name,
            local_path=None if path is None else str(path),
            risk="unknown",
        )
    )


class FakeJamendo:
    """Records ``get_tracks`` batches and which stream URLs were fetched."""

    def __init__(
        self,
        *,
        missing: Iterable[int] = (),
        fetch_errors: Mapping[str, BaseException] | None = None,
        get_error: BaseException | None = None,
        get_error_on_call: int = 1,
        audio: bytes | None = None,
    ) -> None:
        self.missing = {str(m) for m in missing}
        self.fetch_errors = dict(fetch_errors or {})
        self.get_error = get_error
        self.get_error_on_call = get_error_on_call
        self.audio = audio if audio is not None else wav_bytes()
        self.get_calls: list[list[str]] = []
        self.fetched: list[tuple[str, str | None]] = []  # (source_id, stream_url used)
        self._lock = threading.Lock()

    def get_tracks(self, ids: Sequence[str | int], *, use_cache: bool = False) -> list[SourceTrack]:
        self.get_calls.append([str(i) for i in ids])
        if self.get_error is not None and len(self.get_calls) == self.get_error_on_call:
            raise self.get_error
        return [
            SourceTrack(
                source="jamendo",
                source_id=str(i),
                title=f"Track {i}",
                artist=None,
                stream_url=f"https://audio.example/{i}?token=fresh{len(self.get_calls)}",
            )
            for i in ids
            if str(i) not in self.missing
        ]

    def fetch_audio(self, track: SourceTrack, **kwargs: Any) -> bytes:
        with self._lock:
            self.fetched.append((track.source_id, track.stream_url))
        error = self.fetch_errors.get(track.source_id)
        if error is not None:
            raise error
        return self.audio

    def close(self) -> None:
        pass


class CountingStage:
    """A stage that records the audio it was given."""

    version = "count-v1"

    def __init__(self, name: str = "count") -> None:
        self.name = name
        self.done: set[int] = set()
        self.runs: list[tuple[int, type]] = []

    def is_current(self, repo: Any, track_id: int) -> bool:
        return track_id in self.done

    def run(self, repo: Any, track_id: int, audio: object) -> None:
        self.runs.append((track_id, type(audio)))
        self.done.add(track_id)
