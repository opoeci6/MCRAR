"""Small normalized vectors and portable artifacts for the tagging tests."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from mcrar.config import Settings
from mcrar.ml.tagging.registry import entry_id, write_registry
from mcrar.ml.tagging.runtime import Tagger


def synthetic(n: int = 120, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    y = np.arange(n) % 3
    x = rng.normal(0, 0.005, (n, 512)).astype(np.float32)
    x[np.arange(n), y] += 1
    x /= np.linalg.norm(x, axis=1, keepdims=True)
    return x, y


def fixture_tagger(label_set: str = "genre", method: str = "head") -> Tagger:
    weights = np.zeros((512, 3), dtype=np.float32)
    weights[:3] = np.eye(3) * 8
    arrays = (
        {"weight": weights, "bias": np.zeros(3, dtype=np.float32)}
        if method == "head"
        else {"text_vectors": weights.T}
    )
    return Tagger(label_set, "single_label", ["a", "b", "c"], "test@1234567", method, arrays)


def register(
    settings: Settings,
    tagger: Tagger | None = None,
    *,
    commercial: bool = True,
    metric: float = 0.8,
    variant: str = "logreg",
) -> dict:
    tagger = tagger or fixture_tagger()
    path = settings.models_dir / "heads/tmp.npz"
    tagger.save(path)
    identity = entry_id(tagger.label_set, variant, path)
    path.rename(path.with_name(identity + ".npz"))
    entry = {
        "id": identity,
        "method": tagger.method,
        "variant": variant,
        "file": f"heads/{identity}.npz",
        "seed": 0,
        "data_license": "CC BY 4.0",
        "commercial_ok": commercial,
        "created_at": datetime.now(UTC).isoformat(),
        "metrics": {"split": "test", "primary": "macro_f1", "macro_f1": metric},
    }
    registry = {
        "schema": 1,
        "embedder": "clap@195c3a3",
        "label_sets": {
            tagger.label_set: {
                "kind": tagger.kind,
                "labels": tagger.labels,
                "display": {t: t for t in tagger.labels},
                "entries": [entry],
            }
        },
    }
    write_registry(settings, registry)
    return registry
