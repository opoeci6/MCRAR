"""Shared helpers for the scene-label tests (not a test module; unique basename on purpose):
a synthetic catalog whose CLAP vectors carry the hand labels in a few coordinates, a registry
built with the fake CLAP, and a shortcut to label tracks."""

from __future__ import annotations

import numpy as np
from ml_support import FakeEmbedder

from mcrar.catalog import CatalogRepository, TrackRecord
from mcrar.config import Settings
from mcrar.ml.tagging.scenes import build_scene_entries
from mcrar.recommend.vocab import DEFAULT_SCENES

MODEL = "clap@195c3a3"
SIGNAL_SCENES = DEFAULT_SCENES[:3]  # combat, boss, exploration: written into coordinates 0, 1, 2


def clap() -> FakeEmbedder:
    return FakeEmbedder("clap", revision="195c3a3", dim=512)


def signal_catalog(
    repo: CatalogRepository, n: int = 120, seed: int = 0, *, source: str = "jamendo"
) -> tuple[list[int], np.ndarray, np.ndarray]:
    """``n`` tracks with CLAP vectors; scene ``j`` of :data:`SIGNAL_SCENES` is present in about
    half of them and moves coordinate ``j`` by +/-0.12, so a linear head can learn it.

    Returns ``(track ids, vectors, truth)`` with truth a bool ``[track, 3]`` matrix.
    """
    rng = np.random.default_rng(seed)
    truth = rng.random((n, len(SIGNAL_SCENES))) < 0.5
    vectors = rng.normal(size=(n, 512)).astype(np.float32) / np.sqrt(512)
    for j in range(len(SIGNAL_SCENES)):
        vectors[:, j] += np.where(truth[:, j], 0.12, -0.12)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    ids = []
    for i, vector in enumerate(vectors):
        track = repo.upsert_track(
            TrackRecord(source=source, source_id=str(1000 + i), title=f"T{i}", artist=f"A{i % 7}")
        )
        repo.set_embedding(track, MODEL, vector)
        ids.append(track)
    return ids, vectors, truth


def build_registry(settings: Settings, repo: CatalogRepository) -> list[dict]:
    """The two zero-shot scene entries (plain, centered), registered and selected."""
    return build_scene_entries(settings, clap(), repo)


def label_tracks(
    repo: CatalogRepository,
    ids: list[int],
    truth: np.ndarray,
    labeller: str = "owner",
    *,
    intensity: str | None = "mid",
) -> None:
    """Label ``ids`` from ``truth`` (bool ``[track, scene]`` over :data:`SIGNAL_SCENES`)."""
    for track, row in zip(ids, truth, strict=True):
        scenes = [s for s, on in zip(SIGNAL_SCENES, row, strict=True) if on]
        repo.set_scene_label(track, labeller, scenes, intensity, "labelled")
