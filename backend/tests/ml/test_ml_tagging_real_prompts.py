"""Committed zero-shot text embeddings must match the pinned CLAP prompt encoder."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from mcrar.config import get_settings
from mcrar.ml.embedders import load_embedder
from mcrar.ml.tagging.runtime import load_tagger
from mcrar.ml.tagging.zeroshot import PROMPTS, prompt_vectors


@pytest.mark.models
def test_committed_prompt_embeddings_match_fresh_clap() -> None:
    root = Path(__file__).resolve().parents[3]
    settings = get_settings(home=root, models_dir=root / "models")
    registry = json.loads((settings.models_dir / "registry.json").read_text())
    entries = [
        (name, spec, e)
        for name, spec in registry["label_sets"].items()
        for e in spec["entries"]
        if e["method"] == "zeroshot"
    ]
    if not entries:
        pytest.fail("no committed zero-shot artifacts to validate")
    embedder = load_embedder("clap", settings=settings)
    try:
        for name, spec, entry in entries:
            fresh = prompt_vectors(embedder, PROMPTS / f"{name}.toml", spec["labels"])
            saved = load_tagger(settings.models_dir / entry["file"])
            assert saved.arrays["prompt_texts"].tolist() == fresh["prompt_texts"].tolist()
            assert str(saved.arrays["prompt_sha256"]) == str(fresh["prompt_sha256"])
            np.testing.assert_allclose(
                saved.arrays["text_vectors"], fresh["text_vectors"], atol=2e-3
            )
    finally:
        embedder.close()
