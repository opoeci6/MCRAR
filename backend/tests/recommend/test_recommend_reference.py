"""Search by a reference song (M10): ranking by audio-audio cosine, blended with a text query."""

from __future__ import annotations

import math

import numpy as np
import pytest
from recommend_support import MODEL_ID, QUERY_TEXTS, MapEmbedder, axis, make_service

from mcrar.catalog import CatalogRepository
from mcrar.recommend import SearchError, SearchFilters, SearchRequest, SearchResult, SearchService
from mcrar.recommend.explain import REFERENCE_BANDS
from mcrar.recommend.query import ReferenceQuery
from mcrar.recommend.results import MatchQuality, ReferenceInfo

LABEL = "Shadow Walk — Ada"
# A query the rule parser reads as plain text: no genre/mood hint and no tempo or energy words,
# so the semantic and reference terms are the only active ones.
TEXT = "sunshine melody"


def service_for(repo: CatalogRepository, **search: object) -> tuple[SearchService, MapEmbedder]:
    return make_service(repo, MapEmbedder({**QUERY_TEXTS, TEXT: axis("happy")}), **search)


def titles(result: SearchResult) -> list[str | None]:
    return [item.title for item in result.items]


def run(
    service: SearchService,
    reference: ReferenceQuery | None,
    text: str | None = None,
    filters: SearchFilters | None = None,
    **kwargs: object,
) -> SearchResult:
    request = SearchRequest(
        text=text, filters=filters or SearchFilters(), reference=reference, limit=50, **kwargs
    )  # type: ignore[arg-type]
    return service.search(request)


def neighbours(repo: CatalogRepository, ids: dict[str, int], title: str) -> list[str]:
    """Every other embedded track by cosine to ``title``'s embedding, best first."""
    by_id = {v: k for k, v in ids.items()}
    index_ids, matrix = repo.load_embeddings(MODEL_ID)
    cosines = matrix @ repo.get_embedding(ids[title], MODEL_ID)
    order = np.lexsort((index_ids, -cosines))
    return [by_id[int(i)] for i in index_ids[order] if int(i) != ids[title]]


# -- the reference of a catalog track -----------------------------------------------------------


def test_a_track_reference_ranks_its_neighbours_and_leaves_itself_out(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, embedder = service_for(repo)
    ref = service.reference_for_track(ids["Shadow Walk"])
    assert (ref.kind, ref.track_id, ref.label, ref.weight) == (
        "track",
        ids["Shadow Walk"],
        LABEL,
        0.5,
    )
    result = run(service, ref)
    assert titles(result) == neighbours(repo, ids, "Shadow Walk")
    assert titles(result)[:2] == ["Quiet Vents", "Night Heist"]
    assert embedder.calls == []  # a reference alone needs no text model


def test_the_label_is_the_title_alone_without_an_artist(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = service_for(repo)
    assert service.reference_for_track(ids["Local Ambient"]).label == "Local Ambient"


def test_a_track_without_an_embedding_for_the_model_cannot_be_a_reference(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = service_for(repo)
    with pytest.raises(SearchError, match="Re-embed missing tracks") as info:
        service.reference_for_track(ids["Unembedded Tune"])
    assert "mcrar embed" in str(info.value) and MODEL_ID in str(info.value)


def test_an_unknown_track_is_a_lookup_error(repo: CatalogRepository, ids: dict[str, int]) -> None:
    service, _ = service_for(repo)
    with pytest.raises(LookupError, match="no track with id 9999"):
        service.reference_for_track(9999)


def test_a_reference_alone_does_not_fall_back_to_the_safest_licensed_tracks(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = service_for(repo, pool_size=5)
    result = run(service, service.reference_for_track(ids["Shadow Walk"]))
    # the five nearest, whatever their licence (Creeping Dread is amber, Red Alert is red)
    assert titles(result) == neighbours(repo, ids, "Shadow Walk")[:5]
    assert {item.risk for item in result.items} > {"green"}


def test_an_upload_reference_does_not_exclude_any_track(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = service_for(repo)
    ref = ReferenceQuery(axis("stealth"), "my song.wav", "upload")
    result = run(service, ref)
    assert titles(result)[0] == "Shadow Walk" and len(result.items) == 20
    assert result.reference == ReferenceInfo("upload", None, "my song.wav", 0.5)


def test_a_vector_of_the_wrong_size_is_a_search_error(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = service_for(repo)
    ref = ReferenceQuery(np.ones(5, dtype=np.float32), "x.wav", "upload")
    with pytest.raises(SearchError, match="reference song's embedding does not fit"):
        run(service, ref)
    with pytest.raises(SearchError, match="reference song's embedding does not fit"):
        run(service, ref, text="tense stealth level")


@pytest.mark.parametrize("weight", [-0.1, 1.5, math.nan])
def test_the_reference_weight_must_be_between_0_and_1(weight: float) -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        ReferenceQuery(axis("stealth"), "x", "upload", weight=weight)


# -- blended with text ---------------------------------------------------------------------------


def test_the_blend_weight_moves_the_ranking_from_the_text_to_the_reference(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = service_for(repo)
    text = TEXT
    text_only = [t for t in titles(run(service, None, text)) if t != "Shadow Walk"]
    ref_only = titles(run(service, service.reference_for_track(ids["Shadow Walk"])))

    def blend(weight: float) -> SearchResult:
        return run(service, service.reference_for_track(ids["Shadow Walk"], weight), text)

    assert titles(blend(0.0)) == text_only
    assert titles(blend(1.0)) == ref_only
    middle = blend(0.5)
    assert titles(middle)[0] not in (text_only[0], ref_only[0])
    assert middle.items[0].breakdown["semantic"]["weight"] == pytest.approx(0.5)
    assert middle.items[0].breakdown["reference"]["weight"] == pytest.approx(0.5)
    assert "Shadow Walk" not in titles(middle)


def test_the_pool_is_the_union_of_both_top_lists_and_every_track_has_both_cosines(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = service_for(repo, pool_size=3)
    text_top = titles(run(service, None, TEXT))
    ref_top = titles(run(service, service.reference_for_track(ids["Shadow Walk"])))
    assert len(text_top) == len(ref_top) == 3
    result = run(service, service.reference_for_track(ids["Shadow Walk"]), TEXT)
    assert set(titles(result)) == set(text_top) | set(ref_top)
    assert len(result.items) == 6
    for item in result.items:  # each of the six has both scaled terms
        assert item.breakdown["semantic"]["raw"] is not None
        assert item.breakdown["reference"]["raw"] is not None
    # a track only the text found is scored on the reference too: the best reference match
    # gets 1.0 and the worst of the pool 0.0
    raws = [item.breakdown["reference"]["raw"] for item in result.items]
    assert max(raws) == 1.0 and min(raws) == 0.0


# -- filters, relaxation, breakdown, echo, explanation ------------------------------------------


def test_filters_still_apply_with_a_reference(repo: CatalogRepository, ids: dict[str, int]) -> None:
    service, _ = service_for(repo)
    ref = service.reference_for_track(ids["Shadow Walk"])
    result = run(service, ref, filters=SearchFilters(max_risk="green", vocal="instrumental"))
    assert result.items
    assert {item.risk for item in result.items} == {"green"}
    assert "Creeping Dread" not in titles(result) and "Red Alert" not in titles(result)


def test_relaxation_still_runs_with_a_reference(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = service_for(repo)
    ref = service.reference_for_track(ids["Shadow Walk"])
    filters = SearchFilters(duration_max_s=5, sources=("jamendo",))
    result = run(service, ref, filters=filters)
    assert result.relaxed == ["Relaxed the duration limit (≤ 5 s)"]
    assert titles(result)[0] == "Quiet Vents"


def test_the_breakdown_has_a_reference_term_and_the_active_weights_sum_to_one(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = service_for(repo)
    ref = service.reference_for_track(ids["Shadow Walk"])
    only = run(service, ref).items[0].breakdown
    assert only["reference"] == {"raw": 1.0, "weight": 1.0, "contribution": 1.0}
    assert only["semantic"] == {"raw": None, "weight": 0.0, "contribution": 0.0}
    both = run(service, ref, TEXT).items[0].breakdown
    assert sum(term["weight"] for term in both.values()) == pytest.approx(1.0)
    assert both["semantic"]["weight"] > 0 and both["reference"]["weight"] > 0
    plain = run(service, None, TEXT).items[0].breakdown
    assert plain["reference"] == {"raw": None, "weight": 0.0, "contribution": 0.0}


def test_the_result_echoes_the_reference_without_its_vector(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = service_for(repo)
    result = run(service, service.reference_for_track(ids["Shadow Walk"], 0.25))
    assert result.reference == ReferenceInfo("track", ids["Shadow Walk"], LABEL, 0.25)
    assert result.to_dict()["reference"] == {
        "kind": "track",
        "track_id": ids["Shadow Walk"],
        "label": LABEL,
        "weight": 0.25,
    }
    assert run(service, None, "calm").reference is None
    assert run(service, None, "calm").to_dict()["reference"] is None


def test_the_explanation_says_how_close_the_track_sounds(
    repo: CatalogRepository, ids: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Bands that split the synthetic catalog's cosines (the real ones are measured on audio).
    monkeypatch.setitem(REFERENCE_BANDS, "clap", (0.85, 0.70))
    service, _ = service_for(repo)
    result = run(service, service.reference_for_track(ids["Shadow Walk"]))
    by_title = {item.title: item.explanation for item in result.items}
    assert by_title["Quiet Vents"].startswith("Sounds close to “Shadow Walk — Ada” · ")
    assert by_title["Creeping Dread"].startswith("Sounds similar to “Shadow Walk — Ada”")
    assert by_title["Lullaby"].startswith("Loosely like “Shadow Walk — Ada”")
    assert "Matches your filters" not in by_title["Lullaby"]
    both = run(service, service.reference_for_track(ids["Shadow Walk"]), TEXT)
    explanation = both.items[0].explanation
    assert explanation is not None
    assert explanation.index(f'match for "{TEXT}"') < explanation.index("“Shadow Walk — Ada”")
    quiet = run(service, service.reference_for_track(ids["Shadow Walk"]), explain=False)
    assert quiet.items[0].explanation is None


def test_a_model_without_bands_gets_no_strength_word(
    repo: CatalogRepository, ids: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delitem(REFERENCE_BANDS, "clap")
    service, _ = service_for(repo)
    result = run(service, service.reference_for_track(ids["Shadow Walk"]))
    assert all(item.explanation.startswith(f"Sounds like “{LABEL}”") for item in result.items)


def test_there_is_no_weak_match_notice_for_a_reference_alone(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = service_for(repo, weak_cosine=0.9999)
    ref = service.reference_for_track(ids["Shadow Walk"])
    assert run(service, ref).match == MatchQuality()
    mixed = run(service, ref, TEXT)
    assert mixed.match.top_cosine is not None and mixed.match.weak  # the text decides


def test_tracks_without_an_embedding_are_reported_as_not_found_by_the_reference(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = service_for(repo)
    result = run(service, service.reference_for_track(ids["Shadow Walk"]))
    assert result.unembedded_count == 1
    assert any("reference search cannot find them" in note for note in result.notes)
