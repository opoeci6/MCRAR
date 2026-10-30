"""A search that no track can match never needs the text model (so no first-run download)."""

from __future__ import annotations

from pathlib import Path

from recommend_support import QUERY_TEXTS, MapEmbedder, make_settings

from mcrar.catalog import CatalogRepository, open_path
from mcrar.recommend import SearchFilters, SearchRequest, SearchService


def service_that_must_not_load(repo: CatalogRepository) -> SearchService:
    def loader() -> MapEmbedder:
        raise AssertionError("the embedder must not be loaded")

    return SearchService(repo, make_settings(), embedder_loader=loader)


def test_a_text_search_on_an_empty_catalog_does_not_load_the_model(tmp_path: Path) -> None:
    with open_path(tmp_path / "empty" / "catalog.db") as empty:
        service = service_that_must_not_load(empty)
        result = service.search(SearchRequest(text="epic battle"))
        assert not service.embedder_loaded
    assert result.items == [] and result.total_candidates == 0
    assert result.unembedded_count == 0 and result.relaxed == []
    assert result.notes == ["No tracks match"]
    assert result.parsed.semantic_text == "epic battle"
    assert result.match is not None and result.match.top_cosine is None


def test_filters_that_leave_no_track_do_not_load_the_model(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service = service_that_must_not_load(repo)
    filters = SearchFilters(sources=("no-such-source",))
    result = service.search(SearchRequest(text="epic battle", filters=filters))
    assert result.items == [] and result.total_candidates == 0
    assert result.notes == ["No tracks match in no-such-source"]


def test_the_model_is_still_used_when_tracks_match(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    loads: list[int] = []
    embedder = MapEmbedder(QUERY_TEXTS)

    def loader() -> MapEmbedder:
        loads.append(1)
        return embedder

    service = SearchService(repo, make_settings(), embedder_loader=loader)
    result = service.search(SearchRequest(text="epic battle"))
    assert loads == [1] and result.items
