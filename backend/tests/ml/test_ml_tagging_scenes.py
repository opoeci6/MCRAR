"""The zero-shot scene tagger (M9): the catalog-referenced build, its registry entry, tagging and
the CLI, all with a fake CLAP and synthetic catalog vectors (no model, no network)."""

from __future__ import annotations

import json
import re

import numpy as np
import pytest
from ml_support import FakeEmbedder
from tagging_support import register
from typer.testing import CliRunner

from mcrar import cli
from mcrar.catalog import CatalogRepository, TrackRecord, open_catalog
from mcrar.cli import app
from mcrar.config import get_settings
from mcrar.ml.tagging import TaggingStage, load_taggers, select_entry, tagging_stages
from mcrar.ml.tagging.registry import _NON_COMMERCIAL, read_registry, validate_registry
from mcrar.ml.tagging.runtime import load_tagger
from mcrar.ml.tagging.scenes import MIN_REFERENCE, build_scene_entries
from mcrar.recommend.tags import allowed_tag_versions
from mcrar.recommend.vocab import DEFAULT_SCENE_DISPLAY, DEFAULT_SCENES

runner = CliRunner()
MODEL = "clap@195c3a3"


def clap() -> FakeEmbedder:
    return FakeEmbedder("clap", revision="195c3a3", dim=512)


def build_scene_entry(settings, embedder, repo, **kwargs) -> dict:  # noqa: ANN001, ANN003
    """Build both variants and return the selected one (the centered entry)."""
    return build_scene_entries(settings, embedder, repo, **kwargs)[1]


def fill_catalog(repo: CatalogRepository, n: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    matrix = rng.normal(size=(n, 512)).astype(np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    for i, vector in enumerate(matrix):
        track = repo.upsert_track(TrackRecord(source="jamendo", source_id=str(i), title=f"T{i}"))
        repo.set_embedding(track, MODEL, vector)
    return matrix


# -- the registry: entries without metrics ---------------------------------------------------


def entry(identity: str, created_at: str, metrics: object) -> dict:
    return {"id": identity, "created_at": created_at, "commercial_ok": True, "metrics": metrics}


def test_select_entry_prefers_evaluated_entries_over_unevaluated_ones() -> None:
    evaluated = entry("a", "2026-01-01", {"split": "test", "primary": "macro_f1", "macro_f1": 0.3})
    newest = entry("z", "2026-09-01", None)
    spec = {"kind": "single_label", "entries": [newest, evaluated]}
    assert select_entry(spec)["id"] == "a"


def test_select_entry_takes_the_newest_unevaluated_entry_without_an_evaluated_one() -> None:
    old, new = entry("zz", "2026-01-01", None), entry("aa", "2026-05-01", None)
    spec = {"kind": "multi_label", "entries": [new, old]}
    assert select_entry(spec)["id"] == "aa"
    same_time = {
        **spec,
        "entries": [entry("aa", "2026-05-01", None), entry("bb", "2026-05-01", None)],
    }
    assert select_entry(same_time)["id"] == "bb"  # then the larger id
    assert select_entry({"kind": "multi_label", "entries": []}) is None
    nan = {"split": "test", "primary": "macro_pr_auc", "macro_pr_auc": float("nan")}
    assert select_entry({"kind": "multi_label", "entries": [entry("n", "", nan)]}) is None


def test_the_model_card_tables_list_an_unevaluated_entry() -> None:
    from mcrar.ml.tagging.report import metric_tables

    registry = {
        "label_sets": {
            "scene": {"entries": [{"variant": "zeroshot-catalog", "metrics": None}]},
            "genre": {"entries": []},
        }
    }
    tables = metric_tables(registry)
    assert "### scene" in tables and "| zeroshot-catalog | — | not evaluated |" in tables
    assert "| Pending data run |" in tables  # genre, without entries, as before


def test_the_scene_metric_table_has_as_many_cells_as_its_header() -> None:
    from mcrar.ml.tagging.report import metric_tables

    metrics = {
        "split": "hand-labels-cv",
        "primary": "mean_p_at_10",
        "mean_p_at_10": 0.4143,
        "n_tracks": 164,
    }
    registry = {
        "label_sets": {"scene": {"entries": [{"variant": "logreg-hybrid", "metrics": metrics}]}}
    }
    rows = [line for line in metric_tables(registry).splitlines() if line.startswith("|")]
    assert rows[0] == "| Variant | Test n | Primary (95% CI) |"
    assert rows[2] == "| logreg-hybrid | 164 | 0.4143 |"  # the scene count is n_tracks
    assert {row.count("|") for row in rows} == {4}


def test_the_test_count_is_n_and_a_dash_when_neither_is_recorded() -> None:
    from mcrar.ml.tagging.report import metric_tables

    def row(metrics: dict) -> str:
        registry = {"label_sets": {"scene": {"entries": [{"variant": "v", "metrics": metrics}]}}}
        return metric_tables(registry).splitlines()[4]

    base = {"primary": "p", "p": 0.5}
    assert row({**base, "n": 7, "n_tracks": 9}) == "| v | 7 | 0.5000 |"
    assert row(base) == "| v | — | 0.5000 |"


def test_the_pending_row_has_as_many_cells_as_the_header_with_and_without_columns() -> None:
    from mcrar.ml.tagging.report import metric_tables

    for name in ("scene", "genre", "moodtheme", "valence"):
        rows = [
            line
            for line in metric_tables({"label_sets": {name: {"entries": []}}}).splitlines()
            if line.startswith("|")
        ]
        assert len(rows) == 3 and {row.count("|") for row in rows} == {rows[0].count("|")}
    scene = metric_tables({"label_sets": {"scene": {"entries": []}}}).splitlines()
    assert scene[-1] == "| Pending data run | — | — |"


def test_the_registry_accepts_null_metrics_only() -> None:
    settings = get_settings()
    with open_catalog(settings) as repo:
        fill_catalog(repo, MIN_REFERENCE)
        built = build_scene_entry(settings, clap(), repo)
    registry = read_registry(settings)  # validates the null-metrics entry and its artifact
    assert registry["label_sets"]["scene"]["entries"][0]["metrics"] is None
    registry["label_sets"]["scene"]["entries"][0]["metrics"] = {"split": "validation"}
    with pytest.raises(ValueError, match="test-split metrics"):
        validate_registry(registry)
    registry["label_sets"]["scene"]["entries"][0]["metrics"] = {
        "split": "test",
        "primary": "macro_pr_auc",
        "macro_pr_auc": float("nan"),
    }
    with pytest.raises(ValueError, match="finite"):
        validate_registry(registry)
    assert built["metrics"] is None


# -- the build -------------------------------------------------------------------------------


def test_build_writes_a_content_addressed_artifact_and_registers_it() -> None:
    settings = get_settings()
    with open_catalog(settings) as repo:
        reference = fill_catalog(repo, 60)
        embedder = clap()
        plain, built = build_scene_entries(settings, embedder, repo)
    assert re.fullmatch(r"scene-zeroshot-catalog@[0-9a-f]{7}", plain["id"])
    assert re.fullmatch(r"scene-zeroshot-catalog-centered@[0-9a-f]{7}", built["id"])
    assert (plain["centering"], built["centering"]) == (0.0, 0.75)
    assert built["prefer"] is True and "prefer" not in plain
    for entry, variant in ((plain, "zeroshot-catalog"), (built, "zeroshot-catalog-centered")):
        assert (settings.models_dir / entry["file"]).is_file()
        assert (entry["method"], entry["variant"], entry["metrics"]) == ("zeroshot", variant, None)
        assert entry["commercial_ok"] is True and entry["seed"] == 0
        assert entry["reference_data"] == "catalog@60 tracks"
        assert "NC" not in entry["data_license"].upper() and entry["created_at"].endswith("Z")
    assert not embedder.closed  # the caller owns the embedder

    registry = read_registry(settings)
    spec = registry["label_sets"]["scene"]
    assert (spec["kind"], spec["labels"]) == ("multi_label", list(DEFAULT_SCENES))
    assert spec["display"] == DEFAULT_SCENE_DISPLAY
    assert [e["id"] for e in spec["entries"]] == [plain["id"], built["id"]]
    assert registry["selected"]["scene"] == built["id"]  # the centered one, before any labels

    tagger = load_tagger(settings.models_dir / built["file"], built["id"])
    assert (tagger.label_set, tagger.method, tagger.labels) == ("scene", "zeroshot", DEFAULT_SCENES)
    scores = reference @ tagger.arrays["text_vectors"].T  # the stored (centered) vectors
    np.testing.assert_allclose(tagger.arrays["reference_mean"], scores.mean(axis=0), atol=1e-6)
    np.testing.assert_allclose(tagger.arrays["reference_std"], scores.std(axis=0), rtol=1e-4)
    assert np.isfinite(tagger.arrays["text_vectors"]).all()
    # centering: t' = t - 0.75 * mean of the label vectors, and the plain entry keeps t
    flat = load_tagger(settings.models_dir / plain["file"], plain["id"]).arrays["text_vectors"]
    np.testing.assert_allclose(
        tagger.arrays["text_vectors"], flat - 0.75 * flat.mean(axis=0), atol=1e-6
    )
    # the prompts of prompts/scene.toml, embedded with the fake: three templates per synonym
    texts = tagger.arrays["prompt_texts"].tolist()
    assert "video game music for an epic boss fight" in texts
    assert len(texts) == (13 * 2 + 3) * 3  # synonyms (combat has three) times three templates


def test_the_probabilities_are_in_range_and_centre_on_the_catalog() -> None:
    settings = get_settings()
    with open_catalog(settings) as repo:
        reference = fill_catalog(repo, 80)
        built = build_scene_entry(settings, clap(), repo)
    tagger = load_tagger(settings.models_dir / built["file"], built["id"])
    probs = tagger.predict(reference)
    assert list(probs) == list(DEFAULT_SCENES)
    for values in probs.values():
        assert values.shape == (80,) and ((values >= 0) & (values <= 1)).all()
        assert values.mean() == pytest.approx(0.5, abs=0.1)  # z-scored on these very vectors


def test_building_again_replaces_the_entry_and_is_deterministic() -> None:
    settings = get_settings()
    with open_catalog(settings) as repo:
        fill_catalog(repo, 60)
        first = build_scene_entries(settings, clap(), repo)
        again = build_scene_entries(settings, clap(), repo)
        assert [e["id"] for e in again] == [e["id"] for e in first]  # same artifacts
        fill_catalog(repo, 70, seed=0)  # ten more tracks (the first 60 keep their vectors)
        grown = build_scene_entries(settings, clap(), repo)
    assert {e["id"] for e in grown}.isdisjoint(e["id"] for e in first)
    assert all(e["reference_data"] == "catalog@70 tracks" for e in grown)
    registry = read_registry(settings)
    assert [e["id"] for e in registry["label_sets"]["scene"]["entries"]] == [e["id"] for e in grown]
    assert registry["selected"]["scene"] == grown[1]["id"]


def test_the_preferred_unevaluated_entry_wins_whatever_the_timestamps() -> None:
    old_but_preferred = {**entry("a", "2026-01-01", None), "prefer": True}
    newer = entry("z", "2026-09-01", None)
    spec = {"kind": "multi_label", "entries": [newer, old_but_preferred]}
    assert select_entry(spec)["id"] == "a"
    spec["entries"][1] = entry(
        "b", "2026-09-01", {"split": "test", "primary": "macro_pr_auc", "macro_pr_auc": 0.1}
    )
    assert select_entry(spec)["id"] == "b"  # an evaluated entry still beats a preferred one


def test_the_models_dir_can_be_overridden(tmp_path) -> None:  # noqa: ANN001
    settings = get_settings()
    elsewhere = tmp_path / "other-models"
    with open_catalog(settings) as repo:
        fill_catalog(repo, 60)
        built = build_scene_entry(settings, clap(), repo, models_dir=elsewhere)
    assert (elsewhere / built["file"]).is_file() and (elsewhere / "registry.json").is_file()
    assert not (settings.models_dir / "registry.json").exists()


def test_a_catalog_that_is_too_small_is_refused() -> None:
    settings = get_settings()
    embedder = clap()
    with open_catalog(settings) as repo:
        fill_catalog(repo, MIN_REFERENCE - 1)
        with pytest.raises(
            ValueError, match=rf"has {MIN_REFERENCE - 1} {MODEL} embeddings.*at least"
        ):
            build_scene_entries(settings, embedder, repo)
    assert not (settings.models_dir / "registry.json").exists()
    assert embedder.text_calls == []  # it failed before embedding any prompt


def test_the_build_leaves_the_other_label_sets_alone() -> None:
    settings = get_settings()
    genre = register(settings)["label_sets"]["genre"]["entries"][0]
    with open_catalog(settings) as repo:
        fill_catalog(repo, 60)
        built = build_scene_entry(settings, clap(), repo)
    registry = read_registry(settings)
    assert registry["label_sets"]["genre"]["entries"] == [genre]
    assert registry["selected"] == {"scene": built["id"]}
    selected = {t.label_set: t.entry_id for t in load_taggers(settings)}
    assert selected == {"genre": genre["id"], "scene": built["id"]}
    assert allowed_tag_versions(settings) == {"genre": genre["id"], "scene": built["id"]}


def test_the_scene_stage_tags_the_catalog_and_the_search_accepts_the_rows() -> None:
    settings = get_settings()
    with open_catalog(settings) as repo:
        fill_catalog(repo, 60)
        built = build_scene_entry(settings, clap(), repo)
        stages = tagging_stages(settings)
        assert [s.name for s in stages] == ["tag:scene"]
        stage = stages[0]
        assert isinstance(stage, TaggingStage) and stage.version == built["id"]
        track = int(repo.load_embeddings(MODEL)[0][0])
        assert not stage.is_current(repo, track)
        stage.run(repo, track)
        assert stage.is_current(repo, track)
        rows = repo.get_tag_probs(track, head="scene")
        assert {r.label for r in rows} == set(DEFAULT_SCENES)
        assert all(0 <= r.prob <= 1 and r.model_version == built["id"] for r in rows)
        assert {r.method for r in rows} == {"zeroshot"}
    assert allowed_tag_versions(settings)["scene"] == built["id"]


# -- the CLI ---------------------------------------------------------------------------------


class Loader:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.embedder = clap()

    def __call__(self, key: str, settings: object, **kwargs: object) -> FakeEmbedder:
        self.calls.append(key)
        return self.embedder


@pytest.fixture
def loader(monkeypatch: pytest.MonkeyPatch) -> Loader:
    fake = Loader()
    monkeypatch.setattr(cli, "_load_embedder", fake)
    return fake


def test_scenes_build_cli_registers_the_entry_and_points_at_tag(loader: Loader) -> None:
    settings = get_settings()
    with open_catalog(settings) as repo:
        fill_catalog(repo, 60)
    result = runner.invoke(app, ["scenes", "build"])
    assert result.exit_code == 0, result.output
    built = read_registry(settings)["selected"]["scene"]
    assert (
        f"Selected: {built}" in result.output and "Built scene-zeroshot-catalog@" in result.output
    )
    assert "mcrar tag --label-sets scene" in result.output
    assert loader.calls == ["clap"] and loader.embedder.closed

    tagged = runner.invoke(app, ["tag", "--label-sets", "scene"])
    assert tagged.exit_code == 0, tagged.output
    assert "Tagged 60" in tagged.output
    with open_catalog(settings) as repo:
        track = int(repo.load_embeddings(MODEL)[0][0])
        assert len(repo.get_tag_probs(track, "scene")) == 14
    assert runner.invoke(app, ["tag", "--label-sets", "scene"]).output.count("skipped 60") == 1


def test_scenes_build_cli_needs_a_big_enough_catalog_before_loading_the_model(
    loader: Loader,
) -> None:
    with open_catalog(get_settings()) as repo:
        fill_catalog(repo, 10)
    result = runner.invoke(app, ["scenes", "build"])
    assert result.exit_code == 1 and "error:" in result.output
    assert f"at least {MIN_REFERENCE}" in result.output and "Traceback" not in result.output
    assert loader.calls == []


def test_tag_accepts_scene_and_still_rejects_unknown_label_sets() -> None:
    settings = get_settings()
    register(settings)  # only a genre entry: scene has nothing to tag with yet
    assert "No tagging entries" in runner.invoke(app, ["tag", "--label-sets", "scene"]).output
    result = runner.invoke(app, ["tag", "--label-sets", "genre,polka"])
    assert result.exit_code == 1 and "unknown label sets: polka" in result.output


def test_tagging_evaluate_and_select_cope_with_an_unevaluated_scene_set(loader: Loader) -> None:
    settings = get_settings()
    with open_catalog(settings) as repo:
        fill_catalog(repo, 60)
    assert runner.invoke(app, ["scenes", "build"]).exit_code == 0
    evaluated = runner.invoke(app, ["tagging", "evaluate"])  # scene has no labelled dataset
    assert evaluated.exit_code == 0, evaluated.output
    assert read_registry(settings)["label_sets"]["scene"]["entries"][0]["metrics"] is None
    selected = runner.invoke(app, ["tagging", "select"])
    assert selected.exit_code == 0 and "scene: scene-zeroshot-catalog-centered@" in selected.output
    on_disk = json.loads((settings.models_dir / "registry.json").read_text(encoding="utf-8"))
    assert on_disk["selected"]["scene"].startswith("scene-zeroshot-catalog-centered@")


@pytest.mark.parametrize(
    ("licence", "non_commercial"),
    [
        ("CC BY-NC (version unspecified, per DEAM manual)", True),
        ("CC BY-NC-SA 4.0", True),
        ("Non-commercial research only", True),
        ("noncommercial", True),
        ("CC BY 4.0", False),
        ("none (catalog embeddings used as the reference)", False),  # "nc" inside a word
    ],
)
def test_the_non_commercial_check_matches_licence_elements_only(
    licence: str, non_commercial: bool
) -> None:
    assert bool(_NON_COMMERCIAL.search(licence)) is non_commercial
