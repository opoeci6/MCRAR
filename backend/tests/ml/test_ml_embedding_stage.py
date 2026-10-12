"""EmbeddingStage: currency, force, decoding rate, and failures surfacing as failed stages."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from ml_support import BrokenDimEmbedder, FakeEmbedder, add_local, tone, write_wav

from mcrar.catalog import CatalogRepository
from mcrar.ingest import EmbeddingStage, ingest_local, reprocess_catalog
from mcrar.ml.embedders import embed_track, track_windows

SR = 8000


def _stage(**kwargs) -> tuple[EmbeddingStage, FakeEmbedder]:  # noqa: ANN003
    embedder = FakeEmbedder(sample_rate=SR, window_s=1.0, **kwargs)
    return EmbeddingStage(embedder), embedder


def test_name_and_version_come_from_the_embedder() -> None:
    stage, embedder = _stage(key="clap", revision="195c3a3e68faebb3")
    assert stage.name == "embed:clap"
    assert stage.version == embedder.model_id == "clap@195c3a3"


def test_is_current_follows_the_stored_embedding(repo: CatalogRepository, tmp_path: Path) -> None:
    stage, embedder = _stage()
    track_id = add_local(repo, "a.wav", write_wav(tmp_path / "a.wav"))
    assert not stage.is_current(repo, track_id)
    stage.run(repo, track_id, tmp_path / "a.wav")
    assert stage.is_current(repo, track_id)
    stored = repo.get_embedding(track_id, embedder.model_id)
    assert stored is not None and stored.shape == (embedder.dim,)
    assert np.linalg.norm(stored) == pytest.approx(1.0, abs=1e-5)
    # another model's embedding does not make this stage current
    other, _ = _stage(key="other")
    assert not other.is_current(repo, track_id)


def test_run_decodes_at_the_embedders_rate_mono_and_stores_embed_track_output(
    repo: CatalogRepository, tmp_path: Path
) -> None:
    # 1 s of 22.05 kHz audio is exactly one 8 kHz window once decoded at the model's rate
    embedder = FakeEmbedder(sample_rate=SR, window_s=1.0)
    path = write_wav(tmp_path / "a.wav", seconds=1.0, sr=22050)
    track_id = add_local(repo, "a.wav", path)
    EmbeddingStage(embedder).run(repo, track_id, path)
    (call,) = embedder.audio_calls
    assert len(call) == 1 and call[0].shape == (SR,)
    expected = embed_track(FakeEmbedder(sample_rate=SR, window_s=1.0), call[0], SR)
    assert np.allclose(repo.get_embedding(track_id, embedder.model_id), expected, atol=1e-6)


def test_run_accepts_bytes_and_honours_max_seconds(repo: CatalogRepository, tmp_path: Path) -> None:
    embedder = FakeEmbedder(sample_rate=SR, window_s=1.0)
    track_id = add_local(repo, "a.wav", None)
    audio = write_wav(tmp_path / "a.wav", seconds=10.0, sr=SR).read_bytes()
    EmbeddingStage(embedder, max_seconds=2).run(repo, track_id, audio)
    # only the first 2 s were decoded, so the three windows come from a 2 s clip
    expected = track_windows(tone(10.0, SR)[: 2 * SR], SR, 1.0)
    (windows,) = embedder.audio_calls
    assert len(windows) == len(expected) == 3
    for got, want in zip(windows, expected, strict=True):
        assert np.allclose(got, want, atol=1e-3)  # 16-bit WAV quantisation


def test_pipeline_skips_current_tracks_and_force_reembeds(
    repo: CatalogRepository, tmp_path: Path
) -> None:
    root = tmp_path / "lib"
    write_wav(root / "a.wav", freq=300.0)
    write_wav(root / "b.wav", freq=900.0)
    stage, embedder = _stage()

    first = ingest_local(root, repo, stages=[stage])
    assert (first.processed, first.skipped, first.failed) == (2, 0, 0)
    assert len(embedder.audio_calls) == 2

    again = ingest_local(root, repo, stages=[stage])
    assert (again.processed, again.skipped) == (0, 2)
    assert len(embedder.audio_calls) == 2  # nothing recomputed

    forced = ingest_local(root, repo, stages=[stage], force=True)
    assert (forced.processed, forced.skipped) == (2, 0)
    assert len(embedder.audio_calls) == 4
    assert repo.stats()["embeddings_by_model"] == {embedder.model_id: 2}


def test_dim_mismatch_with_the_stored_model_fails_the_stage(
    repo: CatalogRepository, tmp_path: Path
) -> None:
    root = tmp_path / "lib"
    write_wav(root / "a.wav")
    good, embedder = _stage()
    ingest_local(root, repo, stages=[good])

    # same model id, different dimension: the database refuses and the stage fails
    narrower = EmbeddingStage(FakeEmbedder(sample_rate=SR, window_s=1.0, dim=4))
    report = ingest_local(root, repo, stages=[narrower], force=True)
    assert (report.processed, report.failed) == (0, 1)
    failure = report.failures[0]
    assert failure.stage == "embed:fake"
    assert "does not match existing dim 8" in failure.message
    assert repo.get_embedding(1, embedder.model_id).shape == (8,)  # type: ignore[union-attr]
    (entry,) = repo.failed_items("embed:fake")
    assert entry.status == "failed"


def test_an_embedder_returning_the_wrong_dimension_fails_the_stage(
    repo: CatalogRepository, tmp_path: Path
) -> None:
    root = tmp_path / "lib"
    write_wav(root / "a.wav")
    stage = EmbeddingStage(BrokenDimEmbedder(sample_rate=SR, window_s=1.0, dim=8))
    report = ingest_local(root, repo, stages=[stage])
    assert report.failed == 1
    assert "returned 7-d embeddings, expected 8" in report.failures[0].message
    assert repo.stats()["embeddings_by_model"] == {}


def test_a_silent_or_undecodable_track_fails_without_stopping_the_run(
    repo: CatalogRepository, tmp_path: Path
) -> None:
    root = tmp_path / "lib"
    write_wav(root / "a.wav", freq=200.0)
    (root / "broken.wav").write_bytes(b"RIFF\x00\x00\x00\x00WAVEjunk")
    write_wav(root / "c.wav", freq=600.0)
    stage, embedder = _stage()
    report = ingest_local(root, repo, stages=[stage])
    assert (report.processed, report.failed) == (2, 1)
    assert report.failures[0].title == "broken"
    assert repo.stats()["embeddings_by_model"] == {embedder.model_id: 2}


def test_reprocess_catalog_embeds_existing_local_tracks(
    repo: CatalogRepository, tmp_path: Path
) -> None:
    ids = [
        add_local(repo, f"{n}.wav", write_wav(tmp_path / f"{n}.wav", freq=200.0 * (n + 1)))
        for n in range(3)
    ]
    stage, embedder = _stage()
    report = reprocess_catalog(repo, stages=[stage])
    assert (report.seen, report.processed, report.skipped, report.failed) == (3, 3, 0, 0)
    assert all(repo.get_embedding(i, embedder.model_id) is not None for i in ids)
