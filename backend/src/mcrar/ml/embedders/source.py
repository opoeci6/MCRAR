"""One recipe for the embedding of an audio file, shared by every caller.

The catalog's tracks (``EmbeddingStage``), an uploaded reference song (``POST /api/reference``)
and ``mcrar search --like-file`` all go through :func:`embed_audio_source`, so a song embedded
for a search lands in the same space, from the same decoding and windows, as the same song in
the catalog. ``mcrar.audio`` (librosa) is imported inside the function to keep this package light.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from mcrar.ml.embedders.base import Embedder, embed_track

if TYPE_CHECKING:
    from mcrar.audio.io import AudioSource

EMBED_MAX_SECONDS = 240  # only the first 4 minutes of a track are decoded and embedded


@dataclass(frozen=True)
class SourceEmbedding:
    """``vector`` is the L2-normalised ``(dim,)`` track embedding; ``duration_s`` is the length
    of the whole file (not only of the part that was embedded)."""

    vector: np.ndarray
    duration_s: float


def embed_audio_source(
    embedder: Embedder,
    source: AudioSource,
    *,
    max_seconds: float | None = EMBED_MAX_SECONDS,
) -> SourceEmbedding:
    """Decode the first ``max_seconds`` of ``source`` (path, bytes or binary file) mono at the
    embedder's sample rate and embed it with :func:`~mcrar.ml.embedders.base.embed_track`.

    Raises ``mcrar.audio.AudioError`` when the audio cannot be decoded."""
    from mcrar.audio import load_audio

    clip = load_audio(source, sr=embedder.sample_rate, mono=True, max_seconds=max_seconds)
    return SourceEmbedding(embed_track(embedder, clip.samples, clip.sr), clip.duration_s)
