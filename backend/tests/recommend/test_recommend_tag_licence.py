"""Stored tags are only trusted when their model version is allowed in the current licence mode."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from recommend_support import QUERY_TEXTS, MapEmbedder

from mcrar.catalog import CatalogRepository
from mcrar.config import Settings, get_settings
from mcrar.recommend import (
    CompositeTagScorer,
    SearchFilters,
    SearchRequest,
    SearchService,
    StoredTagScorer,
)
from mcrar.recommend.tags import allowed_tag_versions

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ml"))
from tagging_support import register  # noqa: E402  (tests/ has no __init__.py)

LABELS = ["a", "b", "c"]  # the labels of the fixture registry's genre set


def test_only_rows_of_the_allowed_version_are_used(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    a, b, c = ids["Shadow Walk"], ids["Quiet Vents"], ids["Night Heist"]
    repo.set_tag_probs(a, "genre", "head", "genre-good@1", {"jazz": 0.9})
    repo.set_tag_probs(b, "genre", "head", "genre-nc@2", {"jazz": 0.8})
    scorer = StoredTagScorer(repo, {"genre": "genre-good@1"})
    scores, covered = scorer.scores_with_coverage([a, b, c], "genre", ["jazz"])
    assert list(covered) == [True, False, False]
    assert list(scores["jazz"]) == [pytest.approx(0.9), 0.0, 0.0]


@pytest.mark.parametrize("allowed", [{}, {"genre": None}, {"moodtheme": "mood@1"}])
def test_a_label_set_without_an_allowed_version_has_no_usable_rows(
    repo: CatalogRepository, ids: dict[str, int], allowed: dict[str, str | None]
) -> None:
    track = ids["Shadow Walk"]
    repo.set_tag_probs(track, "genre", "head", "genre-good@1", {"jazz": 0.9})
    _, covered = StoredTagScorer(repo, allowed).scores_with_coverage([track], "genre", ["jazz"])
    assert not covered.any()


def test_without_a_mapping_every_row_is_accepted(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    track = ids["Shadow Walk"]
    repo.set_tag_probs(track, "genre", "head", "whatever@9", {"jazz": 0.9})
    _, covered = StoredTagScorer(repo).scores_with_coverage([track], "genre", ["jazz"])
    assert covered.all()


def test_the_composite_falls_back_to_zero_shot_for_rejected_rows(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    track = ids["Shadow Walk"]
    repo.set_tag_probs(track, "genre", "head", "genre-nc@2", {"jazz": 0.99})

    class Spy:
        def scores(self, track_ids, label_set, labels):  # noqa: ANN001, ANN201
            return {label: np.full(len(track_ids), 0.25) for label in labels}

    gated = CompositeTagScorer(StoredTagScorer(repo, {"genre": "genre-good@1"}), Spy())
    assert gated.scores([track], "genre", ["jazz"])["jazz"][0] == pytest.approx(0.25)
    open_ = CompositeTagScorer(StoredTagScorer(repo), Spy())
    assert open_.scores([track], "genre", ["jazz"])["jazz"][0] == pytest.approx(0.99)


# -- from the registry --------------------------------------------------------------------------


def settings_with_registry(commercial_mode: bool, *, entry_commercial: bool) -> Settings:
    settings = get_settings(commercial_mode=commercial_mode, search={"max_per_artist": 50})
    register(settings, commercial=entry_commercial)
    return settings


def test_no_registry_means_no_allowed_version() -> None:
    assert allowed_tag_versions(get_settings()) == {}


def test_a_broken_registry_means_no_allowed_version() -> None:
    settings = get_settings()
    (settings.models_dir).mkdir(parents=True)
    (settings.models_dir / "registry.json").write_text("{not json", encoding="utf-8")
    assert allowed_tag_versions(settings) == {}


def test_the_allowed_version_depends_on_the_mode() -> None:
    settings = settings_with_registry(True, entry_commercial=False)
    assert allowed_tag_versions(settings) == {"genre": None}
    entry = allowed_tag_versions(get_settings(commercial_mode=False))["genre"]
    assert entry is not None and entry.startswith("genre-logreg@")


def test_a_commercial_entry_is_allowed_in_both_modes() -> None:
    settings = settings_with_registry(True, entry_commercial=True)
    entry = allowed_tag_versions(settings)["genre"]
    assert entry is not None and entry.startswith("genre-logreg@")
    assert allowed_tag_versions(get_settings(commercial_mode=False)) == {"genre": entry}


def service_for(repo: CatalogRepository, settings: Settings) -> SearchService:
    embedder = MapEmbedder(QUERY_TEXTS)
    return SearchService(repo, settings, embedder_loader=lambda: embedder)


def genre_score(service: SearchService, track_id: int) -> float:
    request = SearchRequest("", SearchFilters(genres=("a",), vocal="instrumental"), limit=50)
    item = next(i for i in service.search(request).items if i.track_id == track_id)
    return next(t.score for t in item.top_tags if t.label == "a")


def test_a_non_commercial_tag_is_ignored_in_commercial_mode_and_used_otherwise(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    track = ids["Shadow Walk"]
    settings = settings_with_registry(True, entry_commercial=False)
    version = allowed_tag_versions(get_settings(commercial_mode=False))["genre"]
    repo.set_tag_probs(track, "genre", "head", version, {"a": 0.987, "b": 0.0, "c": 0.0})

    commercial = service_for(repo, settings)
    assert genre_score(commercial, track) != pytest.approx(0.987)  # zero-shot instead

    non_commercial = service_for(repo, get_settings(commercial_mode=False))
    assert genre_score(non_commercial, track) == pytest.approx(0.987)


def test_a_commercial_tag_is_used_in_both_modes(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    track = ids["Shadow Walk"]
    settings = settings_with_registry(True, entry_commercial=True)
    version = allowed_tag_versions(settings)["genre"]
    repo.set_tag_probs(track, "genre", "head", version, {"a": 0.987, "b": 0.0, "c": 0.0})
    assert genre_score(service_for(repo, settings), track) == pytest.approx(0.987)
    assert genre_score(
        service_for(repo, get_settings(commercial_mode=False)), track
    ) == pytest.approx(0.987)


def test_rows_of_an_older_version_are_ignored(repo: CatalogRepository, ids: dict[str, int]) -> None:
    track = ids["Shadow Walk"]
    settings = settings_with_registry(True, entry_commercial=True)
    repo.set_tag_probs(track, "genre", "head", "genre-logreg@0000000", {"a": 0.987, "b": 0, "c": 0})
    assert genre_score(service_for(repo, settings), track) != pytest.approx(0.987)
