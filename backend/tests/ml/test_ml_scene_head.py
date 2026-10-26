"""The hybrid scene head (M9): zero-shot columns written as a linear head, logistic regression for
the scenes with enough labels, cross-validated metrics for every entry, registry rules for the
hand-label metrics and the selection (ties go to the simpler entry)."""

from __future__ import annotations

import json

import numpy as np
import pytest
from scene_support import (
    SIGNAL_SCENES,
    build_registry,
    clap,
    label_tracks,
    signal_catalog,
)
from tagging_support import register
from typer.testing import CliRunner

from mcrar.catalog import open_catalog
from mcrar.cli import app
from mcrar.config import get_settings
from mcrar.ml.tagging.registry import read_registry, select_entry, validate_registry
from mcrar.ml.tagging.runtime import load_tagger
from mcrar.ml.tagging.scene_head import (
    HEAD_VARIANT,
    best_zeroshot,
    cross_validated_head_scores,
    entry_metrics,
    fit_hybrid,
    linear_equivalent,
    probability_matrix,
    train_scene_head,
    zeroshot_entries,
)
from mcrar.recommend.vocab import DEFAULT_SCENES

runner = CliRunner()


def truth_matrix(signal: np.ndarray) -> np.ndarray:
    """All 14 scenes: the first three from the catalog's signal, the rest never present."""
    out = np.zeros((len(signal), len(DEFAULT_SCENES)), dtype=bool)
    out[:, : signal.shape[1]] = signal
    return out


@pytest.fixture
def catalog():  # noqa: ANN201
    settings = get_settings()
    with open_catalog(settings) as repo:
        ids, vectors, signal = signal_catalog(repo, 120)
        entries = build_registry(settings, repo)
        yield settings, repo, ids, vectors, signal, entries


# -- the zero-shot columns as a linear head ----------------------------------------------------


def test_a_zeroshot_tagger_is_a_linear_head(catalog) -> None:  # noqa: ANN001
    settings, _, _, vectors, *_ = catalog
    for _, tagger in zeroshot_entries(settings):
        weight, bias = linear_equivalent(tagger)
        assert weight.shape == (512, 14) and bias.shape == (14,)
        logits = vectors.astype(np.float64) @ weight + bias
        np.testing.assert_allclose(
            1 / (1 + np.exp(-logits)), probability_matrix(tagger, vectors), atol=1e-5
        )


def test_linear_equivalent_refuses_a_head(catalog) -> None:  # noqa: ANN001
    settings, repo, ids, vectors, signal, _ = catalog
    _, fallback = zeroshot_entries(settings)[0]
    head, _ = fit_hybrid(vectors, truth_matrix(signal), fallback)
    with pytest.raises(ValueError, match="zero-shot"):
        linear_equivalent(head)


def test_the_hybrid_reproduces_the_zeroshot_probabilities_where_it_trains_nothing(
    catalog,  # noqa: ANN001
) -> None:
    settings, _, _, vectors, signal, _ = catalog
    for _, fallback in zeroshot_entries(settings):
        head, trained = fit_hybrid(vectors, truth_matrix(signal), fallback)
        assert trained == list(SIGNAL_SCENES)  # only these have 5 positives and 5 negatives
        assert (head.label_set, head.kind, head.method) == ("scene", "multi_label", "head")
        assert head.labels == list(DEFAULT_SCENES)
        mine, theirs = probability_matrix(head, vectors), probability_matrix(fallback, vectors)
        np.testing.assert_allclose(mine[:, 3:], theirs[:, 3:], atol=1e-5)  # exact up to float32
        assert not np.allclose(mine[:, :3], theirs[:, :3], atol=1e-2)  # trained columns differ
        # and the trained ones learned the signal
        for j in range(3):
            assert mine[signal[:, j], j].mean() > mine[~signal[:, j], j].mean() + 0.5
        # with nothing to train the whole head is the zero-shot tagger
        untrained, none = fit_hybrid(vectors, np.zeros_like(truth_matrix(signal)), fallback)
        assert none == []
        np.testing.assert_allclose(probability_matrix(untrained, vectors), theirs, atol=1e-5)


def test_scenes_need_five_positives_and_five_negatives_to_train(catalog) -> None:  # noqa: ANN001
    settings, _, _, vectors, signal, _ = catalog
    _, fallback = zeroshot_entries(settings)[0]
    y = truth_matrix(signal)
    y[:, 0] = False
    y[:4, 0] = True  # 4 positives: too few
    y[:, 1] = True
    y[:4, 1] = False  # 4 negatives: too few
    y[:5, 2] = True
    y[5:, 2] = False  # exactly 5 positives
    _, trained = fit_hybrid(vectors, y, fallback)
    assert trained == [SIGNAL_SCENES[2]]


# -- scoring -----------------------------------------------------------------------------------


def test_entry_metrics_scores_scenes_with_enough_positives_only() -> None:
    labels = ["a", "b", "c"]
    truth = np.zeros((10, 3), dtype=bool)
    truth[:5, 0] = True  # 5 positives
    truth[:2, 1] = True  # only 2
    truth[5:, 2] = True  # 5 positives
    scores = np.zeros((10, 3))
    scores[:, 0] = np.arange(10, 0, -1)  # ranks the positives first: P@4 = 1
    scores[:, 1] = np.arange(10, 0, -1)
    scores[:, 2] = np.arange(10, 0, -1)  # ranks the negatives first: P@4 = 0
    result = entry_metrics(scores, truth, labels, 4)
    a, b, c = (result["per_scene"][s] for s in labels)
    assert (a["positives"], a["p_at_k"], a["ap"]) == (5, 1.0, 1.0)
    assert (b["positives"], b["p_at_k"], b["ap"]) == (2, None, None)  # too few
    assert c["p_at_k"] == 0.0 and c["ap"] == pytest.approx(
        (1 / 6 + 2 / 7 + 3 / 8 + 4 / 9 + 5 / 10) / 5
    )
    assert result["mean_p_at_k"] == pytest.approx(0.5) and result["scenes_scored"] == 2
    nothing = entry_metrics(scores, np.zeros_like(truth), labels, 4)
    assert nothing["mean_p_at_k"] is None


def test_out_of_fold_scores_are_deterministic_and_beat_zero_shot(catalog) -> None:  # noqa: ANN001
    settings, _, _, vectors, signal, _ = catalog
    zeroshots = zeroshot_entries(settings)
    y = truth_matrix(signal)
    _, fallback = zeroshots[0]
    first = cross_validated_head_scores(vectors, y, fallback, folds=4, seed=3)
    again = cross_validated_head_scores(vectors, y, fallback, folds=4, seed=3)
    np.testing.assert_array_equal(first, again)
    assert not np.array_equal(
        first, cross_validated_head_scores(vectors, y, fallback, folds=4, seed=4)
    )
    labels = list(DEFAULT_SCENES)
    head = entry_metrics(first, y, labels, 10)
    zero = {
        e["variant"]: entry_metrics(probability_matrix(t, vectors), y, labels, 10)
        for e, t in zeroshots
    }
    assert head["scenes_scored"] == 3
    # the text prompts know nothing about these synthetic coordinates; the head learned them
    assert head["mean_p_at_k"] > 0.9
    assert all(head["mean_p_at_k"] > z["mean_p_at_k"] + 0.2 for z in zero.values())
    assert best_zeroshot(zero, zeroshots)[0]["variant"] in zero
    with pytest.raises(ValueError, match="at least 2"):
        cross_validated_head_scores(vectors[:1], y[:1], fallback)


def test_best_zeroshot_breaks_ties_towards_the_lower_centering(catalog) -> None:  # noqa: ANN001
    settings, *_ = catalog
    entries = zeroshot_entries(settings)  # plain (0.0) first
    same = {e["variant"]: {"mean_p_at_k": 0.4} for e, _ in entries}
    assert best_zeroshot(same, entries)[0]["centering"] == 0.0
    better = {**same, "zeroshot-catalog-centered": {"mean_p_at_k": 0.41}}
    assert best_zeroshot(better, entries)[0]["variant"] == "zeroshot-catalog-centered"
    unscored = {e["variant"]: {"mean_p_at_k": None} for e, _ in entries}
    assert best_zeroshot(unscored, entries)[0]["centering"] == 0.0


# -- the registry ------------------------------------------------------------------------------


def hand_metrics(value: float) -> dict:
    return {"split": "hand-labels-cv", "primary": "mean_p_at_10", "mean_p_at_10": value}


def test_the_registry_accepts_hand_label_metrics_for_scene_only(catalog) -> None:  # noqa: ANN001
    settings, *_ = catalog
    registry = read_registry(settings)
    entries = registry["label_sets"]["scene"]["entries"]
    entries[0]["metrics"] = hand_metrics(0.4)
    entries[1]["metrics"] = {**hand_metrics(0.5), "per_scene": {}, "n_tracks": 3}
    validate_registry(registry, settings.models_dir)
    for bad, message in (
        (
            {"split": "hand-labels-cv", "primary": "macro_pr_auc", "macro_pr_auc": 0.5},
            "mean_p_at_10",
        ),
        (hand_metrics(float("nan")), "finite"),
        ({"split": "hand-labels-cv", "primary": "mean_p_at_10"}, "finite"),
        ({"split": "validation"}, "test-split metrics"),
    ):
        entries[0]["metrics"] = bad
        with pytest.raises(ValueError, match=message):
            validate_registry(registry, settings.models_dir)
    # the test-split rules of the scene set did not change
    entries[0]["metrics"] = {"split": "test", "primary": "macro_pr_auc", "macro_pr_auc": 0.3}
    validate_registry(registry, settings.models_dir)


def test_other_label_sets_cannot_use_the_hand_label_split() -> None:
    settings = get_settings()
    registry = register(settings)
    registry["label_sets"]["genre"]["entries"][0]["metrics"] = hand_metrics(0.5)
    with pytest.raises(ValueError, match="selection requires test-split metrics$"):
        validate_registry(registry, settings.models_dir)


def entry(identity: str, method: str, centering: float | None, value: float | None) -> dict:
    return {
        "id": identity,
        "method": method,
        "created_at": "2026-01-01",
        **({"centering": centering} if centering is not None else {}),
        "metrics": None if value is None else hand_metrics(value),
    }


def test_selection_prefers_the_best_hand_label_score_and_breaks_ties_to_the_simpler() -> None:
    def pick(*entries: dict) -> str:
        return select_entry({"kind": "multi_label", "entries": list(entries)})["id"]

    plain = entry("plain", "zeroshot", 0.0, 0.40)
    centered = entry("centered", "zeroshot", 0.75, 0.40)
    head = entry("head", "head", None, 0.40)
    assert pick(head, centered, plain) == "plain"  # all tied: zero-shot, the lower centering
    assert pick(head, centered) == "centered"  # a zero-shot entry before the head
    assert pick(head, {**centered, "metrics": hand_metrics(0.41)}, plain) == "centered"
    assert pick({**head, "metrics": hand_metrics(0.5)}, centered, plain) == "head"  # better wins
    assert pick(entry("u", "zeroshot", 0.0, None), head) == "head"  # evaluated beats unevaluated
    assert pick(entry("b", "zeroshot", 0.0, 0.3), entry("a", "zeroshot", 0.0, 0.3)) == "b"  # id


# -- training ----------------------------------------------------------------------------------


def test_training_records_every_entry_and_selects_the_head_when_it_wins(catalog) -> None:  # noqa: ANN001
    settings, repo, ids, _, signal, entries = catalog
    plain, centered = entries
    label_tracks(repo, ids, signal)
    first = train_scene_head(settings, repo, folds=4, seed=1)

    assert first["head_won"] is True and first["n_tracks"] == 120
    assert first["trained"] == list(SIGNAL_SCENES) and first["fallback"] in {
        "zeroshot-catalog",
        "zeroshot-catalog-centered",
    }
    assert first["previous"] == centered["id"] and first["selected"] == first["head"]["id"]
    assert first["scores"][HEAD_VARIANT] > 0.9
    registry = read_registry(settings)  # validates every entry and artifact
    spec = registry["label_sets"]["scene"]
    assert registry["selected"]["scene"] == first["head"]["id"]
    by_variant = {e["variant"]: e for e in spec["entries"]}
    assert set(by_variant) == {"zeroshot-catalog", "zeroshot-catalog-centered", HEAD_VARIANT}
    assert by_variant["zeroshot-catalog"]["id"] == plain["id"]  # the zero-shot files are unchanged
    assert by_variant["zeroshot-catalog-centered"]["id"] == centered["id"]
    for e in by_variant.values():
        m = e["metrics"]
        assert (m["split"], m["primary"], m["n_tracks"], m["folds"], m["seed"]) == (
            "hand-labels-cv",
            "mean_p_at_10",
            120,
            4,
            1,
        )
        assert set(m["per_scene"]) == set(DEFAULT_SCENES)
        assert m["per_scene"]["combat"]["positives"] == int(signal[:, 0].sum())
        assert m["per_scene"]["horror"] == {"positives": 0, "p_at_10": None, "ap": None}
    head = by_variant[HEAD_VARIANT]
    assert head["id"].startswith("scene-logreg-hybrid@")
    assert (
        head["file"] == f"heads/{head['id']}.npz" and (settings.models_dir / head["file"]).is_file()
    )
    assert (head["method"], head["commercial_ok"], head["seed"]) == ("head", True, 1)
    assert head["trained_labels"] == list(SIGNAL_SCENES) and "combat" not in head["zeroshot_labels"]
    assert head["fallback_entry"] in {plain["id"], centered["id"]}
    assert "owner" in head["train_data"] and "120" in head["train_data"]
    assert "NC" not in head["data_license"].split() and "hand labels" in head["data_license"]
    tagger = load_tagger(settings.models_dir / head["file"], head["id"])
    assert (tagger.method, tagger.labels) == ("head", list(DEFAULT_SCENES))

    again = train_scene_head(settings, repo, folds=4, seed=1)  # deterministic: same artifact
    assert again["head"]["id"] == first["head"]["id"] and again["previous"] == first["selected"]
    assert len(read_registry(settings)["label_sets"]["scene"]["entries"]) == 3


def test_the_zeroshot_entry_stays_selected_when_the_head_does_not_beat_it(
    catalog,  # noqa: ANN001
) -> None:
    settings, repo, ids, vectors, _, (plain, centered) = catalog
    # labels that are the centered tagger's own top half: zero-shot is perfect, nothing can beat it
    tagger = zeroshot_entries(settings)[1][1]
    probs = probability_matrix(tagger, vectors)
    truth = probs > np.median(probs, axis=0)
    for track, row in zip(ids, truth, strict=True):
        repo.set_scene_label(
            track,
            "owner",
            [s for s, on in zip(DEFAULT_SCENES, row, strict=True) if on],
            None,
            "labelled",
        )
    result = train_scene_head(settings, repo, folds=4)
    assert result["scores"]["zeroshot-catalog-centered"] == 1.0
    assert result["scores"]["zeroshot-catalog"] == 1.0  # tied: the lower centering is simpler
    assert result["head_won"] is False
    assert result["selected"] == plain["id"] and result["previous"] == centered["id"]
    registry = read_registry(settings)
    assert registry["selected"]["scene"] == plain["id"]
    variants = {e["variant"] for e in registry["label_sets"]["scene"]["entries"]}
    assert HEAD_VARIANT in variants  # still recorded


def test_training_needs_labels_with_enough_positives(catalog) -> None:  # noqa: ANN001
    settings, repo, ids, _, signal, _ = catalog
    with pytest.raises(ValueError, match="no hand labels"):
        train_scene_head(settings, repo)
    label_tracks(repo, ids[:4], signal[:4])
    with pytest.raises(ValueError, match="5 labelled positives"):
        train_scene_head(settings, repo)
    with pytest.raises(ValueError, match="mcrar scenes build"):
        train_scene_head(
            settings.model_copy(update={"models_dir": settings.models_dir / "x"}), repo
        )
    assert HEAD_VARIANT not in json.dumps(read_registry(settings))  # nothing was written


def test_the_train_command_reports_the_result_and_the_retag_reminder(
    catalog,
    monkeypatch: pytest.MonkeyPatch,  # noqa: ANN001
) -> None:
    settings, repo, ids, _, signal, entries = catalog
    label_tracks(repo, ids, signal)
    repo.close()
    result = runner.invoke(app, ["scenes", "train", "--folds", "3"])
    assert result.exit_code == 0, result.output
    assert "Trained on 120 labelled tracks" in result.output
    assert "zeroshot-catalog-centered: mean P@10" in result.output
    assert f"Trained scenes: {', '.join(SIGNAL_SCENES)}" in result.output
    assert "The head won and is selected: scene-logreg-hybrid@" in result.output
    assert "mcrar tag --label-sets scene" in result.output  # the selection changed
    again = runner.invoke(app, ["scenes", "train", "--folds", "3"])
    assert again.exit_code == 0 and "mcrar tag --label-sets scene" not in again.output
    assert clap().model_id == "clap@195c3a3" and entries
