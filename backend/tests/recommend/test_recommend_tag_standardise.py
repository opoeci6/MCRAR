"""Stored tag probabilities are standardised per label over the catalog (one scale for all).

Also: a filter-only genre/mood search is answered from the stored tags without the text model,
unless a track that has an embedding lacks allowed stored rows.
"""

from __future__ import annotations

import numpy as np
import pytest
from recommend_support import QUERY_TEXTS, MapEmbedder, catalog_score, make_settings

from mcrar.catalog import CatalogRepository
from mcrar.recommend import (
    CompositeTagScorer,
    SearchFilters,
    SearchRequest,
    SearchService,
    StandardisedTagScorer,
    StoredTagScorer,
    TagScorer,
)

GOOD, BAD = "genre-good@1", "genre-bad@2"
ONE_SIGMA = 1.0 / (1.0 + np.exp(-1.7))  # sigmoid(1.7 * 1): a track one std above the mean


def tag(
    repo: CatalogRepository,
    ids: dict[str, int],
    rows: dict[str, dict[str, float]],
    *,
    head: str = "genre",
    version: str = GOOD,
) -> None:
    for title, probs in rows.items():
        repo.set_tag_probs(ids[title], head, "head", version, probs)


def two_tagged(repo: CatalogRepository, ids: dict[str, int]) -> list[int]:
    """Smooth Cafe and Garage Band tagged, Lullaby not."""
    tag(repo, ids, {"Smooth Cafe": {"jazz": 0.9, "rock": 0.5}, "Garage Band": {"jazz": 0.1}})
    return [ids["Smooth Cafe"], ids["Garage Band"], ids["Lullaby"]]


# -- the numbers --------------------------------------------------------------------------------


def test_the_score_is_a_sigmoid_of_the_catalog_z_score(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    jazz = {"Smooth Cafe": 0.2, "Garage Band": 0.4, "Lullaby": 0.6, "Epic Quest": 0.8}
    tag(repo, ids, {title: {"jazz": p} for title, p in jazz.items()})
    scorer = StandardisedTagScorer(StoredTagScorer(repo))
    pool = [ids[title] for title in jazz]
    got = scorer.scores(pool, "genre", ["jazz"])["jazz"]
    # mean 0.5, std sqrt(0.05): z = -1.342, -0.447, +0.447, +1.342
    expected = [1 / (1 + np.exp(-1.7 * z)) for z in (-1.3416408, -0.4472136, 0.4472136, 1.3416408)]
    assert got.tolist() == pytest.approx(expected)
    assert got.tolist() == pytest.approx([catalog_score(list(jazz.values()), i) for i in range(4)])
    assert isinstance(scorer, TagScorer)


def test_two_values_are_one_sigma_either_side(repo: CatalogRepository, ids: dict[str, int]) -> None:
    pool = two_tagged(repo, ids)[:2]
    got = StandardisedTagScorer(StoredTagScorer(repo)).scores(pool, "genre", ["jazz"])["jazz"]
    assert got.tolist() == pytest.approx([ONE_SIGMA, 1 - ONE_SIGMA])


def test_the_score_does_not_depend_on_the_pool(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    two_tagged(repo, ids)
    scorer = StandardisedTagScorer(StoredTagScorer(repo))
    cafe = ids["Smooth Cafe"]
    alone = scorer.scores([cafe], "genre", ["jazz"])["jazz"][0]
    assert alone == pytest.approx(ONE_SIGMA)  # the catalog's statistics, not the pool's
    for pool in (
        [cafe, ids["Lullaby"]],
        [ids["Epic Quest"], ids["Garage Band"], cafe],
        list(ids.values()),
    ):
        assert scorer.scores(pool, "genre", ["jazz", "rock"])["jazz"][pool.index(cafe)] == alone


def test_a_mood_and_a_genre_label_on_different_scales_become_comparable(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    titles = list(ids)
    jazz = [0.3 + 0.03 * n for n in range(len(titles))]  # 0.3 .. 0.9, like a peaky genre head
    calm = [0.1 - 0.004 * n for n in range(len(titles))]  # 0.10 .. 0.02, low like a mood head
    for n, title in enumerate(titles):
        repo.set_tag_probs(ids[title], "genre", "head", GOOD, {"jazz": jazz[n]})
        repo.set_tag_probs(ids[title], "moodtheme", "head", "mood@1", {"calm": calm[n]})
    scorer = StandardisedTagScorer(StoredTagScorer(repo))
    pool = list(ids.values())
    genre = scorer.scores(pool, "genre", ["jazz"])["jazz"]
    mood = scorer.scores(pool, "moodtheme", ["calm"])["calm"]
    assert max(calm) < 0.2 < min(jazz)  # the raw values are on very different scales
    # The most-genre track and the most-mood track are equally far above their label's average.
    assert genre.max() == pytest.approx(mood.max())
    assert genre.min() == pytest.approx(mood.min())

    # Mirrored, so the tag term of a two-label request is the same for every track: neither the
    # genre nor the mood label dominates the mean (raw: 0.2 for the first, 0.46 for the last).
    service = SearchService(
        repo,
        make_settings(),
        embedder_loader=lambda: pytest.fail("no model"),
        stored_tags=StoredTagScorer(repo),
    )
    result = service.search(
        SearchRequest(
            "", SearchFilters(genres=("jazz",), moods=("calm",), max_risk="unknown"), limit=50
        )
    )
    assert len(result.items) == len(titles)
    assert [i.breakdown["tags"]["raw"] for i in result.items] == pytest.approx([0.5] * len(titles))


def test_a_covered_track_without_a_row_counts_as_zero_and_an_unseen_label_scores_zero(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    cafe, band, lullaby = two_tagged(repo, ids)
    scorer = StandardisedTagScorer(StoredTagScorer(repo))
    scores, covered = scorer.scores_with_coverage(
        [cafe, band, lullaby], "genre", ["jazz", "rock", "blues"]
    )
    assert covered.tolist() == [True, True, False]
    # rock: Smooth Cafe 0.5, Garage Band has no row (= 0): one sigma either side, like jazz
    assert scores["rock"].tolist() == pytest.approx([ONE_SIGMA, 1 - ONE_SIGMA, 0.0])
    assert scores["jazz"].tolist() == pytest.approx([ONE_SIGMA, 1 - ONE_SIGMA, 0.0])
    assert scores["blues"].tolist() == [0.0, 0.0, 0.0]  # no row anywhere: says nothing about it


def test_no_spread_scores_one_half_and_untagged_tracks_stay_uncovered(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    tag(repo, ids, {"Smooth Cafe": {"calm": 0.3}, "Garage Band": {"calm": 0.3}}, head="moodtheme")
    scorer = StandardisedTagScorer(StoredTagScorer(repo))
    pool = [ids["Smooth Cafe"], ids["Lullaby"], ids["Garage Band"]]
    scores, covered = scorer.scores_with_coverage(pool, "moodtheme", ["calm", "dark"])
    assert covered.tolist() == [True, False, True]
    assert scores["calm"].tolist() == pytest.approx([0.5, 0.0, 0.5])
    assert scores["dark"].tolist() == [0.0, 0.0, 0.0]
    nothing = scorer.scores_with_coverage([ids["Lullaby"]], "genre", ["jazz"])
    assert nothing[0]["jazz"].tolist() == [0.0] and not nothing[1].any()
    empty = scorer.scores_with_coverage([], "genre", ["jazz"])
    assert empty[0]["jazz"].tolist() == [] and empty[1].tolist() == []


# -- licence ------------------------------------------------------------------------------------


def test_rows_of_a_version_that_is_not_allowed_are_neither_covered_nor_counted(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    tag(repo, ids, {"Smooth Cafe": {"jazz": 0.9}, "Garage Band": {"jazz": 0.1}})
    tag(repo, ids, {"Lullaby": {"jazz": 1.0}}, version=BAD)
    pool = [ids["Smooth Cafe"], ids["Garage Band"], ids["Lullaby"]]

    gated = StandardisedTagScorer(StoredTagScorer(repo, {"genre": GOOD}))
    scores, covered = gated.scores_with_coverage(pool, "genre", ["jazz"])
    assert covered.tolist() == [True, True, False]
    assert scores["jazz"].tolist() == pytest.approx([ONE_SIGMA, 1 - ONE_SIGMA, 0.0])

    # Without a mapping every row counts, so the third track enters the statistics.
    open_ = StandardisedTagScorer(StoredTagScorer(repo))
    scores, covered = open_.scores_with_coverage(pool, "genre", ["jazz"])
    assert covered.all()
    assert scores["jazz"].tolist() == pytest.approx(
        [catalog_score([0.9, 0.1, 1.0], i) for i in range(3)]
    )


@pytest.mark.parametrize("allowed", [{}, {"genre": None}, {"moodtheme": "mood@1"}])
def test_a_set_without_an_allowed_version_is_skipped_without_a_query(
    repo: CatalogRepository,
    ids: dict[str, int],
    allowed: dict[str, str | None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tag(repo, ids, {"Smooth Cafe": {"jazz": 0.9}})

    def fail(*args: object) -> None:
        raise AssertionError("the statistics must not be read")

    monkeypatch.setattr(repo, "tag_prob_moments", fail)
    monkeypatch.setattr(repo, "tag_probs_signature", fail)
    scorer = StandardisedTagScorer(StoredTagScorer(repo, allowed))
    scores, covered = scorer.scores_with_coverage([ids["Smooth Cafe"]], "genre", ["jazz"])
    assert scores["jazz"].tolist() == [0.0] and not covered.any()


# -- the cache ----------------------------------------------------------------------------------


def test_statistics_are_cached_until_the_rows_change(
    repo: CatalogRepository, ids: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    cafe, band, lullaby = two_tagged(repo, ids)
    calls: list[tuple[str, str | None]] = []
    original = repo.tag_prob_moments

    def spy(head: str, model_version: str | None = None):  # noqa: ANN202
        calls.append((head, model_version))
        return original(head, model_version)

    monkeypatch.setattr(repo, "tag_prob_moments", spy)
    scorer = StandardisedTagScorer(StoredTagScorer(repo, {"genre": GOOD, "moodtheme": "mood@1"}))
    first = scorer.scores([cafe, band], "genre", ["jazz"])["jazz"]
    scorer.scores([band, lullaby], "genre", ["jazz", "rock"])
    scorer.scores([cafe], "genre", ["blues"])
    assert calls == [("genre", GOOD)]

    # Another head changes: this head's statistics are still current.
    tag(repo, ids, {"Lullaby": {"calm": 0.4}}, head="moodtheme", version="mood@1")
    scorer.scores([cafe], "genre", ["jazz"])
    assert calls == [("genre", GOOD)]
    scorer.scores([lullaby], "moodtheme", ["calm"])
    assert calls == [("genre", GOOD), ("moodtheme", "mood@1")]

    # A third track is tagged: recomputed.
    tag(repo, ids, {"Lullaby": {"jazz": 0.5}})
    again = scorer.scores([cafe, band, lullaby], "genre", ["jazz"])["jazz"]
    assert calls[-1] == ("genre", GOOD) and len(calls) == 3
    assert again.tolist() == pytest.approx([catalog_score([0.9, 0.1, 0.5], i) for i in range(3)])
    assert again[0] != pytest.approx(first[0])

    # Probabilities replaced in place (same rows count): recomputed too.
    tag(repo, ids, {"Garage Band": {"jazz": 0.3}})
    replaced = scorer.scores([cafe, band, lullaby], "genre", ["jazz"])["jazz"]
    assert len(calls) == 4
    assert replaced.tolist() == pytest.approx([catalog_score([0.9, 0.3, 0.5], i) for i in range(3)])


# -- with the zero-shot fallback ----------------------------------------------------------------


def test_the_composite_still_asks_zero_shot_only_for_uncovered_tracks(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    cafe, band, lullaby = two_tagged(repo, ids)
    seen: list[list[int]] = []

    class Spy:
        def scores(self, track_ids, label_set, labels):  # noqa: ANN001, ANN202
            seen.append(list(track_ids))
            return {label: np.full(len(track_ids), 0.25) for label in labels}

    composite = CompositeTagScorer(StandardisedTagScorer(StoredTagScorer(repo)), Spy())
    scores = composite.scores([lullaby, cafe, band], "genre", ["jazz"])["jazz"]
    assert seen == [[lullaby]]
    assert scores.tolist() == pytest.approx([0.25, ONE_SIGMA, 1 - ONE_SIGMA])

    seen.clear()
    tag(repo, ids, {"Lullaby": {"jazz": 0.5}})
    composite.scores([lullaby, cafe, band], "genre", ["jazz"])
    assert seen == []  # everything tagged: zero-shot is not consulted


# -- filter-only search without the text model --------------------------------------------------


class Loader:
    """An embedder loader that stands for 'torch is not installed'."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> MapEmbedder:
        self.calls += 1
        raise RuntimeError("text search needs the ml extra (torch is not installed)")


def tag_everything(
    repo: CatalogRepository,
    ids: dict[str, int],
    head: str,
    label: str,
    *,
    skip: tuple[str, ...] = (),
    version: str = GOOD,
) -> dict[str, float]:
    """Every track (except ``skip``) gets a distinct probability for ``label``."""
    probs = {}
    for n, title in enumerate(ids):
        if title not in skip:
            probs[title] = 0.05 + 0.04 * n
            repo.set_tag_probs(ids[title], head, "head", version, {label: probs[title]})
    return probs


def service_with(repo: CatalogRepository, loader: Loader, allowed: dict[str, str | None]):  # noqa: ANN201
    return SearchService(
        repo, make_settings(), embedder_loader=loader, stored_tags=StoredTagScorer(repo, allowed)
    )


@pytest.mark.parametrize(
    ("head", "label", "filters"),
    [
        ("genre", "jazz", {"genres": ("jazz",)}),
        ("moodtheme", "calm", {"moods": ("calm",)}),
    ],
)
def test_filter_only_search_ranks_by_stored_tags_without_loading_the_model(
    repo: CatalogRepository,
    ids: dict[str, int],
    head: str,
    label: str,
    filters: dict[str, tuple[str, ...]],
) -> None:
    probs = tag_everything(repo, ids, head, label)
    loader = Loader()
    service = service_with(repo, loader, {head: GOOD})
    result = service.search(
        SearchRequest("", SearchFilters(max_risk="unknown", **filters), limit=50)
    )
    assert loader.calls == 0 and not service.embedder_loaded
    assert len(result.items) == len(ids)
    by_probability = sorted(probs, key=lambda title: -probs[title])
    assert [i.title for i in result.items] == by_probability  # standardised, same order
    values = list(probs.values())
    for item in result.items:
        expected = catalog_score(values, list(probs).index(item.title))
        assert item.breakdown["tags"]["raw"] == pytest.approx(expected)
        assert item.top_tags[0].score == pytest.approx(expected)


def test_a_track_that_cannot_be_embedded_does_not_need_the_model(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    tag_everything(repo, ids, "genre", "jazz", skip=("Unembedded Tune",))
    loader = Loader()
    service = service_with(repo, loader, {"genre": GOOD})
    result = service.search(
        SearchRequest("", SearchFilters(genres=("jazz",), max_risk="unknown"), limit=50)
    )
    assert loader.calls == 0
    untagged = next(i for i in result.items if i.title == "Unembedded Tune")
    assert untagged.breakdown["tags"]["raw"] == 0.0


def test_an_embedded_track_without_allowed_tags_needs_the_model(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    tag_everything(repo, ids, "genre", "jazz", skip=("Lullaby",))
    loader = Loader()
    request = SearchRequest("", SearchFilters(genres=("jazz",), max_risk="unknown"), limit=50)
    with pytest.raises(RuntimeError, match="ml extra"):
        service_with(repo, loader, {"genre": GOOD}).search(request)
    assert loader.calls == 1


def test_tags_of_a_version_that_is_not_allowed_need_the_model(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    tag_everything(repo, ids, "genre", "jazz", version=BAD)
    loader = Loader()
    request = SearchRequest("", SearchFilters(genres=("jazz",), max_risk="unknown"), limit=50)
    with pytest.raises(RuntimeError, match="ml extra"):
        service_with(repo, loader, {"genre": GOOD}).search(request)
    assert loader.calls == 1


def test_a_request_for_a_genre_and_a_mood_needs_the_model_when_one_set_is_missing(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    tag_everything(repo, ids, "genre", "jazz")  # no moodtheme rows at all
    loader = Loader()
    service = service_with(repo, loader, {"genre": GOOD, "moodtheme": "mood@1"})
    request = SearchRequest(
        "", SearchFilters(genres=("jazz",), moods=("calm",), max_risk="unknown"), limit=50
    )
    with pytest.raises(RuntimeError, match="ml extra"):
        service.search(request)
    assert loader.calls == 1

    # With a working embedder the mood falls back to zero-shot, the genre stays stored.
    embedder = MapEmbedder(QUERY_TEXTS)
    working = SearchService(
        repo,
        make_settings(),
        embedder_loader=lambda: embedder,
        stored_tags=StoredTagScorer(repo, {"genre": GOOD, "moodtheme": "mood@1"}),
    )
    assert working.search(request).items
    assert len(embedder.calls) == 1 and "Calm music" in embedder.calls[0]
