"""The pooled, blind rating set: what each model proposes for each query, shuffled together.

``build_candidates`` returns the public items (which never say which model proposed them) and a
private map from each track back to the models and ranks that proposed it. ``score_ratings``
joins the user's ratings with that map.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from mcrar.catalog import CatalogRepository, StoredTrack
from mcrar.ml.bakeoff import metrics
from mcrar.ml.bakeoff.common import BakeoffError, model_pairs, unit_rows
from mcrar.ml.bakeoff.queries import query_ids

SCORES = (0, 1, 2)
DEFAULT_PER_MODEL = 3


def blind_key(query: str, track_id: int) -> str:
    """Sort key that orders a query's pool deterministically but unrelated to any model."""
    return hashlib.sha256(f"{query}\x00{track_id}".encode()).hexdigest()


def item_for(track: StoredTrack, features: Mapping[str, Any] | None) -> dict[str, Any]:
    """The public description of one candidate. Nothing in it depends on a model."""
    tags = track.source_tags or {}
    bpm = features.get("bpm") if features else None
    energy = features.get("energy") if features else None
    return {
        "track_id": track.id,
        "title": track.title,
        "artist": track.artist,
        "source_url": track.source_url,
        "risk": track.risk,
        "license_code": track.license_code,
        "bpm": None if bpm is None else round(float(bpm)),
        "key": features.get("key") if features else None,
        "mode": features.get("mode") if features else None,
        "energy": None if energy is None else round(float(energy), 2),
        "genres": list(tags.get("genres") or []),
        "vartags": list(tags.get("vartags") or []),
        "duration_s": None if track.duration_s is None else round(float(track.duration_s), 1),
    }


def eligible_tracks(repo: CatalogRepository, common_ids: np.ndarray) -> list[StoredTrack]:
    """Tracks with embeddings for every compared model and a page the user can open."""
    wanted = {int(i) for i in common_ids}
    return [t for t in repo.iter_tracks() if t.id in wanted and t.source_url]


def rank_pool(ids: np.ndarray, scores: np.ndarray, preferred: set[int]) -> list[int]:
    """Track ids best first; tracks in ``preferred`` (downloadable) all rank above the rest."""
    order = np.lexsort((ids, -scores))
    ranked = [int(ids[i]) for i in order]
    return [t for t in ranked if t in preferred] + [t for t in ranked if t not in preferred]


def build_candidates(
    queries: Sequence[str],
    model_ids: Sequence[str],
    ids: np.ndarray,
    gallery_vectors: Mapping[str, np.ndarray],
    query_vectors: Mapping[str, np.ndarray],
    items: Mapping[int, dict[str, Any]],
    preferred: set[int],
    per_model: int,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, list[dict[str, Any]]]]]:
    """``([{id, text, items}], private)`` for the given queries.

    ``ids`` are the eligible tracks; ``gallery_vectors[m]`` is ``(n, dim)`` aligned to ``ids``
    and ``query_vectors[m]`` is ``(n_queries, dim)``. For each query and model the top
    ``per_model`` tracks are taken (downloadable tracks first). ``private[query_id][track_id]``
    lists ``{"model", "rank"}`` for each model that proposed the track.
    """
    if per_model < 1:
        raise ValueError("per_model must be at least 1")
    qids = query_ids(len(queries))
    out: list[dict[str, Any]] = []
    private: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for qi, (qid, text) in enumerate(zip(qids, queries, strict=True)):
        proposed: dict[int, list[dict[str, Any]]] = {}
        for model_id in model_ids:
            scores = (
                unit_rows(gallery_vectors[model_id])
                @ unit_rows(query_vectors[model_id][qi : qi + 1])[0]
            )
            for rank, track_id in enumerate(rank_pool(ids, scores, preferred)[:per_model], 1):
                proposed.setdefault(track_id, []).append({"model": model_id, "rank": rank})
        pool = sorted(proposed, key=lambda t: blind_key(text, t))
        out.append({"id": qid, "text": text, "items": [items[t] for t in pool]})
        private[qid] = {str(t): proposed[t] for t in pool}
    return out, private


# -- scoring the user's ratings --------------------------------------------------------------------


def parse_ratings(data: Any) -> dict[tuple[str, int], int]:
    """``{"ratings": [{"query_id", "track_id", "score"}]}`` to ``{(query_id, track_id): score}``.

    A repeated pair keeps the last score. Invalid entries raise ``BakeoffError``.
    """
    entries = data.get("ratings") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise BakeoffError(
            'ratings file must look like {"ratings": [{"query_id", "track_id", "score"}]}'
        )
    ratings: dict[tuple[str, int], int] = {}
    for n, entry in enumerate(entries, start=1):
        try:
            query_id, track_id, score = (
                str(entry["query_id"]),
                int(entry["track_id"]),
                entry["score"],
            )
        except (KeyError, TypeError, ValueError):
            raise BakeoffError(f"rating #{n} needs query_id, track_id and score") from None
        if isinstance(score, bool) or score not in SCORES:
            raise BakeoffError(f"rating #{n}: score must be 0, 1 or 2, got {score!r}")
        ratings[(query_id, track_id)] = int(score)
    return ratings


def _model_lists(
    private: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]], k: int
) -> dict[str, dict[str, list[int]]]:
    """``{model: {query_id: [track ids by rank, up to rank k]}}`` from the private map."""
    lists: dict[str, dict[str, list[tuple[int, int]]]] = {}
    for qid, tracks in private.items():
        for track_id, proposers in tracks.items():
            for p in proposers:
                if p["rank"] <= k:
                    lists.setdefault(p["model"], {}).setdefault(qid, []).append(
                        (int(p["rank"]), int(track_id))
                    )
    return {
        model: {qid: [t for _, t in sorted(pairs)] for qid, pairs in per_query.items()}
        for model, per_query in lists.items()
    }


def _macro(per_query: Mapping[str, Mapping[str, Any]], queries: list[str], field: str) -> Any:
    return round(float(np.mean([per_query[q][field] for q in queries])), 4) if queries else None


def score_ratings(
    candidates: Mapping[str, Any],
    private: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]],
    ratings: Mapping[tuple[str, int], int],
    *,
    k: int,
    model_order: Sequence[str] | None = None,
    n_resamples: int = 1000,
    seed: int = 0,
) -> dict[str, Any]:
    """Per-model quality of the top ``k`` from the user's ratings.

    Per query: the mean rating of the model's rated top-k items, nDCG@k (gain = rating, the
    ideal ranking drawn from the rated pool of that query) and the share of rated items rated
    at least 1. Unrated items are left out and counted. Model figures are means over queries
    with at least one rated item; model pairs are compared with a paired bootstrap over the
    queries both models were scored on.
    """
    per_model_n = int(candidates.get("per_model", k))
    if not 1 <= k <= per_model_n:
        raise BakeoffError(f"k must be between 1 and per_model ({per_model_n}), got {k}")
    pool_ids = {q["id"]: [int(i["track_id"]) for i in q["items"]] for q in candidates["queries"]}
    unknown = {pair for pair in ratings if pair[1] not in pool_ids.get(pair[0], ())}
    rated = {pair: s for pair, s in ratings.items() if pair not in unknown}
    pool_total = sum(len(v) for v in pool_ids.values())

    lists = _model_lists(private, k)
    models = list(model_order or candidates.get("models") or lists)
    results: dict[str, dict[str, Any]] = {}
    per_query_values: dict[str, dict[str, float]] = {}
    for model in models:
        per_query: dict[str, dict[str, Any]] = {}
        n_items = n_rated = 0
        for qid in pool_ids:
            ranked = lists.get(model, {}).get(qid, [])
            if not ranked:
                continue
            scored = [rated[(qid, t)] for t in ranked if (qid, t) in rated]
            pool_gains = [rated[(qid, t)] for t in pool_ids[qid] if (qid, t) in rated]
            n_items += len(ranked)
            n_rated += len(scored)
            per_query[qid] = {
                "n_items": len(ranked),
                "n_rated": len(scored),
                "n_unrated": len(ranked) - len(scored),
                "mean_rating": float(np.mean(scored)) if scored else None,
                "ndcg": metrics.ndcg_at_k(scored, pool_gains, k) if scored else None,
                "share_relevant": float(np.mean([s >= 1 for s in scored])) if scored else None,
            }
        scored_queries = [q for q, v in per_query.items() if v["n_rated"]]

        results[model] = {
            "mean_rating": _macro(per_query, scored_queries, "mean_rating"),
            "ndcg": _macro(per_query, scored_queries, "ndcg"),
            "share_relevant": _macro(per_query, scored_queries, "share_relevant"),
            "n_items": n_items,
            "n_rated": n_rated,
            "n_unrated": n_items - n_rated,
            "coverage": round(n_rated / n_items, 4) if n_items else 0.0,
            "n_queries_scored": len(scored_queries),
            "per_query": {
                q: {f: (round(x, 4) if isinstance(x, float) else x) for f, x in v.items()}
                for q, v in per_query.items()
            },
        }
        per_query_values[model] = {q: per_query[q]["mean_rating"] for q in scored_queries}

    pairwise = []
    for a, b in model_pairs(models):
        shared = sorted(set(per_query_values[a]) & set(per_query_values[b]))
        if not shared:
            continue
        diff = metrics.paired_bootstrap_diff(
            [per_query_values[a][q] for q in shared],
            [per_query_values[b][q] for q in shared],
            n_resamples=n_resamples,
            seed=seed,
        )
        pairwise.append(
            {
                "a": a,
                "b": b,
                "metric": "mean_rating",
                "n_queries": len(shared),
                "diff": round(diff.diff, 4),
                "ci": [round(diff.lo, 4), round(diff.hi, 4)],
                "significant": diff.excludes_zero,
            }
        )
    return {
        "k": k,
        "n_queries": len(pool_ids),
        "models": models,
        "coverage": {
            "pool_items": pool_total,
            "pool_rated": len(rated),
            "pool_fraction": round(len(rated) / pool_total, 4) if pool_total else 0.0,
            "unknown_ratings_ignored": len(unknown),
            "min_model_fraction": min((r["coverage"] for r in results.values()), default=0.0),
        },
        "results": results,
        "pairwise": pairwise,
    }
