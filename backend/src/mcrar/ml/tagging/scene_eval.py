"""Measure the scene entries against the hand labels (M9): ``mcrar scenes eval``.

Every scene entry is scored the same way (see :mod:`mcrar.ml.tagging.scene_head`):

- **Pool**: on the labelled tracks that have a CLAP embedding, precision@k and average
  precision per scene, and the mean P@k over the scenes with at least 5 positives (the others
  say "too few"). The zero-shot entries are scored from their artifacts; the trained head is
  scored out-of-fold (K-fold with the seed), with the best zero-shot entry filling the scenes it
  cannot train.
- **Catalog**: each entry's top-k tracks of the whole catalog per scene, and how many of those
  have been labelled. The precision is over the labelled ones only; the unlabelled count says how
  much of the list that leaves unmeasured (like ``mcrar ratings eval``). A registered head was
  trained on these labels, so its catalog precision is flagged ``in_sample``.
- **Intensity**: Spearman's rho (ties get average ranks) of the DSP ``energy`` and of the arousal
  head's value against the labelled intensity (low 1, mid 2, high 3; the mean over a track's
  labellers).
- **Agreement**: Cohen's kappa per scene, and the exact-match rate of the intensity, between the
  two labellers with the most labels, on the tracks both labelled.

Several labellers are merged per track: a scene is present when at least half of them marked it.
The result is written to ``<data>/benchmarks/results/scenes_<UTC timestamp>.json``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from mcrar.catalog import CatalogRepository, SceneLabel
from mcrar.config import Settings
from mcrar.ml.datasets.embedding import EMBEDDER
from mcrar.ml.tagging.registry import select_entry
from mcrar.ml.tagging.runtime import load_tagger
from mcrar.ml.tagging.scene_head import (
    HEAD_VARIANT,
    MIN_POSITIVES,
    best_zeroshot,
    cross_validated_head_scores,
    entry_metrics,
    labelled_data,
    probability_matrix,
    scene_registry,
    scene_spec,
    zeroshot_entries,
)
from mcrar.ml.tagging.scene_labels import merge_labels
from mcrar.recommend.tags import allowed_tag_versions

RESULTS_DIR = "benchmarks/results"


# -- statistics --------------------------------------------------------------------------------


def spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    """Spearman's rho: the Pearson correlation of the average ranks (so ties are handled).
    None for fewer than 3 pairs or when one side is constant."""
    from scipy.stats import rankdata

    x, y = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if len(x) != len(y):
        raise ValueError("the two samples must be the same length")
    if len(x) < 3:
        return None
    rx, ry = rankdata(x), rankdata(y)
    if rx.std() == 0 or ry.std() == 0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


def cohens_kappa(a: np.ndarray, b: np.ndarray) -> float | None:
    """Cohen's kappa of two binary ratings of the same items; None when chance agreement is
    already perfect (both always say the same constant) or there are no items."""
    x, y = np.asarray(a, dtype=bool), np.asarray(b, dtype=bool)
    if len(x) != len(y):
        raise ValueError("the two ratings must be the same length")
    if len(x) == 0:
        return None
    observed = float((x == y).mean())
    pa, pb = float(x.mean()), float(y.mean())
    chance = pa * pb + (1 - pa) * (1 - pb)
    return None if chance >= 1 else (observed - chance) / (1 - chance)


# -- the parts ---------------------------------------------------------------------------------


def agreement(labels: list[SceneLabel], scene_ids: list[str]) -> dict | None:
    """Kappa per scene and intensity agreement between the two labellers with the most labels
    (``labelled`` status), on the tracks both labelled. None with fewer than two labellers."""
    own: dict[str, dict[int, SceneLabel]] = {}
    for label in labels:
        if label.status == "labelled":
            own.setdefault(label.labeller, {})[label.track_id] = label
    ranked = sorted(own, key=lambda name: (-len(own[name]), name))
    if len(ranked) < 2:
        return None
    first, second = ranked[0], ranked[1]
    shared = sorted(set(own[first]) & set(own[second]))
    per_scene: dict[str, dict] = {}
    for scene in scene_ids:
        a = np.array([scene in own[first][t].scenes for t in shared], dtype=bool)
        b = np.array([scene in own[second][t].scenes for t in shared], dtype=bool)
        per_scene[scene] = {"kappa": cohens_kappa(a, b), "n": len(shared)}
    kappas = [s["kappa"] for s in per_scene.values() if s["kappa"] is not None]
    both = [
        (own[first][t].intensity, own[second][t].intensity)
        for t in shared
        if own[first][t].intensity is not None and own[second][t].intensity is not None
    ]
    return {
        "labellers": [first, second],
        "n_tracks": len(shared),
        "per_scene": per_scene,
        "mean_kappa": float(np.mean(kappas)) if kappas else None,
        "intensity": {
            "match_rate": float(np.mean([x == y for x, y in both])) if both else None,
            "n": len(both),
        },
    }


def intensity_correlations(repo: CatalogRepository, settings: Settings, merged) -> dict:
    """Spearman of the DSP energy and of the arousal head's value against the merged intensity."""
    ids = [int(t) for t in merged.track_ids]
    wanted = merged.intensity
    features = repo.get_features_many(ids)
    energy = np.full(len(ids), np.nan)
    for i, t in enumerate(ids):
        value = (features.get(t) or {}).get("energy")
        if value is not None:  # 0.0 is a real (silent) energy
            energy[i] = value
    allowed = allowed_tag_versions(settings).get("arousal")
    arousal = np.full(len(ids), np.nan)
    if allowed is not None:
        for i, t in enumerate(ids):
            for row in repo.get_tag_probs(t, head="arousal"):
                if row.label == "value" and row.model_version == allowed:
                    arousal[i] = row.prob
    out = {}
    for name, values in (("energy", energy), ("arousal", arousal)):
        ok = ~np.isnan(values) & ~np.isnan(wanted)
        out[name] = {"rho": spearman(values[ok], wanted[ok]), "n": int(ok.sum())}
    return out


def _catalog_precision(
    ids: np.ndarray, scores: np.ndarray, labels: list[str], merged, k: int
) -> dict[str, dict]:
    row = {int(t): i for i, t in enumerate(merged.track_ids)}
    out = {}
    for j, scene in enumerate(labels):
        top = [int(ids[i]) for i in np.lexsort((ids, -scores[:, j]))[:k]]
        known = [t for t in top if t in row]
        hits = sum(bool(merged.scenes[row[t], j]) for t in known)
        out[scene] = {
            "p_at_k": hits / len(known) if known else None,
            "labelled": len(known),
            "unlabelled": len(top) - len(known),
        }
    return out


# -- the run -----------------------------------------------------------------------------------


def evaluate_scenes(
    repo: CatalogRepository, settings: Settings, *, k: int = 10, folds: int = 5, seed: int = 0
) -> dict:
    """The evaluation described in the module docstring, as a JSON-ready dict."""
    if k < 1 or folds < 2:
        raise ValueError("k must be at least 1 and folds at least 2")
    registry = scene_registry(settings)
    spec = scene_spec(registry)
    labels = list(spec["labels"])
    selected = select_entry(spec)
    zeroshots = zeroshot_entries(settings)
    all_labels = repo.iter_scene_labels()
    data = labelled_data(repo, labels)
    merged_all = merge_labels(all_labels, labels)
    if len(merged_all) == 0:
        raise ValueError("there are no hand labels yet; label the pool first")
    catalog_ids, catalog_x = repo.load_embeddings(EMBEDDER)
    catalog_ids = catalog_ids.astype(np.int64)

    entries: list[dict] = []
    pool_scored: dict[str, dict] = {}
    for entry, tagger in zeroshots:
        pool_scored[entry["variant"]] = entry_metrics(
            probability_matrix(tagger, data.x) if len(data.x) else np.empty((0, len(labels))),
            data.truth,
            labels,
            k,
        )
        entries.append(
            {
                "variant": entry["variant"],
                "id": entry["id"],
                "method": "zeroshot",
                "centering": float(entry.get("centering", 0.0)),
                "selected": selected is not None and selected["id"] == entry["id"],
                "in_sample": False,
                "catalog": _catalog_precision(
                    catalog_ids, probability_matrix(tagger, catalog_x), labels, merged_all, k
                )
                if len(catalog_ids)
                else None,
                "pool": pool_scored[entry["variant"]],
            }
        )
    fallback_entry, fallback = best_zeroshot(pool_scored, zeroshots)
    head_pool = None
    if len(data.merged) >= 2:
        oof = cross_validated_head_scores(data.x, data.truth, fallback, folds=folds, seed=seed)
        head_pool = entry_metrics(oof, data.truth, labels, k)
    registered = next((e for e in spec["entries"] if e["variant"] == HEAD_VARIANT), None)
    head_catalog = None
    if registered is not None and len(catalog_ids):
        head = load_tagger(settings.models_dir / registered["file"], registered["id"])
        head_catalog = _catalog_precision(
            catalog_ids, probability_matrix(head, catalog_x), labels, merged_all, k
        )
    entries.append(
        {
            "variant": HEAD_VARIANT,
            "id": registered["id"] if registered else None,
            "method": "head",
            "centering": None,
            "selected": selected is not None
            and registered is not None
            and selected["id"] == registered["id"],
            "in_sample": True,
            "fallback": fallback_entry["variant"],
            "catalog": head_catalog,
            "pool": head_pool,
        }
    )
    count: dict[str, dict[str, int]] = {}
    for label in all_labels:
        entry_counts = count.setdefault(label.labeller, {"labelled": 0, "skipped": 0})
        entry_counts[label.status] += 1
    return {
        "schema": 1,
        "kind": "scene-eval",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "k": k,
        "folds": folds,
        "seed": seed,
        "min_positives": MIN_POSITIVES,
        "selected": selected["id"] if selected else None,
        "scenes": labels,
        "labels": {
            "tracks": len(merged_all),
            "with_embedding": len(data.merged),
            "labellers": count,
            "positives": {s: int(merged_all.scenes[:, i].sum()) for i, s in enumerate(labels)},
        },
        "entries": entries,
        "intensity": intensity_correlations(repo, settings, merged_all),
        "agreement": agreement(all_labels, labels),
    }


def write_results(settings: Settings, result: dict) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = settings.data_dir / RESULTS_DIR / f"scenes_{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return path


def latest_results(settings: Settings) -> dict | None:
    """The newest ``scenes_*.json`` result, or None when there is none (or it is unreadable)."""
    folder = settings.data_dir / RESULTS_DIR
    files = sorted(folder.glob("scenes_*.json")) if folder.is_dir() else []
    if not files:
        return None
    try:
        data = json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("kind") == "scene-eval" else None


# -- text --------------------------------------------------------------------------------------


def _num(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _table(rows: list[list[str]]) -> list[str]:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return [
        "  ".join(
            c.ljust(w) if i == 0 else c.rjust(w)
            for i, (c, w) in enumerate(zip(r, widths, strict=True))
        )
        for r in rows
    ]


def format_report(result: dict) -> str:
    """A readable version of :func:`evaluate_scenes`' result."""
    k = result["k"]
    info = result["labels"]
    lines = [
        f"Hand labels: {info['tracks']} tracks ({info['with_embedding']} with a CLAP embedding)",
        "Labellers: "
        + (
            ", ".join(
                f"{name} {c['labelled']} labelled / {c['skipped']} skipped"
                for name, c in info["labellers"].items()
            )
            or "none"
        ),
        f"Selected entry: {result['selected'] or 'none'}",
        "",
        f"Pool (labelled tracks with an embedding; P@{k} / AP; the head is cross-validated, "
        f"{result['folds']} folds, seed {result['seed']}):",
    ]
    entries = result["entries"]
    heads = ["Scene", "Positives"] + [
        e["variant"] + (" *" if e["selected"] else "") for e in entries
    ]
    rows = [heads]
    for scene in result["scenes"]:
        row = [scene, str(info["positives"][scene])]
        for e in entries:
            cell = (e["pool"] or {"per_scene": {}})["per_scene"].get(scene)
            row.append(
                "too few"
                if cell is None or cell["p_at_k"] is None
                else f"{_num(cell['p_at_k'])} / {_num(cell['ap'])}"
            )
        rows.append(row)
    rows.append(
        ["mean P@k", ""] + [_num(e["pool"]["mean_p_at_k"]) if e["pool"] else "n/a" for e in entries]
    )
    lines += _table(rows)
    lines += [
        "",
        f"Catalog top-{k} (precision over the labelled ones; labelled / unlabelled in the list):",
    ]
    rows = [["Scene"] + [e["variant"] for e in entries]]
    for scene in result["scenes"]:
        row = [scene]
        for e in entries:
            cell = (e["catalog"] or {}).get(scene)
            row.append(
                "n/a"
                if cell is None
                else f"{_num(cell['p_at_k'])} ({cell['labelled']}/{cell['unlabelled']})"
            )
        rows.append(row)
    lines += _table(rows)
    lines.append(
        "(* selected; the head's catalog numbers are in-sample: it was trained on these labels)"
    )
    intensity = result["intensity"]
    lines += ["", "Intensity (Spearman rho against low=1, mid=2, high=3):"]
    for name in ("energy", "arousal"):
        lines.append(f"  {name}: rho {_num(intensity[name]['rho'])} (n={intensity[name]['n']})")
    agree = result["agreement"]
    lines.append("")
    if agree is None:
        lines.append("Agreement: needs two labellers with shared tracks")
    else:
        a, b = agree["labellers"]
        lines.append(f"Agreement between {a} and {b} on {agree['n_tracks']} shared tracks:")
        for scene, cell in agree["per_scene"].items():
            lines.append(f"  {scene}: kappa {_num(cell['kappa'])}")
        lines.append(f"  mean kappa {_num(agree['mean_kappa'])}")
        inten = agree["intensity"]
        lines.append(f"  intensity exact match {_num(inten['match_rate'])} (n={inten['n']})")
    return "\n".join(lines)
