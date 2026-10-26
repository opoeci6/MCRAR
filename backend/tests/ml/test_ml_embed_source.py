"""embed_audio_source: the one recipe behind EmbeddingStage, reference uploads and --like-file."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from ml_support import FakeEmbedder, add_local, tone, write_wav

from mcrar.audio import AudioError
from mcrar.catalog import CatalogRepository
from mcrar.ingest import EmbeddingStage
from mcrar.ml.embedders import EMBED_MAX_SECONDS, embed_audio_source, embed_track

SR = 8000


def embedder() -> FakeEmbedder:
    return FakeEmbedder(sample_rate=SR, window_s=1.0)


def test_the_stage_stores_exactly_what_the_recipe_returns(
    repo: CatalogRepository, tmp_path: Path
) -> None:
    path = write_wav(tmp_path / "a.wav", seconds=5.0, sr=22050, freq=523.0)
    track_id = add_local(repo, "a.wav", path)
    stage_model = embedder()
    EmbeddingStage(stage_model).run(repo, track_id, path)
    stored = repo.get_embedding(track_id, stage_model.model_id)
    for source in (path, path.read_bytes()):  # a path and the bytes of the same file
        embedded = embed_audio_source(embedder(), source)
        assert np.array_equal(embedded.vector, stored)
        assert embedded.vector.shape == (stage_model.dim,)
        assert np.linalg.norm(embedded.vector) == pytest.approx(1.0, abs=1e-5)
        assert embedded.duration_s == pytest.approx(5.0, abs=0.01)


def test_the_recipe_decodes_at_the_models_rate_and_uses_embed_track(tmp_path: Path) -> None:
    model = embedder()
    path = write_wav(tmp_path / "a.wav", seconds=1.0, sr=22050)
    embedded = embed_audio_source(model, path)
    (windows,) = model.audio_calls
    assert len(windows) == 1 and windows[0].shape == (SR,)  # 1 s at 8 kHz after resampling
    assert np.allclose(embedded.vector, embed_track(embedder(), windows[0], SR), atol=1e-6)


def test_only_the_first_max_seconds_are_embedded_but_the_duration_is_the_whole_file(
    tmp_path: Path,
) -> None:
    model = embedder()
    path = write_wav(tmp_path / "long.wav", seconds=10.0, sr=SR)
    embedded = embed_audio_source(model, path, max_seconds=2)
    assert embedded.duration_s == pytest.approx(10.0, abs=0.01)
    (windows,) = model.audio_calls
    assert len(windows) == 3 and np.allclose(windows[0], tone(10.0, SR)[:SR], atol=1e-3)


def test_the_default_limit_is_240_seconds() -> None:
    assert EMBED_MAX_SECONDS == 240


def test_audio_that_cannot_be_decoded_is_an_audio_error() -> None:
    with pytest.raises(AudioError):
        embed_audio_source(embedder(), b"this is not audio at all")
