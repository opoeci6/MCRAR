"""Weak-label check on the catalog: text query "<genre> music" against the uploader's genre tags.

The labels are what the uploader typed on Jamendo, so they are noisy: a "rock" track may not
sound like rock and a rock-sounding track may lack the tag. Use the numbers to compare models
with each other, not as absolute accuracy.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from mcrar.ml.bakeoff import metrics
from mcrar.ml.bakeoff.common import unit_rows

LABEL_NOTE = (
    "Relevance comes from the uploader's Jamendo genre tags, which are noisy weak labels. "
    "Compare models with each other; do not read the values as absolute accuracy."
)
QUERY_TEMPLATE = "{genre} music"
P_AT = 10


def query_text(tag: str) -> str:
    return QUERY_TEMPLATE.format(genre=tag)


def track_genres(source_tags: Mapping | None) -> set[str]:
    """The lower-cased genre tags of a track's ``source_tags`` (empty when there are none)."""
    genres = (source_tags or {}).get("genres") or []
    return {str(g).strip().lower() for g in genres if str(g).strip()}


def select_tags(
    genres_by_track: Mapping[int, set[str]], track_ids: np.ndarray, min_tracks: int
) -> list[tuple[str, int]]:
    """Tags carried by at least ``min_tracks`` of ``track_ids``, with their counts.

    A tag carried by every track is dropped: it cannot discriminate. Sorted by tag name.
    """
    counts: dict[str, int] = {}
    for track_id in track_ids:
        for tag in genres_by_track.get(int(track_id), ()):
            counts[tag] = counts.get(tag, 0) + 1
    return sorted((tag, n) for tag, n in counts.items() if n >= min_tracks and n < len(track_ids))


def evaluate_tags(
    tags: list[tuple[str, int]],
    track_ids: np.ndarray,
    genres_by_track: Mapping[int, set[str]],
    gallery_vectors: Mapping[str, np.ndarray],
    query_vectors: Mapping[str, np.ndarray],
) -> dict:
    """AP and precision@10 per tag and model, plus macro averages.

    ``gallery_vectors[m]`` is ``(n_tracks, dim)`` aligned to ``track_ids``;
    ``query_vectors[m]`` is ``(n_tags, dim)`` aligned to ``tags``.
    """
    relevance = np.asarray(
        [[tag in genres_by_track.get(int(t), ()) for t in track_ids] for tag, _ in tags],
        dtype=bool,
    ).reshape(len(tags), len(track_ids))
    results: dict[str, dict] = {}
    for model_id, tracks_m in gallery_vectors.items():
        scores = unit_rows(query_vectors[model_id]) @ unit_rows(tracks_m).T
        per_tag = {}
        for i, (tag, _) in enumerate(tags):
            per_tag[tag] = {
                "AP": round(metrics.average_precision(scores[i], relevance[i]), 4),
                "P@10": round(metrics.precision_at_k(scores[i], relevance[i], P_AT), 4),
            }
        results[model_id] = {
            "macro_AP": round(float(np.mean([v["AP"] for v in per_tag.values()])), 4),
            "macro_P@10": round(float(np.mean([v["P@10"] for v in per_tag.values()])), 4),
            "per_tag": per_tag,
        }
    n = len(track_ids)
    return {
        "note": LABEL_NOTE,
        "n_tracks": n,
        "tags": [
            {
                "tag": tag,
                "query": query_text(tag),
                "n_relevant": count,
                "prevalence": round(count / n, 4),
            }
            for tag, count in tags
        ],
        "results": results,
    }
