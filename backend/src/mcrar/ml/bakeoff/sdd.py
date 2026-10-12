"""The Song Describer Dataset (SDD) evaluation: load it, embed its audio, score text retrieval.

Layout under the SDD folder: ``song_describer.csv`` and
``audio/audio/<dir>/<track_id>.2min.mp3`` (the CSV ``path`` is ``<dir>/<track_id>.mp3``).
Embeddings are cached per model in ``embeddings/<model_id>.npz`` (``track_ids``, ``matrix``).
"""

from __future__ import annotations

import csv
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import numpy as np

from mcrar.audio import AudioError, load_audio
from mcrar.ml.bakeoff import metrics
from mcrar.ml.bakeoff.common import BakeoffError, intersect_ids, model_pairs, unit_rows
from mcrar.ml.embedders.base import Embedder, embed_track

CSV_NAME = "song_describer.csv"
AUDIO_SUBDIR = Path("audio") / "audio"
AUDIO_SUFFIX = ".2min.mp3"
EMBEDDINGS_SUBDIR = "embeddings"
PAIRWISE_METRICS = ("R@10", "MRR")


@dataclass(frozen=True)
class Caption:
    caption_id: int
    track_id: int
    text: str
    valid: bool


@dataclass(frozen=True)
class SddData:
    """``captions`` is the (possibly validated-only) caption set; ``tracks`` maps every track of
    the CSV whose audio file exists to that file; ``missing`` lists CSV tracks without a file."""

    captions: list[Caption]
    tracks: dict[int, Path]
    missing: list[int] = field(default_factory=list)


def audio_path(root: Path, csv_path: str) -> Path:
    """``34/1004034.mp3`` to ``<root>/audio/audio/34/1004034.2min.mp3``."""
    rel = PurePosixPath(csv_path.strip())
    return root / AUDIO_SUBDIR / rel.parent.as_posix() / (rel.stem + AUDIO_SUFFIX)


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("true", "1", "yes")


def load_sdd(root: Path, *, all_captions: bool = False) -> SddData:
    """Read the SDD CSV. By default only the validated subset of captions is kept; the track set
    (the retrieval gallery) always covers every track of the CSV."""
    csv_file = root / CSV_NAME
    if not csv_file.is_file():
        raise BakeoffError(f"Song Describer Dataset not found: expected {csv_file}")
    captions: list[Caption] = []
    paths: dict[int, str] = {}
    try:
        with open(csv_file, encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                track_id = int(row["track_id"])
                paths.setdefault(track_id, row["path"])
                valid = _truthy(row["is_valid_subset"])
                if all_captions or valid:
                    captions.append(
                        Caption(int(row["caption_id"]), track_id, row["caption"].strip(), valid)
                    )
    except (KeyError, ValueError, csv.Error) as exc:
        raise BakeoffError(f"cannot parse {csv_file} ({type(exc).__name__}: {exc})") from None
    tracks: dict[int, Path] = {}
    missing: list[int] = []
    for track_id in sorted(paths):
        file = audio_path(root, paths[track_id])
        if file.is_file():
            tracks[track_id] = file
        else:
            missing.append(track_id)
    return SddData(captions=captions, tracks=tracks, missing=missing)


# -- embedding the audio -------------------------------------------------------------------------


@dataclass
class SddEmbedding:
    track_ids: np.ndarray
    matrix: np.ndarray
    failures: list[tuple[int, str]]  # (track id, reason) for files that could not be embedded


ProgressFn = Callable[[int, int, int, str, str | None], None]  # index, total, track, status, why


def embed_sdd_tracks(
    embedder: Embedder,
    tracks: Mapping[int, Path],
    *,
    on_progress: ProgressFn | None = None,
) -> SddEmbedding:
    """One vector per track via :func:`embed_track`, decoded at the model's sample rate.

    Files that cannot be decoded (or give a degenerate embedding) are skipped and listed in
    ``failures``.
    """
    ids: list[int] = []
    rows: list[np.ndarray] = []
    failures: list[tuple[int, str]] = []
    total = len(tracks)
    for index, (track_id, file) in enumerate(sorted(tracks.items()), start=1):
        try:
            clip = load_audio(file, sr=embedder.sample_rate, mono=True)
            vector = embed_track(embedder, clip.samples, clip.sr)
        except (AudioError, ValueError) as exc:
            failures.append((track_id, str(exc)[:200]))
            if on_progress:
                on_progress(index, total, track_id, "failed", str(exc)[:200])
            continue
        ids.append(track_id)
        rows.append(vector)
        if on_progress:
            on_progress(index, total, track_id, "ok", None)
    matrix = np.stack(rows) if rows else np.empty((0, embedder.dim), dtype=np.float32)
    return SddEmbedding(np.asarray(ids, dtype=np.int64), matrix.astype(np.float32), failures)


def embeddings_path(root: Path, model_id: str) -> Path:
    return root / EMBEDDINGS_SUBDIR / f"{model_id}.npz"


def save_embeddings(path: Path, track_ids: np.ndarray, matrix: np.ndarray) -> None:
    """Write the npz atomically, so an interrupted run never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp.npz")
    np.savez(tmp, track_ids=np.asarray(track_ids, dtype=np.int64), matrix=matrix)
    os.replace(tmp, path)


def load_embeddings_file(path: Path) -> tuple[np.ndarray, np.ndarray]:
    try:
        with np.load(path) as data:
            return data["track_ids"].astype(np.int64), data["matrix"].astype(np.float32)
    except FileNotFoundError:
        raise BakeoffError(f"no SDD embeddings at {path}; run: mcrar bakeoff sdd-embed") from None
    except (OSError, ValueError, KeyError) as exc:
        raise BakeoffError(f"cannot read {path} ({type(exc).__name__})") from None


@dataclass(frozen=True)
class EmbedReport:
    model_id: str
    embedded: int
    failed: list[tuple[int, str]]
    missing: int
    elapsed_s: float
    path: Path


def embed_sdd(
    embedder: Embedder,
    data: SddData,
    root: Path,
    *,
    on_progress: ProgressFn | None = None,
) -> EmbedReport:
    """Embed every SDD track with one model and save ``embeddings/<model_id>.npz``."""
    started = time.perf_counter()
    result = embed_sdd_tracks(embedder, data.tracks, on_progress=on_progress)
    if len(result.track_ids) == 0:
        raise BakeoffError(f"{embedder.model_id}: no SDD track could be embedded")
    path = embeddings_path(root, embedder.model_id)
    save_embeddings(path, result.track_ids, result.matrix)
    return EmbedReport(
        model_id=embedder.model_id,
        embedded=len(result.track_ids),
        failed=result.failures,
        missing=len(data.missing),
        elapsed_s=time.perf_counter() - started,
        path=path,
    )


# -- evaluation ----------------------------------------------------------------------------------


def common_gallery(
    stored: Mapping[str, tuple[np.ndarray, np.ndarray]], csv_tracks: set[int]
) -> np.ndarray:
    """Sorted ids of the tracks that every model has embedded and the CSV lists."""
    common = intersect_ids([ids for ids, _ in stored.values()])
    return np.asarray([int(i) for i in common if int(i) in csv_tracks], dtype=np.int64)


def _round(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


def evaluate_sdd(
    captions: Sequence[Caption],
    gallery: np.ndarray,
    gallery_vectors: Mapping[str, np.ndarray],
    caption_vectors: Mapping[str, np.ndarray],
    *,
    n_resamples: int = 1000,
    seed: int = 0,
) -> dict:
    """Text-to-audio and audio-to-text retrieval for every model, with bootstrap intervals.

    ``gallery_vectors[m]`` is ``(n_tracks, dim)`` aligned to ``gallery``; ``caption_vectors[m]``
    is ``(n_captions, dim)`` aligned to ``captions``. Every caption's track must be in the
    gallery. All models are scored on exactly the same captions and tracks.
    """
    if not captions:
        raise BakeoffError("no captions to evaluate")
    position = {int(t): i for i, t in enumerate(gallery)}
    try:
        targets = np.asarray([position[c.track_id] for c in captions], dtype=np.int64)
    except KeyError as exc:
        raise ValueError(f"caption track {exc.args[0]} is not in the gallery") from None
    relevant = np.zeros((len(gallery), len(captions)), dtype=bool)  # [track, caption]
    relevant[targets, np.arange(len(captions))] = True
    query_tracks = np.flatnonzero(relevant.any(axis=1))

    results: dict[str, dict] = {}
    per_caption: dict[str, dict[str, np.ndarray]] = {}
    for model_id, tracks_m in gallery_vectors.items():
        scores = unit_rows(caption_vectors[model_id]) @ unit_rows(tracks_m).T  # [caption, track]
        ranks = metrics.target_ranks(scores, targets)
        hit10 = (ranks <= 10).astype(np.float64)
        rr = metrics.reciprocal_ranks(ranks)
        per_caption[model_id] = {"R@10": hit10, "MRR": rr}
        recall_ci = metrics.bootstrap_mean_ci(hit10, n_resamples=n_resamples, seed=seed)
        mrr_ci = metrics.bootstrap_mean_ci(rr, n_resamples=n_resamples, seed=seed)
        a2t_ranks = metrics.first_hit_ranks(scores.T[query_tracks], relevant[query_tracks])
        results[model_id] = {
            "t2a": {
                "n_captions": len(captions),
                "n_tracks": len(gallery),
                **{f"R@{k}": _round(metrics.recall_at_k(ranks, k)) for k in metrics.RECALL_KS},
                "median_rank": metrics.median_rank(ranks),
                "mrr": _round(mrr_ci.mean),
                "R@10_ci": [_round(recall_ci.lo), _round(recall_ci.hi)],
                "mrr_ci": [_round(mrr_ci.lo), _round(mrr_ci.hi)],
            },
            "a2t": {
                "n_tracks": int(len(query_tracks)),
                "n_captions": len(captions),
                **{f"R@{k}": _round(metrics.recall_at_k(a2t_ranks, k)) for k in metrics.RECALL_KS},
            },
        }

    pairwise = []
    for a, b in model_pairs(list(gallery_vectors)):
        for metric in PAIRWISE_METRICS:
            diff = metrics.paired_bootstrap_diff(
                per_caption[a][metric], per_caption[b][metric], n_resamples=n_resamples, seed=seed
            )
            pairwise.append(
                {
                    "a": a,
                    "b": b,
                    "metric": metric,
                    "diff": _round(diff.diff),
                    "ci": [_round(diff.lo), _round(diff.hi)],
                    "significant": diff.excludes_zero,
                }
            )
    return {
        "n_captions": len(captions),
        "n_tracks": int(len(gallery)),
        "n_query_tracks": int(len(query_tracks)),
        "results": results,
        "pairwise": pairwise,
    }
