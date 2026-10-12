"""Prompt averaging is mean cosine; label-free normalisation accepts no target data."""

from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np
import pytest
from ml_support import FakeEmbedder
from tagging_support import synthetic

from mcrar.ml.tagging.runtime import load_tagger
from mcrar.ml.tagging.service import prediction_matrix
from mcrar.ml.tagging.training import calibrate
from mcrar.ml.tagging.zeroshot import calibrated, prompt_vectors, unsupervised


def test_ensemble_and_both_variants_use_stored_text_vectors(tmp_path: Path) -> None:
    path = tmp_path / "prompt.toml"
    path.write_text(
        'templates = ["{label} music", "a {label} song"]\n[labels]\n'
        'a = ["happy", "joyful"]\nb = ["sad"]\nc = ["calm"]\n'
    )
    embedder = FakeEmbedder("clap", revision="195c3a3", dim=512)
    vectors = prompt_vectors(embedder, path, ["a", "b", "c"])
    x, y = synthetic()
    owners = vectors["prompt_owners"]
    np.testing.assert_allclose(
        x @ vectors["text_vectors"].T,
        np.column_stack(
            [(x @ vectors["prompt_vectors"][owners == i].T).mean(axis=1) for i in range(3)]
        ),
        atol=1e-7,
    )
    before = len(embedder.text_calls)
    supervised = calibrated("genre", "single_label", ["a", "b", "c"], vectors, x, y)
    free = unsupervised("genre", "single_label", ["a", "b", "c"], vectors, x)
    assert "y" not in inspect.signature(unsupervised).parameters
    assert "validation_y" not in inspect.signature(unsupervised).parameters
    assert len(embedder.text_calls) == before
    for tagger in (supervised, free):
        tagger.save(tmp_path / "tagger.npz")
        probs = prediction_matrix(load_tagger(tmp_path / "tagger.npz"), x)
        assert ((probs >= 0) & (probs <= 1)).all()
        np.testing.assert_allclose(probs.sum(axis=1), 1, atol=1e-6)
    with pytest.raises(ValueError, match="must never"):
        calibrate(free, x, y)


def test_unsupervised_sigmoid_and_constant_reference_are_finite() -> None:
    x, _ = synthetic()
    vectors = {"text_vectors": np.ones((1, 512), dtype=np.float32)}
    for kind in ("multi_label", "regression"):
        t = unsupervised("valence", kind, ["value"], vectors, np.tile(x[:1], (4, 1)))
        probs = t.predict(x)["value"]
        assert np.isfinite(probs).all() and ((probs >= 0) & (probs <= 1)).all()


def test_reference_loader_reads_no_labels_and_refuses_partial_runs(
    tmp_path: Path, monkeypatch
) -> None:
    from mcrar.config import get_settings
    from mcrar.ml.datasets import Sample
    from mcrar.ml.tagging import service

    class NoLabels(dict):
        def __getitem__(self, key):
            raise AssertionError("unsupervised reference must not read labels")

    samples = [
        Sample(i, tmp_path / str(i), "train" if i < 3 else "test", NoLabels()) for i in range(4)
    ]
    monkeypatch.setattr(service, "samples_for", lambda *args: samples)
    settings = get_settings()
    path = service.dataset_root(settings, "fma-medium") / "embeddings/clap@195c3a3.npz"
    path.parent.mkdir(parents=True)
    x, _ = synthetic(4)
    np.savez(path, ids=np.arange(4), matrix=x)
    np.testing.assert_array_equal(service.reference_embeddings(settings), x[:3])
    np.savez(path, ids=np.arange(3), matrix=x[:3])
    with pytest.raises(ValueError, match="incomplete"):
        service.reference_embeddings(settings)
