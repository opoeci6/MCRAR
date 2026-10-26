"""The labelling pool (M9): choosing the tracks from every zero-shot entry's top lists and a
seeded random draw, shuffling, splitting into parts, and refusing to replace without --force."""

from __future__ import annotations

import numpy as np
import pytest
from scene_support import build_registry, signal_catalog
from typer.testing import CliRunner

from mcrar.catalog import open_catalog
from mcrar.cli import app
from mcrar.config import get_settings
from mcrar.ml.tagging.scene_head import probability_matrix, zeroshot_entries
from mcrar.ml.tagging.scene_pool import build_pool, save_pool, summarise_pool
from mcrar.recommend.vocab import DEFAULT_SCENES

runner = CliRunner()
SMALL = {"per_scene": 2, "random_n": 10, "both_n": 6, "seed": 0}


@pytest.fixture
def catalog():
    settings = get_settings()
    with open_catalog(settings) as repo:
        ids, vectors, _ = signal_catalog(repo, 120)
        build_registry(settings, repo)
        yield settings, repo, ids, vectors


def test_the_pool_needs_the_scene_entries_and_embeddings() -> None:
    settings = get_settings()
    with open_catalog(settings) as repo:
        signal_catalog(repo, 60)
        with pytest.raises(ValueError, match="mcrar scenes build"):
            build_pool(repo, settings)
        build_registry(settings, repo)
    with open_catalog(get_settings(data_dir=settings.data_dir / "other")) as empty:
        with pytest.raises(ValueError, match="no clap@195c3a3 embeddings"):
            build_pool(empty, settings)


def test_the_pool_takes_each_entrys_top_tracks_then_random_ones(catalog) -> None:  # noqa: ANN001
    settings, repo, ids, vectors = catalog
    pool = build_pool(repo, settings, **SMALL)
    track_ids = [e.track_id for e in pool]
    assert len(set(track_ids)) == len(track_ids)  # a track is in the pool once
    assert [e.position for e in pool] == list(range(1, len(pool) + 1))
    reasons = {e.track_id: e.reason for e in pool}
    assert sum(r == "random" for r in reasons.values()) == 10
    variants = {r.split(":")[2] for r in reasons.values() if r != "random"}
    assert variants == {"zeroshot-catalog", "zeroshot-catalog-centered"}
    assert {r.split(":")[1] for r in reasons.values() if r != "random"} <= set(DEFAULT_SCENES)

    # the best track of the plain entry for the first scene is in, with that reason (it is first)
    (plain, plain_tagger), (_, centered_tagger) = zeroshot_entries(settings)
    column = probability_matrix(plain_tagger, vectors)[:, 0]
    best = ids[int(np.lexsort((np.arange(len(ids)), -column))[0])]
    assert reasons[best] == f"top:{DEFAULT_SCENES[0]}:zeroshot-catalog"
    # every top-2 of the centered entry is in the pool (with its own or an earlier reason)
    scores = probability_matrix(centered_tagger, vectors)
    for j in range(len(DEFAULT_SCENES)):
        for index in np.lexsort((np.arange(len(ids)), -scores[:, j]))[:2]:
            assert ids[int(index)] in reasons
    # the first reason wins: a track in the plain entry's lists never carries a centered reason
    top_plain = {
        ids[int(i)]
        for j in range(len(DEFAULT_SCENES))
        for i in np.lexsort(
            (np.arange(len(ids)), -probability_matrix(plain_tagger, vectors)[:, j])
        )[:2]
    }
    assert all(reasons[t].endswith(":zeroshot-catalog") for t in top_plain)
    assert plain["variant"] == "zeroshot-catalog"


def test_the_pool_is_shuffled_and_deterministic(catalog) -> None:  # noqa: ANN001
    settings, repo, *_ = catalog
    first = build_pool(repo, settings, **SMALL)
    assert build_pool(repo, settings, **SMALL) == first
    other = build_pool(repo, settings, **{**SMALL, "seed": 1})
    assert [e.track_id for e in other] != [e.track_id for e in first]
    # not in the order the candidates were collected in (top lists first, then random)
    reasons = [e.reason for e in first]
    assert reasons != sorted(reasons, key=lambda r: r == "random")


def test_both_tracks_are_spread_and_the_rest_alternate(catalog) -> None:  # noqa: ANN001
    settings, repo, *_ = catalog
    pool = build_pool(repo, settings, **SMALL)
    n = len(pool)
    both = [e.position for e in pool if e.part == "both"]
    assert len(both) == 6
    gaps = np.diff([0, *both, n])
    assert gaps.max() <= n // 6 + 2 and gaps.min() >= 1  # evenly spread, none bunched
    rest = [e.part for e in pool if e.part != "both"]
    assert rest[:4] == ["A", "B", "A", "B"] and abs(rest.count("A") - rest.count("B")) <= 1
    summary = summarise_pool(pool)
    assert summary.size == n and sum(summary.parts.values()) == n and summary.parts["both"] == 6
    assert sum(summary.reasons.values()) == n and summary.reasons["random"] == 10
    everything = build_pool(repo, settings, per_scene=1, random_n=0, both_n=1000)
    assert {e.part for e in everything} == {"both"}  # more "both" than tracks: all of them
    assert not any(e.part == "both" for e in build_pool(repo, settings, **{**SMALL, "both_n": 0}))


def test_random_tracks_are_capped_by_what_is_left(catalog) -> None:  # noqa: ANN001
    settings, repo, ids, _ = catalog
    pool = build_pool(repo, settings, per_scene=1, random_n=10_000, both_n=0)
    assert {e.track_id for e in pool} == set(ids)  # the whole catalog, nothing twice
    with pytest.raises(ValueError, match="negative"):
        build_pool(repo, settings, per_scene=-1)


def test_save_pool_refuses_to_replace_without_force_and_keeps_labels(catalog) -> None:  # noqa: ANN001
    settings, repo, ids, _ = catalog
    pool = build_pool(repo, settings, **SMALL)
    assert save_pool(repo, pool) == len(pool)
    repo.set_scene_label(pool[0].track_id, "Ana", ["combat"], None, "labelled")
    again = build_pool(repo, settings, **{**SMALL, "seed": 5})
    pattern = rf"pool of {len(pool)} tracks already exists.*--force.*kept"
    with pytest.raises(ValueError, match=pattern):
        save_pool(repo, again)
    assert repo.label_pool() == pool
    assert save_pool(repo, again, force=True) == len(again)
    assert repo.label_pool() == again
    assert repo.get_scene_label(pool[0].track_id, "Ana") is not None  # labels are per track


def test_scenes_pool_cli_prints_counts_and_needs_force_to_replace() -> None:
    settings = get_settings()
    with open_catalog(settings) as repo:
        signal_catalog(repo, 80)
        build_registry(settings, repo)
    args = ["scenes", "pool", "--per-scene", "2", "--random", "10", "--both", "4"]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert "Pool of " in result.output and "parts: A " in result.output
    assert "top:combat:zeroshot-catalog" in result.output and "random: 10" in result.output
    assert "Labelling tab" in result.output
    with open_catalog(settings) as repo:
        first = repo.label_pool()
    refused = runner.invoke(app, [*args, "--seed", "3"])
    assert refused.exit_code == 1 and "--force" in refused.output
    with open_catalog(settings) as repo:
        assert repo.label_pool() == first
    assert runner.invoke(app, [*args, "--seed", "3", "--force"]).exit_code == 0
    with open_catalog(settings) as repo:
        assert repo.label_pool() != first
