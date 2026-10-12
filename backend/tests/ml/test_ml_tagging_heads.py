"""Head training/export preserves predictions and learns separable held-out vectors."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from tagging_support import synthetic

from mcrar.ml.tagging.runtime import load_tagger
from mcrar.ml.tagging.service import prediction_matrix
from mcrar.ml.tagging.training import calibrate, train_logreg, train_mlp


@pytest.mark.parametrize("variant", ["logreg", "mlp"])
def test_head_training_roundtrip_and_numpy_only_inference(tmp_path: Path, variant: str) -> None:
    x, y = synthetic(120)
    labels = ["a", "b", "c"]
    if variant == "logreg":
        tagger = train_logreg("genre", "single_label", labels, x[:60], y[:60])
        from sklearn.linear_model import LogisticRegression

        independent = LogisticRegression(C=10, max_iter=1000, random_state=0).fit(x[:60], y[:60])
        np.testing.assert_allclose(
            prediction_matrix(tagger, x), independent.predict_proba(x), atol=1e-6
        )
    else:
        tagger = train_mlp(
            "genre",
            "single_label",
            labels,
            x[:60],
            y[:60],
            x[60:90],
            y[60:90],
            hidden=16,
            epochs=100,
            patience=20,
            batch_size=20,
        )
    tagger = calibrate(tagger, x[60:90], y[60:90])
    expected = prediction_matrix(tagger, x[90:])
    assert (expected.argmax(axis=1) == y[90:]).mean() == 1
    path = tmp_path / "head.npz"
    tagger.save(path)
    actual = prediction_matrix(load_tagger(path), x[90:])
    np.testing.assert_allclose(actual, expected, atol=1e-6)
    # Fresh process: deny model frameworks during artifact loading and inference.
    code = """
import sys, importlib.abc
class Reject(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch', 'sklearn', 'transformers'}:
            raise AssertionError(fullname)
sys.meta_path.insert(0, Reject())
import numpy as np
from mcrar.ml.tagging.runtime import load_tagger
t = load_tagger(sys.argv[1])
x = np.zeros((1,512), dtype=np.float32); x[0,0] = 1
assert set(t.predict(x)) == {'a','b','c'}
"""
    result = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("kind", ["multi_label", "regression"])
def test_multilabel_and_regression_heads_roundtrip(tmp_path: Path, kind: str) -> None:
    x, classes = synthetic(90)
    y = (
        (classes == 0).astype(np.float32)[:, None]
        if kind == "multi_label"
        else (classes / 2).astype(np.float32)[:, None]
    )
    labels = ["happy"] if kind == "multi_label" else ["value"]
    for variant in ("logreg", "mlp"):
        tagger = (
            train_logreg("moodtheme", kind, labels, x[:60], y[:60])
            if variant == "logreg"
            else train_mlp(
                "moodtheme",
                kind,
                labels,
                x[:60],
                y[:60],
                x[60:75],
                y[60:75],
                hidden=12,
                epochs=100,
                batch_size=20,
            )
        )
        tagger = calibrate(tagger, x[60:75], y[60:75])
        tagger.save(tmp_path / "head.npz")
        probs = prediction_matrix(load_tagger(tmp_path / "head.npz"), x[75:])
        np.testing.assert_allclose(probs, prediction_matrix(tagger, x[75:]), atol=1e-6)
        assert np.all((probs >= 0) & (probs <= 1))
