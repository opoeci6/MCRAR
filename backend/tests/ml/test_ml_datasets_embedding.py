"""Embedding uses the catalog's CLAP contract and commits before deleting source audio."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from ml_support import FakeEmbedder, write_wav

from mcrar import audio as audio_module
from mcrar.ml.datasets import Sample
from mcrar.ml.datasets import embedding as module


def test_checkpoint_resume_cap_and_delete_only_after_write(tmp_path: Path, monkeypatch) -> None:
    paths = [write_wav(tmp_path / f"{i}.wav") for i in range(3)]
    samples = [Sample(i, p, "train", {}) for i, p in enumerate(paths)]
    embedder = FakeEmbedder("clap", revision="195c3a3", dim=512)
    output = tmp_path / "embeddings/clap@195c3a3.npz"
    original_load, original_save = audio_module.load_audio, module.atomic_npz
    cap_calls, save_calls = [], []

    def load(path, **kwargs):
        cap_calls.append(kwargs)
        return original_load(path, **kwargs)

    def save(path, **kwargs):
        assert all(p.exists() for p in paths)  # no audio deleted before the first durable save
        original_save(path, **kwargs)
        save_calls.append(path)

    monkeypatch.setattr(audio_module, "load_audio", load)
    monkeypatch.setattr(module, "atomic_npz", save)
    module.embed_dataset(samples[:2], embedder, output, delete_audio=False)
    assert len(save_calls) == 1
    monkeypatch.setattr(module, "atomic_npz", original_save)
    report = module.embed_dataset(samples, embedder, output, delete_audio=True)
    assert report["embedded"] == 3 and len(embedder.audio_calls) == 3
    assert all(
        c == {"sr": embedder.sample_rate, "mono": True, "max_seconds": 240} for c in cap_calls
    )
    assert all(not p.exists() for p in paths)
    with np.load(output, allow_pickle=False) as data:
        assert data["matrix"].shape == (3, 512) and data["matrix"].dtype == np.float32


def test_failed_checkpoint_retains_audio_and_corrupt_files_are_counted(
    tmp_path: Path, monkeypatch
) -> None:
    path = write_wav(tmp_path / "good.wav")
    broken = tmp_path / "bad.mp3"
    broken.write_bytes(b"invalid")
    embedder = FakeEmbedder("clap", revision="195c3a3", dim=512)
    samples = [Sample(1, broken, "test", {}), Sample(2, path, "test", {})]
    report = module.embed_dataset(samples, embedder, tmp_path / "good.npz", delete_audio=True)
    assert report["skipped"] == 1 and broken.exists() and not path.exists()
    path = write_wav(path)

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(module, "atomic_npz", fail)
    with pytest.raises(OSError, match="disk full"):
        module.embed_dataset([samples[1]], embedder, tmp_path / "failed.npz", delete_audio=True)
    assert path.exists() and not (tmp_path / "failed.npz").exists()


def test_batched_window_vectors_match_canonical_track_embedding(tmp_path: Path) -> None:
    from mcrar.audio import load_audio
    from mcrar.ml.embedders import embed_track

    paths = [write_wav(tmp_path / f"{i}.wav", seconds=3 + i, freq=220 + i * 80) for i in range(5)]
    samples = [Sample(i, p, "train", {}) for i, p in enumerate(paths)]
    reference = FakeEmbedder("clap", revision="195c3a3", dim=512)
    expected = []
    for path in paths:
        audio = load_audio(path, sr=reference.sample_rate, mono=True, max_seconds=240)
        expected.append(embed_track(reference, audio.samples, audio.sr))
    batched = FakeEmbedder("clap", revision="195c3a3", dim=512)
    output = tmp_path / "batched.npz"
    module.embed_dataset(samples, batched, output, batch_size=32)
    assert len(batched.audio_calls) == 1
    with np.load(output, allow_pickle=False) as saved:
        np.testing.assert_allclose(saved["matrix"], np.stack(expected), atol=1e-6)


def test_all_missing_audio_still_writes_failure_report(tmp_path: Path) -> None:
    embedder = FakeEmbedder("clap", revision="195c3a3", dim=512)
    samples = [Sample(1, tmp_path / "missing.mp3", "test", {})]
    output = tmp_path / "new/embeddings/clap@195c3a3.npz"
    report = module.embed_dataset(samples, embedder, output)
    assert report["embedded"] == 0 and report["skipped"] == 1
    assert "audio file not found" in report["failures"]["1"]
    assert output.with_suffix(".report.json").is_file()
    assert not output.exists() and not embedder.audio_calls
