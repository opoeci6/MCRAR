"""The game-scene tagger (M9): zero-shot from text prompts, standardised on the owner's catalog.

There is no labelled dataset for game scenes, so the ``scene`` label set has one entry, the
``zeroshot-catalog`` variant: the prompts of ``prompts/scene.toml`` embedded with CLAP, and for
each label the mean and spread of the catalog tracks' cosines to it (the same z-score maths as the
unsupervised FMA variants, with the catalog's stored CLAP vectors as the reference). A track's
probability for a label says how much more it sounds like the prompts than an average track of
the catalog does. No external labels are used, so the entry is commercial-safe.

The entry carries ``metrics: null`` (not evaluated yet); the registry selects it while the set
has no evaluated entry. Building again after the catalog grew replaces the entry, because the
artifact is content-addressed on the reference statistics; ``mcrar tag --label-sets scene``
then tags the catalog with the new version.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from mcrar.catalog import CatalogRepository
from mcrar.config import Settings
from mcrar.ml.datasets.embedding import EMBEDDER
from mcrar.ml.embedders import Embedder
from mcrar.ml.tagging.registry import entry_id, read_registry, select_entry, write_registry
from mcrar.ml.tagging.zeroshot import PROMPTS, prompt_vectors, unsupervised
from mcrar.recommend.vocab import DEFAULT_SCENE_DISPLAY, DEFAULT_SCENES, SCENE

VARIANT = "zeroshot-catalog"
KIND = "multi_label"
MIN_REFERENCE = 50  # fewer catalog embeddings give meaningless standard deviations
DATA_LICENSE = "none (text prompts only; catalog embeddings used as the score baseline)"


def catalog_reference(repo: CatalogRepository) -> np.ndarray:
    """The catalog's CLAP embeddings, checked: the z-score reference of the scene tagger.

    Raises ``ValueError`` when there are fewer than :data:`MIN_REFERENCE` or they are unusable.
    """
    _, matrix = repo.load_embeddings(EMBEDDER)
    if len(matrix) < MIN_REFERENCE:
        raise ValueError(
            f"the catalog has {len(matrix)} {EMBEDDER} embeddings; scene tags need at least "
            f"{MIN_REFERENCE} to standardise against (run: mcrar ingest, then mcrar embed)"
        )
    if (
        matrix.shape[1] != 512
        or not np.isfinite(matrix).all()
        or not np.allclose(np.linalg.norm(matrix, axis=1), 1, atol=1e-3)
    ):
        raise ValueError(f"the catalog's {EMBEDDER} embeddings are not finite unit vectors")
    return matrix


def build_scene_entry(
    settings: Settings,
    embedder: Embedder,
    repo: CatalogRepository,
    *,
    models_dir: Path | None = None,
) -> dict:
    """Build the scene artifact, register it and select it; returns the registry entry.

    ``embedder`` must be CLAP (``clap@195c3a3``); it embeds the prompts only. ``models_dir``
    overrides ``settings.models_dir`` (where ``registry.json`` and ``heads/`` live).
    """
    if models_dir is not None:
        settings = settings.model_copy(update={"models_dir": models_dir})
    reference = catalog_reference(repo)
    labels = list(DEFAULT_SCENES)
    vectors = prompt_vectors(embedder, PROMPTS / f"{SCENE}.toml", labels)
    tagger = unsupervised(SCENE, KIND, labels, vectors, reference)

    heads = settings.models_dir / "heads"
    heads.mkdir(parents=True, exist_ok=True)
    temporary = heads / f".{SCENE}-{VARIANT}.npz"
    tagger.save(temporary)
    identity = entry_id(SCENE, VARIANT, temporary)
    temporary.replace(heads / f"{identity}.npz")

    entry = {
        "id": identity,
        "method": tagger.method,
        "variant": VARIANT,
        "file": f"heads/{identity}.npz",
        "seed": 0,
        "metrics": None,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "commercial_ok": True,
        "data_license": DATA_LICENSE,
        "prompts": f"backend/src/mcrar/ml/tagging/prompts/{SCENE}.toml",
        "reference_data": f"catalog@{len(reference)} tracks",
        "embedding": {"model": EMBEDDER},
    }
    registry = (
        read_registry(settings)
        if (settings.models_dir / "registry.json").is_file()
        else {"schema": 1, "embedder": EMBEDDER, "label_sets": {}}
    )
    spec = registry["label_sets"].setdefault(
        SCENE,
        {
            "kind": KIND,
            "labels": labels,
            "display": {label: DEFAULT_SCENE_DISPLAY[label] for label in labels},
            "entries": [],
        },
    )
    if (spec["kind"], spec["labels"]) != (KIND, labels):
        raise ValueError("the registry's scene labels differ from the built-in scene labels")
    spec["entries"] = [e for e in spec["entries"] if e["variant"] != VARIANT] + [entry]
    chosen = select_entry(spec)
    registry.setdefault("selected", {})[SCENE] = chosen["id"] if chosen else None
    write_registry(settings, registry)
    return entry
