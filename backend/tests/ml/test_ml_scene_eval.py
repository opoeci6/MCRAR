"""Evaluating the scene entries against hand labels (M9): merged truth, catalog and pool
precision, Spearman with ties, Cohen's kappa, the written result and the model card section."""

from __future__ import annotations

import json

import numpy as np
import pytest
from scene_support import (
    build_registry,
    label_tracks,
    signal_catalog,
)
from typer.testing import CliRunner

from mcrar.catalog import SceneLabel, open_catalog
from mcrar.cli import app
from mcrar.config import get_settings
from mcrar.ml.tagging.registry import read_registry
from mcrar.ml.tagging.report import scene_section, write_model_card
from mcrar.ml.tagging.scene_eval import (
    _catalog_precision,
    agreement,
    cohens_kappa,
    evaluate_scenes,
    format_report,
    latest_results,
    spearman,
    write_results,
)
from mcrar.ml.tagging.scene_labels import merge_labels
from mcrar.recommend.vocab import DEFAULT_SCENES

runner = CliRunner()
SCENES = ["combat", "boss", "menu"]


def label(
    track: int,
    who: str,
    scenes: list[str],
    intensity: str | None = None,
    status: str = "labelled",
) -> SceneLabel:
    return SceneLabel(track, who, tuple(scenes), intensity, status, "t", "t")


# -- merged truth ------------------------------------------------------------------------------


def test_a_scene_is_present_when_at_least_half_of_the_labellers_marked_it() -> None:
    labels = [
        label(1, "a", ["combat"], "low"),  # one labeller: his word
        label(2, "a", ["combat", "boss"], "high"),  # two labellers, a tie on "combat": present
        label(2, "b", ["boss"], "mid"),
        label(3, "a", ["boss"], "low"),  # three labellers: 1 of 3 is not enough, 2 of 3 is
        label(3, "b", ["menu", "boss"], None),
        label(3, "c", ["menu"], "low"),
        label(4, "a", ["combat"], "high", "skipped"),  # skipped: no label at all
        label(5, "a", [], "mid"),  # "no scene fits"
    ]
    merged = merge_labels(labels, SCENES)
    assert merged.track_ids.tolist() == [1, 2, 3, 5]
    assert merged.scenes.tolist() == [
        [True, False, False],
        [True, True, False],  # a tie of 1 vs 1 on combat counts as present
        [False, True, True],  # 2 of 3 on boss and on menu
        [False, False, False],
    ]
    assert merged.labellers.tolist() == [1, 2, 3, 1]
    np.testing.assert_allclose(
        merged.intensity, [1.0, 2.5, 1.0, 2.0]
    )  # means of low=1/mid=2/high=3


def test_a_track_without_a_given_intensity_has_none() -> None:
    merged = merge_labels([label(1, "a", ["boss"], None)], SCENES)
    assert np.isnan(merged.intensity[0])
    assert len(merge_labels([], SCENES)) == 0


# -- the statistics ----------------------------------------------------------------------------


def test_spearman_handles_ties_like_scipy() -> None:
    from scipy.stats import spearmanr

    a = np.array([1, 2, 3, 4, 5, 6], dtype=float)
    b = np.array([1, 2, 2, 3, 3, 3], dtype=float)  # many ties
    expected = float(spearmanr(a, b).statistic)
    assert spearman(a, b) == pytest.approx(expected)
    assert spearman(a, a) == pytest.approx(1.0) and spearman(a, -a) == pytest.approx(-1.0)
    # by hand: average ranks of b are 1, 2.5, 2.5, 5, 5, 5; Pearson of those with 1..6
    ranks = np.array([1, 2.5, 2.5, 5, 5, 5])
    assert spearman(a, b) == pytest.approx(np.corrcoef(a, ranks)[0, 1])
    assert spearman(np.ones(5), np.arange(5)) is None  # constant: undefined
    assert spearman(np.array([1.0, 2.0]), np.array([2.0, 1.0])) is None  # too few pairs
    with pytest.raises(ValueError, match="same length"):
        spearman(a, b[:3])


def test_cohens_kappa_matches_a_known_value() -> None:
    # the textbook example: 20 both yes, 5 yes/no, 10 no/yes, 15 both no: kappa = 0.4
    a = np.array([True] * 25 + [False] * 25)
    b = np.array([True] * 20 + [False] * 5 + [True] * 10 + [False] * 15)
    assert cohens_kappa(a, b) == pytest.approx(0.4)
    assert cohens_kappa(a, a) == pytest.approx(1.0)
    assert cohens_kappa(a, ~a) == pytest.approx(-1.0)
    assert cohens_kappa(np.ones(4, bool), np.ones(4, bool)) is None  # chance agreement is 1
    assert cohens_kappa(np.array([], bool), np.array([], bool)) is None


def test_agreement_uses_the_two_busiest_labellers_on_their_shared_tracks() -> None:
    both = [
        # track, a's scenes, b's scenes, a's intensity, b's intensity
        (1, ["combat"], ["combat"], "high", "high"),
        (2, ["combat"], [], "mid", "low"),
        (3, [], ["combat"], "low", None),
        (4, [], [], None, "low"),
    ]
    labels = []
    for track, sa, sb, ia, ib in both:
        labels += [label(track, "alice", sa, ia), label(track, "bob", sb, ib)]
    labels += [label(10, "alice", ["boss"]), label(11, "alice", []), label(12, "cleo", ["boss"])]
    labels.append(label(5, "bob", ["menu"], status="skipped"))  # skipped: not a label
    result = agreement(labels, SCENES)
    assert result["labellers"] == ["alice", "bob"]  # alice 6 labels, bob 4, cleo 1
    assert result["n_tracks"] == 4
    combat = result["per_scene"]["combat"]  # a: T T F F, b: T F T F -> po 0.5, pe 0.5
    assert combat == {"kappa": pytest.approx(0.0), "n": 4}
    assert result["per_scene"]["boss"]["kappa"] is None  # nobody says boss on the shared tracks
    assert result["mean_kappa"] == pytest.approx(0.0)
    assert result["intensity"] == {"match_rate": 0.5, "n": 2}  # only tracks 1 and 2 have both
    assert agreement([label(1, "a", [])], SCENES) is None  # one labeller
    assert agreement([label(1, "a", []), label(2, "b", [])], SCENES)["n_tracks"] == 0


# -- the catalog top lists ---------------------------------------------------------------------


def test_catalog_precision_counts_the_labelled_and_unlabelled_tracks_of_the_list() -> None:
    ids = np.arange(10, 20)
    scores = np.zeros((10, 3))
    scores[:, 0] = np.arange(10, 0, -1)  # combat: ids 10, 11, 12, 13 first
    scores[:, 1] = np.arange(1, 11)  # boss: ids 19, 18, 17, 16 first
    scores[[4, 5, 6, 8], 2] = [4, 3, 2, 1]  # menu: ids 14, 15, 16, 18 first
    labels = [
        label(10, "a", ["combat"]),
        label(11, "a", []),
        label(13, "a", ["combat"]),
        label(17, "a", ["boss"]),
    ]
    merged = merge_labels(labels, SCENES)
    result = _catalog_precision(ids, scores, SCENES, merged, 4)
    assert result["combat"] == {"p_at_k": pytest.approx(2 / 3), "labelled": 3, "unlabelled": 1}
    assert result["boss"] == {"p_at_k": 1.0, "labelled": 1, "unlabelled": 3}
    # nothing labelled in the list: no precision, all unlabelled
    assert result["menu"] == {"p_at_k": None, "labelled": 0, "unlabelled": 4}


# -- the whole evaluation ----------------------------------------------------------------------


@pytest.fixture
def labelled():  # noqa: ANN201
    settings = get_settings()
    with open_catalog(settings) as repo:
        ids, vectors, signal = signal_catalog(repo, 120)
        entries = build_registry(settings, repo)
        label_tracks(repo, ids, signal, "owner", intensity="mid")
        yield settings, repo, ids, signal, entries


def test_the_evaluation_reports_every_entry_on_the_pool_and_the_catalog(labelled) -> None:  # noqa: ANN001
    settings, repo, ids, signal, (plain, centered) = labelled
    result = evaluate_scenes(repo, settings, k=10, folds=4, seed=2)
    assert json.loads(json.dumps(result, allow_nan=False)) == result  # plain JSON
    assert (result["k"], result["folds"], result["seed"]) == (10, 4, 2)
    assert result["selected"] == centered["id"] and result["scenes"] == list(DEFAULT_SCENES)
    assert result["labels"]["tracks"] == 120 and result["labels"]["with_embedding"] == 120
    assert result["labels"]["labellers"] == {"owner": {"labelled": 120, "skipped": 0}}
    assert result["labels"]["positives"]["combat"] == int(signal[:, 0].sum())
    assert result["labels"]["positives"]["horror"] == 0

    variants = [e["variant"] for e in result["entries"]]
    assert variants == ["zeroshot-catalog", "zeroshot-catalog-centered", "logreg-hybrid"]
    zero_plain, zero_centered, head = result["entries"]
    assert (zero_plain["id"], zero_centered["id"], head["id"]) == (
        plain["id"],
        centered["id"],
        None,
    )
    assert [e["selected"] for e in result["entries"]] == [False, True, False]
    assert zero_centered["centering"] == 0.75 and head["method"] == "head"
    assert head["fallback"] in variants[:2]
    for e in result["entries"]:
        pool = e["pool"]
        assert pool["scenes_scored"] == 3 and pool["per_scene"]["horror"]["p_at_k"] is None
        assert pool["per_scene"]["combat"]["positives"] == int(signal[:, 0].sum())
    # the head learned the labels; the prompts know nothing of the synthetic coordinates
    assert head["pool"]["mean_p_at_k"] > 0.9 > zero_plain["pool"]["mean_p_at_k"] + 0.2
    # catalog lists: every list has k tracks, all of them labelled (the whole catalog is)
    for e in (zero_plain, zero_centered):
        for scene in DEFAULT_SCENES:
            cell = e["catalog"][scene]
            assert (cell["labelled"], cell["unlabelled"]) == (10, 0)
    assert head["catalog"] is None  # no head registered yet
    # the intensity labels were all "mid" and there is only one labeller
    assert result["intensity"]["energy"] == {"rho": None, "n": 0}
    assert result["agreement"] is None


def test_the_evaluation_is_reproducible_and_needs_labels(labelled) -> None:  # noqa: ANN001
    settings, repo, *_ = labelled
    first = evaluate_scenes(repo, settings, k=5, folds=3, seed=1)
    again = evaluate_scenes(repo, settings, k=5, folds=3, seed=1)
    first.pop("created_at"), again.pop("created_at")
    assert first == again
    with pytest.raises(ValueError, match="at least 2"):
        evaluate_scenes(repo, settings, folds=1)
    for track in repo.iter_scene_labels():
        repo.delete_scene_label(track.track_id, track.labeller)
    with pytest.raises(ValueError, match="no hand labels"):
        evaluate_scenes(repo, settings)


def test_partial_labels_leave_the_rest_of_the_lists_unlabelled(labelled) -> None:  # noqa: ANN001
    settings, repo, ids, signal, _ = labelled
    for track in ids[30:]:  # keep 30 labelled
        repo.delete_scene_label(track, "owner")
    result = evaluate_scenes(repo, settings, k=10, folds=3)
    assert result["labels"]["tracks"] == 30
    for e in result["entries"][:2]:
        for cell in e["catalog"].values():
            assert cell["labelled"] + cell["unlabelled"] == 10 and cell["unlabelled"] >= 1


def test_intensity_is_correlated_with_the_dsp_energy_and_the_arousal_head(labelled) -> None:  # noqa: ANN001
    settings, repo, ids, signal, _ = labelled
    levels = ["low", "mid", "high"]
    for i, track in enumerate(ids):
        repo.set_scene_label(track, "owner", [], levels[i % 3], "labelled")
        repo.set_features(track, {"analysis_version": "t", "energy": (i % 3) / 2 + (i % 5) * 0.01})
    result = evaluate_scenes(repo, settings, k=5, folds=3)
    energy = result["intensity"]["energy"]
    mapped = np.array([1 + i % 3 for i in range(len(ids))], dtype=float)
    values = np.array([(i % 3) / 2 + (i % 5) * 0.01 for i in range(len(ids))])
    assert energy["n"] == 120 and energy["rho"] == pytest.approx(spearman(values, mapped))
    assert energy["rho"] > 0.9
    assert result["intensity"]["arousal"] == {"rho": None, "n": 0}  # no arousal entry registered


def test_two_labellers_give_a_kappa_and_the_text_report_shows_it(labelled) -> None:  # noqa: ANN001
    settings, repo, ids, signal, _ = labelled
    label_tracks(repo, ids[:40], signal[:40], "friend", intensity="high")
    flipped = ~signal[:10]
    label_tracks(repo, ids[:10], flipped, "friend")  # disagrees on the first ten
    result = evaluate_scenes(repo, settings, k=10, folds=3)
    agree = result["agreement"]
    assert agree["labellers"] == ["owner", "friend"] and agree["n_tracks"] == 40
    assert agree["per_scene"]["combat"]["kappa"] is not None and 0 < agree["mean_kappa"] < 1
    assert agree["intensity"]["n"] == 40
    text = format_report(result)
    assert "Hand labels: 120 tracks" in text and "owner 120 labelled" in text
    assert "zeroshot-catalog-centered *" in text  # the selected entry is marked
    assert "too few" in text and "mean P@k" in text
    assert "Agreement between owner and friend on 40 shared tracks" in text
    assert "Catalog top-10" in text and "(10/0)" in text


def test_the_result_is_written_under_the_data_dir_and_found_again(labelled) -> None:  # noqa: ANN001
    settings, repo, *_ = labelled
    assert latest_results(settings) is None
    result = evaluate_scenes(repo, settings, folds=3)
    path = write_results(settings, result)
    assert path.parent == settings.data_dir / "benchmarks" / "results"
    assert path.name.startswith("scenes_") and path.suffix == ".json"
    assert latest_results(settings) == result
    newer = write_results(settings, {**result, "k": 3})
    assert newer != path and latest_results(settings)["k"] == 3
    (settings.data_dir / "benchmarks/results/scenes_9.json").write_text("{", encoding="utf-8")
    assert latest_results(settings) is None  # the newest file is unreadable


def test_the_eval_command_prints_a_table_or_json_and_writes_the_file(labelled) -> None:  # noqa: ANN001
    settings, repo, *_ = labelled
    repo.close()
    text = runner.invoke(app, ["scenes", "eval", "--folds", "3", "--k", "5"])
    assert text.exit_code == 0, text.output
    assert "Pool (labelled tracks" in text.output and "Wrote " in text.output
    assert len(list((settings.data_dir / "benchmarks/results").glob("scenes_*.json"))) == 1
    as_json = runner.invoke(app, ["scenes", "eval", "--json", "--folds", "3"])
    assert as_json.exit_code == 0
    assert json.loads(as_json.output)["kind"] == "scene-eval"
    assert len(list((settings.data_dir / "benchmarks/results").glob("scenes_*.json"))) == 2


def test_the_eval_command_needs_labels_and_a_scene_tagger() -> None:
    result = runner.invoke(app, ["scenes", "eval"])
    assert result.exit_code == 1 and "mcrar scenes build" in result.output
    settings = get_settings()
    with open_catalog(settings) as repo:
        signal_catalog(repo, 60)
        build_registry(settings, repo)
    result = runner.invoke(app, ["scenes", "eval"])
    assert result.exit_code == 1 and "no hand labels" in result.output
    assert "Traceback" not in result.output


# -- the model card ----------------------------------------------------------------------------


def test_the_model_card_section_is_left_out_without_results_and_filled_with_them(
    labelled,  # noqa: ANN001
) -> None:
    settings, repo, *_ = labelled
    registry = read_registry(settings)
    assert scene_section(None, registry) == []
    (settings.home / "docs").mkdir(exist_ok=True)
    write_model_card(settings)
    card = (settings.home / "docs/model_card.md").read_text(encoding="utf-8")
    assert "## Game scenes" not in card and "## Heads and calibration" in card

    result = evaluate_scenes(repo, settings, k=10, folds=3)
    write_results(settings, result)
    write_model_card(settings)
    card = (settings.home / "docs/model_card.md").read_text(encoding="utf-8")
    section = card.split("## Game scenes")[1].split("## Heads and calibration")[0]
    assert "120 labelled tracks" in section and "owner (120 labelled, 0 skipped)" in section
    assert (
        "| Scene | Positives | zeroshot-catalog | zeroshot-catalog-centered | logreg-hybrid |"
        in section
    )
    assert "| combat |" in section and "too few" in section and "| mean P@k |" in section
    assert "Catalog top-10" in section and "in-sample" in section
    assert "Intensity, Spearman rho" in section and "not measured (needs two labellers)" in section
    assert f"Selected entry: {registry['selected']['scene']}" in section
    assert "### scene" in card  # the existing metrics tables are untouched
