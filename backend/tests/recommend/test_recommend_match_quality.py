"""``SearchResult.match``: the raw top cosine of a text search and the weak-match verdict."""

from __future__ import annotations

import numpy as np
import pytest
from recommend_support import (
    AXES,
    MODEL_ID,
    QUERY_TEXTS,
    MapEmbedder,
    axis,
    make_service,
    make_settings,
)

from mcrar.catalog import CatalogRepository
from mcrar.recommend import SearchFilters, SearchRequest, SearchResult, SearchService
from mcrar.recommend.results import MatchQuality
from mcrar.recommend.service import WEAK_COSINE_DEFAULTS

pytestmark = pytest.mark.usefixtures("ids")  # fills the catalog

TEXT = "tense hallway"  # names no genre, mood or scene, so only the text term is active
OFF_TOPIC = "zzz quirk"  # points away from every track (all axes negative): every cosine < 0


def search(service: SearchService, text: str | None = TEXT, **filters: object) -> SearchResult:
    return service.search(SearchRequest(text=text, filters=SearchFilters(**filters), limit=50))


def true_top(
    repo: CatalogRepository, vector: np.ndarray, allowed: list[int] | None = None
) -> float:
    """The highest raw cosine of ``vector`` over the embedded tracks (optionally only some)."""
    ids, matrix = repo.load_embeddings(MODEL_ID)
    cosines = matrix @ (vector / np.linalg.norm(vector))
    return float(
        max(c for i, c in zip(ids, cosines, strict=True) if allowed is None or i in allowed)
    )


def off_topic_service(repo: CatalogRepository, **search_settings: object):
    away = -sum((axis(name) for name in AXES), np.zeros(8, dtype=np.float32))
    return make_service(repo, MapEmbedder({**QUERY_TEXTS, OFF_TOPIC: away}), **search_settings)


def test_top_cosine_is_the_raw_maximum_not_the_normalised_score(repo: CatalogRepository) -> None:
    service, _ = make_service(repo)
    result = search(service)
    assert result.items[0].score == pytest.approx(1.0)  # normalised: 1.0 for the top hit
    assert result.match.top_cosine == pytest.approx(true_top(repo, axis("stealth")), abs=1e-6)
    assert result.match.top_cosine < 1.0
    assert result.match.weak is False
    assert result.to_dict()["match"] == {"top_cosine": result.match.top_cosine, "weak": False}


def test_top_cosine_covers_only_the_tracks_the_filters_let_through(
    repo: CatalogRepository,
) -> None:
    service, _ = make_service(repo)
    vocal = repo.filter_track_ids(vocal="vocal")
    result = search(service, vocal="vocal")
    unfiltered = search(service).match.top_cosine
    assert result.match.top_cosine == pytest.approx(
        true_top(repo, axis("stealth"), vocal), abs=1e-6
    )
    assert result.match.top_cosine < unfiltered  # the best stealth tracks are instrumental


def test_a_weak_text_search_is_flagged_with_the_embedders_default_threshold(
    repo: CatalogRepository,
) -> None:
    service, _ = off_topic_service(repo)
    result = search(service, OFF_TOPIC)
    assert WEAK_COSINE_DEFAULTS["clap"] == 0.40
    assert WEAK_COSINE_DEFAULTS["muq-mulan"] == 0.40
    assert "glap" not in WEAK_COSINE_DEFAULTS  # its cosines carry no signal (all near 0)
    assert result.items  # something was ranked, only badly
    assert result.match.top_cosine is not None and result.match.top_cosine < 0.40
    assert result.match.weak is True


@pytest.mark.parametrize(("offset", "weak"), [(0.001, True), (0.0, False), (-0.001, False)])
def test_weak_means_the_top_cosine_is_below_the_threshold(
    repo: CatalogRepository, offset: float, weak: bool
) -> None:
    top = search(make_service(repo)[0]).match.top_cosine
    assert top is not None
    service, _ = make_service(repo, weak_cosine=min(top + offset, 1.0))
    assert search(service).match.weak is weak


def test_the_setting_overrides_the_default_in_both_directions(repo: CatalogRepository) -> None:
    lenient, _ = off_topic_service(repo, weak_cosine=0.0)
    assert search(lenient, OFF_TOPIC).match.weak is True  # negative cosines are below even 0
    strict, _ = make_service(repo, weak_cosine=1.0)
    assert search(strict).match.weak is True  # the best match is still under 1.0
    default, _ = make_service(repo)
    assert search(default).match.weak is False  # the clap default is 0.40


def test_a_filter_only_search_has_no_match_quality(repo: CatalogRepository) -> None:
    service, _ = make_service(repo)
    result = search(service, None, vocal="vocal")
    assert result.items
    assert result.match == MatchQuality(top_cosine=None, weak=False)
    assert result.to_dict()["match"] == {"top_cosine": None, "weak": False}


def test_a_text_search_that_ranks_nothing_is_weak_without_a_top_cosine(
    repo: CatalogRepository,
) -> None:
    service, _ = make_service(repo)
    result = search(service, TEXT, sources=("nowhere",))
    assert result.items == [] and result.total_candidates == 0
    assert result.match == MatchQuality(top_cosine=None, weak=True)


def test_an_embedder_without_a_default_threshold_is_never_weak(repo: CatalogRepository) -> None:
    model_id = "mystery@1"
    index_ids, matrix = repo.load_embeddings(MODEL_ID)
    for track_id, vector in zip(index_ids, matrix, strict=True):
        repo.set_embedding(int(track_id), model_id, vector)
    embedder = MapEmbedder(QUERY_TEXTS, model_id=model_id)

    def service_for(**search_settings: object) -> SearchService:
        return SearchService(
            repo,
            make_settings(**search_settings),
            embedder_loader=lambda: embedder,
            model_id=model_id,
        )

    service = service_for()
    assert service.weak_cosine() is None
    result = search(service)
    assert result.items and result.match.top_cosine is not None and not result.match.weak
    assert search(service, TEXT, sources=("nowhere",)).match == MatchQuality(None, False)
    assert search(service_for(weak_cosine=1.0)).match.weak is True  # a setting still applies


def test_the_match_describes_the_final_relaxed_attempt(repo: CatalogRepository) -> None:
    service, _ = make_service(repo, min_results=5)
    result = search(service, TEXT, duration_min_s=100_000)  # one track left: relaxed away
    assert result.relaxed and result.items
    assert result.match.top_cosine == pytest.approx(true_top(repo, axis("stealth")), abs=1e-6)
    assert result.match.weak is False
