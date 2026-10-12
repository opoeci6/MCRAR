"""Helpers for the bake-off tests (not a test module; unique basename on purpose).

A tiny synthetic Song Describer folder with generated tones, and fake embedders whose audio and
text vectors are built to match (track ``i`` is a tone of a distinct frequency and its caption
says ``tone i``), so retrieval results are known in advance. Nothing here imports torch.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import soundfile as sf
from ml_support import FakeEmbedder

SR = 8000
BASE_FREQ = 200.0
FREQ_STEP = 450.0
TRACK_ID_BASE = 1000


def tone_freq(index: int) -> float:
    return BASE_FREQ + FREQ_STEP * index


class ToneEmbedder(FakeEmbedder):
    """Audio: a one-hot vector of the tone's frequency slot. Text ``"tone i"``: the one-hot
    of slot ``(i + shift) % dim``. With ``shift=0`` every caption retrieves its own track.
    Other text (genre or scene queries) behaves like :class:`FakeEmbedder`."""

    def __init__(self, key: str = "fake", *, shift: int = 0, **kwargs: object) -> None:
        kwargs.setdefault("sample_rate", SR)
        kwargs.setdefault("window_s", 1.0)
        super().__init__(key, **kwargs)  # type: ignore[arg-type]
        self.shift = shift

    def _one_hot(self, slot: int) -> np.ndarray:
        vec = np.full(self.dim, 0.01, dtype=np.float32)
        vec[slot % self.dim] = 1.0
        return vec

    def embed_audio(self, clips: Sequence[np.ndarray]) -> np.ndarray:
        self.audio_calls.append([np.asarray(c) for c in clips])
        rows = []
        for clip in clips:
            spectrum = np.abs(np.fft.rfft(np.asarray(clip, dtype=np.float32)))
            freq = int(spectrum.argmax()) * self.sample_rate / len(clip)
            rows.append(self._one_hot(round((freq - BASE_FREQ) / FREQ_STEP)))
        return _unit(np.stack(rows))

    def embed_text(self, texts: Sequence[str]) -> np.ndarray:
        """``"tone i"`` matches track ``i``; any other text gets FakeEmbedder's hashed vector."""
        hashed = super().embed_text(texts)  # also records the call
        rows = [
            self._one_hot(int(t.split()[1]) + self.shift) if t.startswith("tone ") else hashed[i]
            for i, t in enumerate(texts)
        ]
        return _unit(np.stack(rows))


def _unit(rows: np.ndarray) -> np.ndarray:
    rows = np.asarray(rows, dtype=np.float32)
    return rows / np.linalg.norm(rows, axis=1, keepdims=True)


def make_sdd(
    root: Path, n_tracks: int = 6, *, broken: Sequence[int] = (), absent: Sequence[int] = ()
):
    """Write ``song_describer.csv`` and tone files under ``root``; returns the track ids.

    Each track has a validated caption ``tone i`` and a non-validated one ``tone i again``,
    except the last track, which only has the non-validated one. Tracks in ``broken`` get
    undecodable audio; tracks in ``absent`` get no file at all.
    """
    rows = []
    track_ids = []
    caption_id = 1
    for i in range(n_tracks):
        track_id = TRACK_ID_BASE + i
        track_ids.append(track_id)
        directory = f"{i % 3:02d}"
        csv_path = f"{directory}/{track_id}.mp3"
        captions = [(f"tone {i}", i != n_tracks - 1), (f"tone {i} again", False)]
        for text, valid in captions:
            rows.append(
                {
                    "caption_id": caption_id,
                    "track_id": track_id,
                    "caption": text,
                    "is_valid_subset": str(valid),
                    "familiarity": 0,
                    "artist_id": 1,
                    "album_id": 1,
                    "path": csv_path,
                    "duration": 3.0,
                }
            )
            caption_id += 1
        target = root / "audio" / "audio" / directory / f"{track_id}.2min.mp3"
        if i in absent:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if i in broken:
            target.write_bytes(b"this is not audio")
            continue
        t = np.arange(3 * SR) / SR
        samples = (0.5 * np.sin(2 * np.pi * tone_freq(i) * t)).astype(np.float32)
        sf.write(str(target), samples, SR, format="WAV")  # WAV content, MP3 name: sniffed
    root.mkdir(parents=True, exist_ok=True)
    with open(root / "song_describer.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return track_ids
