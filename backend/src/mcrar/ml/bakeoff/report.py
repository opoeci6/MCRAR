"""Render ``docs/embedder_bakeoff.md`` from the latest results files, with a rule-based verdict."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from mcrar.ml.bakeoff.common import BakeoffError, latest_result, models_info, read_json

RATINGS_COVERAGE_MIN = 0.8

RULE_LINES = (
    "The default model is the permissive model (commercial use allowed) with the best score. "
    "The score is the SDD text-to-audio R@10.",
    "A non-commercial model (MuQ-MuLan) is flagged as best overall but non-commercial only if "
    "it scores higher than the best permissive model and the 95% interval of the paired "
    "bootstrap difference (1,000 resamples) excludes 0. Otherwise it is not recommended.",
    "If the user's blind ratings cover at least 80% of every model's top-k, they override the "
    "SDD verdict: the score becomes the mean rating of the top-k, compared with a paired "
    "bootstrap over queries. The SDD verdict is still shown.",
)


# -- the recommendation ----------------------------------------------------------------------------


def _pair_diff(
    pairwise: Sequence[Mapping[str, Any]], metric: str, a: str, b: str
) -> tuple[float, float, float] | None:
    """``(diff, lo, hi)`` of ``a - b`` from a pairwise table, whichever way round it is stored."""
    for row in pairwise:
        if row.get("metric") != metric:
            continue
        if (row["a"], row["b"]) == (a, b):
            return row["diff"], row["ci"][0], row["ci"][1]
        if (row["a"], row["b"]) == (b, a):
            return -row["diff"], -row["ci"][1], -row["ci"][0]
    return None


def _verdict(
    scores: Mapping[str, float],
    pairwise: Sequence[Mapping[str, Any]],
    metric: str,
    commercial: Mapping[str, bool],
) -> dict[str, Any]:
    permissive = [m for m in scores if commercial.get(m, False)]
    if not permissive:
        return {"default": None, "flagged": None}
    best = max(permissive, key=lambda m: scores[m])  # the first of equals wins
    beating = [m for m in scores if not commercial.get(m, False) and scores[m] > scores[best]]
    flagged = None
    if beating:
        top = max(beating, key=lambda m: scores[m])
        diff = _pair_diff(pairwise, metric, top, best)
        if diff is not None and diff[1] > 0.0:
            flagged = {"model": top, "diff": diff[0], "ci": [diff[1], diff[2]]}
    return {"default": best, "flagged": flagged}


def recommend(
    commercial: Mapping[str, bool],
    sdd: Mapping[str, Any] | None,
    ratings: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Apply the documented rule (see ``RULE_LINES``).

    ``commercial`` maps model id to whether its licence allows commercial use. Returns the
    evidence used (``"ratings"``, ``"sdd"`` or None), the default model, the flagged
    non-commercial model if any, the SDD verdict on its own, and notes for the reader.
    """
    notes: list[str] = []
    sdd_verdict = None
    if sdd:
        scores = {m: r["t2a"]["R@10"] for m, r in sdd["results"].items()}
        sdd_verdict = _verdict(scores, sdd.get("pairwise", []), "R@10", commercial)
    ratings_verdict = None
    if ratings:
        coverage = ratings["coverage"]["min_model_fraction"]
        if coverage >= RATINGS_COVERAGE_MIN:
            scores = {
                m: r["mean_rating"]
                for m, r in ratings["results"].items()
                if r["mean_rating"] is not None
            }
            ratings_verdict = _verdict(
                scores, ratings.get("pairwise", []), "mean_rating", commercial
            )
        else:
            notes.append(
                f"The ratings cover only {coverage:.0%} of the least-covered model's top-k "
                f"(need {RATINGS_COVERAGE_MIN:.0%}), so they do not override the SDD verdict."
            )
    if ratings_verdict is not None:
        evidence, verdict = "ratings", ratings_verdict
        if sdd_verdict is not None and sdd_verdict["default"] != verdict["default"]:
            notes.append(
                f"The ratings overrode the SDD verdict (SDD picked {sdd_verdict['default']})."
            )
    elif sdd_verdict is not None:
        evidence, verdict = "sdd", sdd_verdict
    else:
        return {
            "evidence": None,
            "default": None,
            "flagged": None,
            "sdd_default": None,
            "notes": [*notes, "No SDD or ratings results yet: nothing to recommend."],
        }
    if verdict["default"] is None:
        notes.append("No permissive (commercial-use) model was evaluated, so no default is set.")
    return {
        "evidence": evidence,
        "default": verdict["default"],
        "flagged": verdict["flagged"],
        "sdd_default": None if sdd_verdict is None else sdd_verdict["default"],
        "notes": notes,
    }


# -- rendering -----------------------------------------------------------------------------------


def _table(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return [*lines, ""]


def _f(value: Any, spec: str = ".3f") -> str:
    return "n/a" if value is None else f"{value:{spec}}"


def _ci(ci: Sequence[float] | None, spec: str = ".3f") -> str:
    return "n/a" if not ci else f"[{ci[0]:{spec}}, {ci[1]:{spec}}]"


def _license(model_id: str, info: Mapping[str, Mapping[str, Any]]) -> str:
    entry = info.get(model_id)
    if not entry:
        return "unknown"
    ok = "commercial use OK" if entry["commercial_ok"] else "NON-COMMERCIAL"
    return f"{entry['license']} ({ok})"


def _pairwise_rows(pairwise: Sequence[Mapping[str, Any]], metrics_: Sequence[str]) -> list[list]:
    return [
        [
            f"{p['a']} vs {p['b']}",
            p["metric"],
            f"{p['diff']:+.3f}",
            _ci(p["ci"]),
            "yes" if p["significant"] else "no",
        ]
        for p in pairwise
        if p["metric"] in metrics_
    ]


def _section_sdd(sdd: Mapping[str, Any] | None, info: Mapping, source: str | None) -> list[str]:
    lines = ["## Song Describer (text to audio retrieval)", ""]
    if not sdd:
        return [*lines, "Not run yet: `mcrar bakeoff sdd-embed` then `mcrar bakeoff sdd-eval`.", ""]
    subset = "validated captions only" if sdd["subset"] == "validated" else "all captions"
    lines += [
        f"Source: `{source}`. {sdd['n_captions']} captions ({subset}) over a gallery of "
        f"{sdd['n_tracks']} tracks. Intervals are 95% bootstrap intervals over captions "
        f"({sdd['n_resamples']} resamples, seed {sdd['seed']}).",
        "",
    ]
    rows = []
    for model, r in sdd["results"].items():
        t2a, a2t = r["t2a"], r["a2t"]
        rows.append(
            [
                model,
                _f(t2a["R@1"]),
                _f(t2a["R@5"]),
                f"{_f(t2a['R@10'])} {_ci(t2a['R@10_ci'])}",
                _f(t2a["median_rank"], ".1f"),
                f"{_f(t2a['mrr'])} {_ci(t2a['mrr_ci'])}",
                _f(a2t["R@10"]),
            ]
        )
    lines += _table(
        [
            "Model",
            "R@1",
            "R@5",
            "R@10 (95% CI)",
            "Median rank",
            "MRR (95% CI)",
            "Audio to text R@10",
        ],
        rows,
    )
    pair_rows = _pairwise_rows(sdd.get("pairwise", []), ("R@10", "MRR"))
    if pair_rows:
        lines += [
            "Paired bootstrap differences (first model minus second). A difference whose interval "
            "excludes 0 is unlikely to be noise.",
            "",
            *_table(["Pair", "Metric", "Difference", "95% CI", "Excludes 0"], pair_rows),
        ]
    return lines


def _section_tags(tags: Mapping[str, Any] | None, info: Mapping, source: str | None) -> list[str]:
    lines = ["## Genre tags on the Jamendo catalog (weak labels)", ""]
    if not tags:
        return [*lines, "Not run yet: `mcrar bakeoff tag-eval`.", ""]
    names = ", ".join(f"{t['tag']} ({t['n_relevant']})" for t in tags["tags"])
    mean_prev = sum(t["prevalence"] for t in tags["tags"]) / max(len(tags["tags"]), 1)
    lines += [
        f"Source: `{source}`. {tags['note']}",
        "",
        f"{len(tags['tags'])} tags with at least {tags['min_tracks']} tracks, over "
        f"{tags['n_tracks']} tracks that every model embedded. The query for each tag is "
        f'"<genre> music". A random ranking would score about {mean_prev:.3f} AP '
        "(the mean tag prevalence).",
        "",
        f"Tags (relevant tracks): {names}.",
        "",
    ]
    rows = [[m, _f(r["macro_AP"]), _f(r["macro_P@10"])] for m, r in tags["results"].items()]
    return [*lines, *_table(["Model", "Macro AP", "Macro P@10"], rows)]


def _section_ratings(
    ratings: Mapping[str, Any] | None, info: Mapping, source: str | None
) -> list[str]:
    lines = ["## Blind ratings (game-scene queries)", ""]
    if not ratings:
        return [
            *lines,
            "Not rated yet: `mcrar bakeoff candidates`, rate, then `score-ratings`.",
            "",
        ]
    cov = ratings["coverage"]
    k = ratings["k"]
    lines += [
        f"Source: `{source}`. {ratings['n_queries']} queries, top-{k} per model. Ratings: 0 "
        "(wrong), 1 (acceptable), 2 (good). "
        f"{cov['pool_rated']} of {cov['pool_items']} pooled items rated "
        f"({cov['pool_fraction']:.0%}); unrated items are left out. Coverage of the "
        f"least-covered model: {cov['min_model_fraction']:.0%}.",
        "",
    ]
    rows = [
        [
            m,
            _f(r["mean_rating"], ".2f"),
            _f(r["ndcg"]),
            _f(r["share_relevant"], ".0%") if r["share_relevant"] is not None else "n/a",
            f"{r['coverage']:.0%}",
            r["n_queries_scored"],
        ]
        for m, r in ratings["results"].items()
    ]
    lines += _table(
        ["Model", f"Mean rating@{k}", f"nDCG@{k}", "Rated 1 or 2", "Coverage", "Queries"], rows
    )
    pair_rows = _pairwise_rows(ratings.get("pairwise", []), ("mean_rating",))
    if pair_rows:
        lines += [
            "Paired bootstrap over queries (first model minus second).",
            "",
            *_table(["Pair", "Metric", "Difference", "95% CI", "Excludes 0"], pair_rows),
        ]
    return lines


def _section_benchmark(bench: Mapping[str, Any] | None, source: str | None) -> list[str]:
    lines = ["## Speed and memory", ""]
    if not bench:
        return [*lines, "Not run yet: `mcrar models benchmark --benchmark-json`.", ""]
    rows = [
        [
            r["model_id"],
            r["device"],
            r["dtype"],
            _f(r["load_s"], ".1f"),
            _f(r["peak_vram_mb"], ".0f"),
            _f(r["resident_vram_mb"], ".0f"),
            _f(r["audio_s_per_s"], ".1f"),
            _f(r["texts_per_s"], ".1f"),
            r["dim"],
        ]
        for r in bench["rows"]
    ]
    return [
        *lines,
        f"Source: `{source}`. Synthetic {bench['seconds']:g} s tracks, 3 windows each.",
        "",
        *_table(
            [
                "Model",
                "Device",
                "Dtype",
                "Load s",
                "Peak VRAM MB",
                "Weights VRAM MB",
                "Audio s/s",
                "Texts/s",
                "Dim",
            ],
            rows,
        ),
    ]


def _section_recommendation(rec: Mapping[str, Any], info: Mapping) -> list[str]:
    lines = ["## Recommendation", "", "Rule (applied mechanically to the results below):", ""]
    lines += [f"{n}. {text}" for n, text in enumerate(RULE_LINES, 1)] + [""]
    if rec["evidence"] is None:
        return [*lines, *rec["notes"], ""]
    basis = "the user's ratings" if rec["evidence"] == "ratings" else "the SDD R@10"
    if rec["default"] is None:
        lines.append(f"**No default**, based on {basis}.")
    else:
        lines.append(
            f"**Default model: `{rec['default']}`** ({_license(rec['default'], info)}), "
            f"based on {basis}."
        )
    flagged = rec["flagged"]
    if flagged:
        lines += [
            "",
            f"**`{flagged['model']}` is best overall but non-commercial** "
            f"({_license(flagged['model'], info)}): "
            f"it beats `{rec['default']}` by {flagged['diff']:+.3f} "
            f"(95% CI {_ci(flagged['ci'])}). Use it only for non-commercial work with "
            "`MCRAR_COMMERCIAL_MODE=false`.",
        ]
    else:
        lines += [
            "",
            "No non-commercial model beats the default with a confidence interval that excludes 0.",
        ]
    if rec["notes"]:
        lines += ["", *[f"- {n}" for n in rec["notes"]]]
    return [*lines, ""]


def _section_models(info: Mapping, model_ids: Sequence[str]) -> list[str]:
    rows = [[m, _license(m, info)] for m in model_ids]
    return ["## Models and licences", "", *_table(["Model", "Licence of the weights"], rows)]


def render_report(
    *,
    sdd: Mapping[str, Any] | None = None,
    tags: Mapping[str, Any] | None = None,
    ratings: Mapping[str, Any] | None = None,
    benchmark: Mapping[str, Any] | None = None,
    sources: Mapping[str, str] | None = None,
) -> str:
    """The Markdown report. ``sources`` maps ``sdd``/``tags``/``ratings``/``benchmark`` to the
    file names the data came from."""
    src = dict(sources or {})
    model_ids: list[str] = []
    for part in (sdd, tags, ratings):
        if part:
            model_ids += [m for m in part["results"] if m not in model_ids]
    if benchmark:
        model_ids += [r["model_id"] for r in benchmark["rows"] if r["model_id"] not in model_ids]
    info = models_info(model_ids)
    for part in (benchmark, ratings, tags, sdd):  # the results files' own facts win
        if part and part.get("models_info"):
            info.update(part["models_info"])
    commercial = {m: bool(v["commercial_ok"]) for m, v in info.items()}
    rec = recommend(commercial, sdd, ratings)

    out = [
        "# Embedder bake-off",
        "",
        "Generated by `mcrar bakeoff report`. Do not edit by hand: re-run the command.",
        "",
        *_section_recommendation(rec, info),
        *_section_models(info, model_ids),
        *_section_sdd(sdd, info, src.get("sdd")),
        *_section_tags(tags, info, src.get("tags")),
        *_section_ratings(ratings, info, src.get("ratings")),
        *_section_benchmark(benchmark, src.get("benchmark")),
    ]
    return "\n".join(out).rstrip() + "\n"


def build_report(results_dir: Path) -> tuple[str, dict[str, str]]:
    """Read the newest results of each kind in ``results_dir`` and render the report.

    Returns the Markdown and the ``{kind: file name}`` actually used.
    """
    kinds = {"sdd": "sdd", "tags": "tags", "ratings": "ratings", "benchmark": "benchmark"}
    data: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for kind, prefix in kinds.items():
        path = latest_result(results_dir, prefix)
        if path is not None:
            data[kind] = read_json(path)
            sources[kind] = path.name
    if not data:
        raise BakeoffError(f"no results found in {results_dir}; run sdd-eval, tag-eval, ... first")
    return render_report(**data, sources=sources), sources
