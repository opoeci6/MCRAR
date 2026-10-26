"""The game-scene taggers (M9): zero-shot from text prompts, standardised on the owner's catalog.

There is no labelled dataset for game scenes, so the ``scene`` label set starts with two
zero-shot entries built from the prompts of ``prompts/scene.toml`` embedded with CLAP:

- ``zeroshot-catalog`` (centering 0): for each label the mean and spread of the catalog tracks'
  cosines to the label's text vector (the same z-score maths as the unsupervised FMA variants,
  with the catalog's stored CLAP vectors as the reference). A track's probability for a label
  says how much more it sounds like the prompts than an average track of the catalog does.
- ``zeroshot-catalog-centered`` (centering 0.75): the same, but each label's text vector first
  loses a share of the mean of all labels' vectors, ``t'_l = t_l - lambda * mean_l(t_l)``. The
  shared "video game music for ..." direction otherwise dominates, so the same cinematic tracks
  top many scenes; removing part of it spreads the top lists out.

Which one is better is for the hand labels to decide (``mcrar scenes eval`` and ``train``). The
centered vectors are what the artifact stores, so :meth:`Tagger.predict` needs no change. No
external labels are used, so both entries are commercial-safe, and both carry ``metrics: null``
(not evaluated yet). Until a set has an evaluated entry the registry selects the unevaluated
entry marked ``"prefer": true`` (the centered one), else the newest. Building again after the
catalog grew replaces both entries, because the artifacts are content-addressed on the reference
statistics; ``mcrar tag --label-sets scene`` then tags the catalog with the selected version.
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
CENTERED_VARIANT = "zeroshot-catalog-centered"
CENTERING = 0.75  # the share of the mean label vector the centered variant removes
# (variant, centering): the plain entry first, the centered one is preferred until labels exist
VARIANTS: tuple[tuple[str, float], ...] = ((VARIANT, 0.0), (CENTERED_VARIANT, CENTERING))
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


def center_vectors(vectors: dict, centering: float) -> dict:
    """``vectors`` with each label's text vector reduced by ``centering`` times the mean of all
    labels' text vectors. Centering 0 returns the vectors as they are."""
    if centering == 0:
        return vectors
    text = vectors["text_vectors"]
    centered = (text - centering * text.mean(axis=0, keepdims=True)).astype(np.float32)
    return {**vectors, "text_vectors": centered}


def build_scene_entries(
    settings: Settings,
    embedder: Embedder,
    repo: CatalogRepository,
    *,
    models_dir: Path | None = None,
) -> list[dict]:
    """Build the scene artifacts, register them and select one; returns the registry entries
    (plain, then centered).

    ``embedder`` must be CLAP (``clap@195c3a3``); it embeds the prompts only. ``models_dir``
    overrides ``settings.models_dir`` (where ``registry.json`` and ``heads/`` live). Entries of
    other variants (a trained head) are kept.
    """
    if models_dir is not None:
        settings = settings.model_copy(update={"models_dir": models_dir})
    reference = catalog_reference(repo)
    labels = list(DEFAULT_SCENES)
    vectors = prompt_vectors(embedder, PROMPTS / f"{SCENE}.toml", labels)

    heads = settings.models_dir / "heads"
    heads.mkdir(parents=True, exist_ok=True)
    created = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    entries = []
    for variant, centering in VARIANTS:
        tagger = unsupervised(SCENE, KIND, labels, center_vectors(vectors, centering), reference)
        temporary = heads / f".{SCENE}-{variant}.npz"
        tagger.save(temporary)
        identity = entry_id(SCENE, variant, temporary)
        temporary.replace(heads / f"{identity}.npz")
        entry = {
            "id": identity,
            "method": tagger.method,
            "variant": variant,
            "file": f"heads/{identity}.npz",
            "seed": 0,
            "metrics": None,
            "created_at": created,
            "commercial_ok": True,
            "data_license": DATA_LICENSE,
            "prompts": f"backend/src/mcrar/ml/tagging/prompts/{SCENE}.toml",
            "reference_data": f"catalog@{len(reference)} tracks",
            "centering": centering,
            "embedding": {"model": EMBEDDER},
        }
        if variant == CENTERED_VARIANT:
            entry["prefer"] = True  # selected while no entry has been evaluated
        entries.append(entry)

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
    rebuilt = {variant for variant, _ in VARIANTS}
    spec["entries"] = [e for e in spec["entries"] if e["variant"] not in rebuilt] + entries
    chosen = select_entry(spec)
    registry.setdefault("selected", {})[SCENE] = chosen["id"] if chosen else None
    write_registry(settings, registry)
    return entries
