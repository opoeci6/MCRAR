"""SearchService end to end on the synthetic catalog: retrieval, ranking, paging, caches."""

from __future__ import annotations

import json

import numpy as np
import pytest
from recommend_support import MODEL_ID, QUERY_TEXTS, MapEmbedder, axis, make_service, make_settings

from mcrar.catalog import CatalogRepository, TrackRecord, open_path
from mcrar.recommend import SearchError, SearchFilters, SearchRequest, SearchResult, SearchService


def titles(result: SearchResult) -> list[str | None]:
    return [item.title for item in result.items]


def search(service: SearchService, text: str | None = None, **kwargs: object) -> SearchResult:
    filters = kwargs.pop("filters", SearchFilters())
    return service.search(SearchRequest(text=text, filters=filters, **kwargs))  # type: ignore[arg-type]


def test_semantic_order_follows_the_embeddings(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = make_service(repo)
    result = search(service, "tense stealth level", limit=50)
    ids_to_title = {v: k for k, v in ids.items()}
    index_ids, matrix = repo.load_embeddings(MODEL_ID)
    cosines = matrix @ axis("stealth")
    expected = [ids_to_title[int(i)] for i in index_ids[np.lexsort((index_ids, -cosines))]]
    assert titles(result) == expected
    assert titles(result)[:3] == ["Shadow Walk", "Quiet Vents", "Night Heist"]
    scores = [item.score for item in result.items]
    assert scores == sorted(scores, reverse=True)
    assert result.model_id == MODEL_ID
    assert result.items[0].breakdown["semantic"]["raw"] == 1.0
    assert result.items[-1].breakdown["semantic"]["raw"] == 0.0


@pytest.mark.parametrize(
    ("text", "first"),
    [
        ("epic battle", "Epic Quest"),
        ("happy upbeat tune", "Sunny Day"),
        ("calm ambient pad", "Lullaby"),
    ],
)
def test_other_queries_find_their_tracks(
    repo: CatalogRepository, ids: dict[str, int], text: str, first: str
) -> None:
    service, _ = make_service(repo)
    assert first in titles(search(service, text))[:2]  # energy/tag terms may swap close tracks


def test_unembedded_tracks_are_counted_skipped_and_reported(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = make_service(repo)
    result = search(service, "tense stealth level", limit=50)
    assert result.unembedded_count == 1
    assert "Unembedded Tune" not in titles(result)
    assert any("mcrar embed" in n and "1 matching" in n for n in result.notes)
    # Only tracks passing the filters are counted.
    narrowed = search(service, "tense stealth level", filters=SearchFilters(vocal="vocal"))
    assert narrowed.unembedded_count == 0 and narrowed.notes == []


@pytest.mark.parametrize(
    ("max_risk", "allowed"),
    [("green", {"green"}), ("amber", {"green", "amber"}), ("red", {"green", "amber", "red"})],
)
def test_max_risk_in_the_service(
    repo: CatalogRepository, ids: dict[str, int], max_risk: str, allowed: set[str]
) -> None:
    service, _ = make_service(repo)
    result = search(
        service, "tense stealth level", filters=SearchFilters(max_risk=max_risk), limit=50
    )  # type: ignore[arg-type]
    assert {item.risk for item in result.items} == allowed
    if max_risk == "amber":
        assert "Red Alert" not in titles(result)  # a red track never shows with max_risk=amber
    loose = search(service, "tense stealth level", limit=50)
    assert {"red", "unknown"} <= {item.risk for item in loose.items}


def test_text_constraints_filter_and_are_stripped(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, embedder = make_service(repo)
    result = search(service, "tense stealth level, no vocals, commercial use", limit=50)
    assert result.parsed.semantic_text == "tense stealth level"
    assert {i.risk for i in result.items} == {"green"}
    vocal = {
        t.vocal_instrumental for t in repo.get_tracks(i.track_id for i in result.items).values()
    }
    assert vocal == {"instrumental"}
    assert ["tense stealth level"] in embedder.calls  # the constraint phrases were not embedded


def test_sources_and_durations_and_bpm_filters(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = make_service(repo)
    local = search(service, "epic battle", filters=SearchFilters(sources=("local",)), limit=50)
    assert {i.source for i in local.items} == {"local"}
    short = search(service, "epic battle", filters=SearchFilters(duration_max_s=100), limit=50)
    assert set(titles(short)) == {"Chip Hero", "Mystery Box", "Local Ambient"}  # unknown passes
    bpm = search(service, "epic battle", filters=SearchFilters(bpm_min=140, bpm_max=155), limit=50)
    assert {i.title for i in bpm.items} == {
        "Party Time",
        "Boss Fight",
        "Garage Band",
        "Chip Hero",
        "Mystery Box",
    }


def test_filter_only_search_never_loads_the_model(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    loads: list[int] = []
    embedder = MapEmbedder(QUERY_TEXTS)
    service = SearchService(
        repo,
        make_settings(),
        embedder_loader=lambda: loads.append(1) or embedder,  # type: ignore[func-returns-value]
    )
    result = search(service, "", filters=SearchFilters(bpm_min=120, bpm_max=130, vocal="vocal"))
    assert not loads and not service.embedder_loaded
    assert result.parsed.semantic_text is None
    assert {i.title for i in result.items} == {"Sunny Day", "Happy Feet", "Red Alert"}
    # No preference to rank by: every score is 0 and the order is licence risk, then track id.
    assert [i.score for i in result.items] == [0.0, 0.0, 0.0]
    assert [i.title for i in result.items] == ["Sunny Day", "Happy Feet", "Red Alert"]
    for item in result.items:
        assert item.breakdown["semantic"] == {"raw": None, "weight": 0.0, "contribution": 0.0}
        assert item.top_tags == []  # no stored tags, and zero-shot would need the model


def test_filter_only_text_that_is_all_constraints(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, embedder = make_service(repo)
    result = search(service, "under 90 bpm, instrumental")
    assert embedder.calls == []
    assert {i.title for i in result.items} >= {"Creeping Dread", "Lullaby", "Ambient Pad"}
    assert all(i.bpm is None or i.bpm <= 90 or i.title == "Mystery Box" for i in result.items)


def test_filter_only_pool_keeps_the_safest_tracks_unless_a_preference_can_rank(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = make_service(repo, pool_size=3)
    capped = search(service, "", filters=SearchFilters(max_risk="green"), limit=50)
    assert capped.total_candidates == 3
    assert [i.track_id for i in capped.items] == sorted(ids.values())[:3]
    ranked = search(service, "", filters=SearchFilters(genres=("jazz",)), limit=50)
    assert ranked.total_candidates == len(ids)  # not capped: the tag term orders them all
    assert titles(ranked)[0] == "Smooth Cafe"


def test_contributions_sum_to_the_score_for_every_kind_of_query(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = make_service(repo)
    requests = [
        SearchRequest("tense stealth level", limit=50),
        SearchRequest("calm dark jazz under 100 bpm", limit=50),
        SearchRequest("epic battle", SearchFilters(moods=("epic",)), limit=50),
        SearchRequest("slow calm ambient pad", limit=50),
        SearchRequest("", SearchFilters(genres=("rock",), moods=("dark",)), limit=50),
        SearchRequest("", SearchFilters(vocal="instrumental"), limit=50),
    ]
    for request in requests:
        result = service.search(request)
        assert result.items
        for item in result.items:
            parts = item.breakdown
            assert sum(p["contribution"] for p in parts.values()) == pytest.approx(item.score)
            assert sum(p["weight"] for p in parts.values()) in (pytest.approx(1.0), 0.0)


def test_only_active_terms_carry_weight(repo: CatalogRepository, ids: dict[str, int]) -> None:
    service, _ = make_service(repo)
    text_only = search(service, "tense stealth level").items[0].breakdown
    assert {k: v["weight"] for k, v in text_only.items()} == {
        "semantic": 1.0,
        "reference": 0.0,
        "tags": 0.0,
        "bpm": 0.0,
        "energy": 0.0,
    }
    mixed = search(service, "calm dark jazz under 100 bpm").items[0].breakdown
    weights = {k: v["weight"] for k, v in mixed.items()}
    assert weights["bpm"] == 0.0  # a range is a filter, not a target
    assert weights["semantic"] == pytest.approx(0.6 / 0.9)
    assert weights["tags"] == pytest.approx(0.2 / 0.9)
    assert weights["energy"] == pytest.approx(0.1 / 0.9)
    tempo = search(service, "slow dark jazz").items[0].breakdown
    assert tempo["bpm"]["weight"] == pytest.approx(0.1 / 0.9)  # "slow" -> a 75 BPM target
    assert tempo["energy"]["weight"] == 0.0
    assert sum(v["weight"] for v in tempo.values()) == pytest.approx(1.0)


def test_weights_come_from_the_settings(repo: CatalogRepository, ids: dict[str, int]) -> None:
    service = SearchService(
        repo,
        make_settings(weights={"semantic": 1.0, "tags": 3.0, "bpm": 0.0, "energy": 0.0}),
        embedder_loader=lambda: MapEmbedder(QUERY_TEXTS),
    )
    weights = {
        k: v["weight"]
        for k, v in search(service, "epic battle", filters=SearchFilters(moods=("epic",)))
        .items[0]
        .breakdown.items()
    }
    assert weights["semantic"] == pytest.approx(0.25) and weights["tags"] == pytest.approx(0.75)


def test_equal_scores_break_ties_by_track_id(repo: CatalogRepository, ids: dict[str, int]) -> None:
    service, _ = make_service(repo)
    result = search(service, "", filters=SearchFilters(max_risk="green"), limit=50)
    assert [i.track_id for i in result.items] == sorted(i.track_id for i in result.items)


def test_artist_cap_demotes_and_paging_follows_the_capped_order(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    uncapped, _ = make_service(repo)
    capped, _ = make_service(repo, max_per_artist=2)
    everything = titles(search(uncapped, "tense stealth level", limit=50))
    result = search(capped, "tense stealth level", limit=50)
    # Ada has three tracks near the top: her third moves behind every in-cap track.
    assert titles(result) == [t for t in everything if t != "Night Heist"] + ["Night Heist"]
    assert titles(result)[:2] == ["Shadow Walk", "Quiet Vents"]
    assert result.total_candidates == len(everything)  # nothing is dropped
    first_page = search(capped, "tense stealth level", limit=10).items
    artists = [i.artist for i in first_page if i.artist]
    assert all(artists.count(a) <= 2 for a in set(artists))
    assert any(i.artist is None for i in result.items)  # "Local Ambient": never capped
    # Paging applies after the cap: consecutive pages tile the capped list.
    pages: list[str | None] = []
    for offset in range(0, 30, 4):
        pages += titles(search(capped, "tense stealth level", limit=4, offset=offset))
    assert pages == titles(result)
    assert search(capped, "tense stealth level", limit=4, offset=500).items == []


def _tracks(repo: CatalogRepository, artists: list[str | None]) -> None:
    for n, artist in enumerate(artists, start=1):
        track_id = repo.upsert_track(
            TrackRecord(
                source="local", source_id=str(n), title=f"T{n}", artist=artist, risk="green"
            )
        )
        repo.set_embedding(track_id, MODEL_ID, axis("epic", 1.0) + axis("calm", 0.05 * n))


def test_a_single_artist_catalog_still_fills_the_page(tmp_path) -> None:  # noqa: ANN001
    with open_path(tmp_path / "solo" / "catalog.db") as solo:
        _tracks(solo, ["Me"] * 10)
        service, _ = make_service(solo, max_per_artist=2)
        page = search(service, "epic battle", limit=5)
        assert len(page.items) == 5 and page.total_candidates == 10
        assert [i.title for i in page.items] == ["T1", "T2", "T3", "T4", "T5"]  # ranked order kept
        assert len(search(service, "epic battle", limit=5, offset=5).items) == 5


def test_with_three_artists_the_first_page_respects_the_cap(tmp_path) -> None:  # noqa: ANN001
    with open_path(tmp_path / "trio" / "catalog.db") as trio:
        _tracks(trio, ["A", "A", "A", "A", "B", "B", "B", "C", "C", "C"])
        service, _ = make_service(trio, max_per_artist=2)
        result = search(service, "epic battle", limit=6)
        by_artist = [i.artist for i in result.items]
        assert sorted(by_artist) == ["A", "A", "B", "B", "C", "C"]
        assert [i.title for i in result.items] == ["T1", "T2", "T5", "T6", "T8", "T9"]
        assert result.total_candidates == 10
        rest = search(service, "epic battle", limit=6, offset=6).items  # the demoted ones follow
        assert [i.title for i in rest] == ["T3", "T4", "T7", "T10"]


def test_equal_scores_are_ordered_by_licence_risk_then_track_id(tmp_path) -> None:  # noqa: ANN001
    with open_path(tmp_path / "risk" / "catalog.db") as risky:
        for n, risk in enumerate(["red", "unknown", "green", "amber", "green", "red"], start=1):
            risky.upsert_track(
                TrackRecord(source="local", source_id=str(n), title=f"T{n}", risk=risk)
            )
        service, embedder = make_service(risky)
        result = search(service, "", limit=10)  # filter-only, no preference: every score is 0
        assert [i.score for i in result.items] == [0.0] * 6
        assert [(i.title, i.risk) for i in result.items] == [
            ("T3", "green"),
            ("T5", "green"),
            ("T4", "amber"),
            ("T1", "red"),
            ("T6", "red"),
            ("T2", "unknown"),
        ]
        assert embedder.calls == []
        # The cap keeps the safest tracks, not the lowest ids.
        small, _ = make_service(risky, pool_size=3)
        capped = search(small, "", limit=10)
        assert [i.title for i in capped.items] == ["T3", "T5", "T4"]
        assert capped.total_candidates == 3


def test_unknown_vocal_flags_pass_and_the_explanation_says_so(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = make_service(repo)
    result = search(service, "", filters=SearchFilters(vocal="instrumental", sources=("local",)))
    by_title = {i.title: i for i in result.items}
    assert set(by_title) == {"Chip Hero", "Local Ambient"}  # Local Ambient has no vocal flag
    assert by_title["Local Ambient"].explanation == (
        "Matches your filters · vocals unknown · Unknown license (unknown)"
    )
    assert (
        by_title["Chip Hero"].explanation == "Matches your filters · instrumental · CC0 1.0 (green)"
    )
    everything = search(service, "", filters=SearchFilters(vocal="instrumental"), limit=50)
    assert "Mystery Box" in titles(everything) and "Sunny Day" not in titles(everything)


def test_pool_size_limits_the_candidates(repo: CatalogRepository, ids: dict[str, int]) -> None:
    service, _ = make_service(repo, pool_size=5)
    result = search(service, "tense stealth level", limit=50)
    assert result.total_candidates == 5
    assert titles(result)[:3] == ["Shadow Walk", "Quiet Vents", "Night Heist"]


def test_the_results_are_deterministic(repo: CatalogRepository, ids: dict[str, int]) -> None:
    service, _ = make_service(repo)
    first = search(service, "calm dark jazz under 100 bpm").to_dict()
    second = search(service, "calm dark jazz under 100 bpm").to_dict()
    for r in (first, second):
        r["elapsed_ms"] = 0
    assert first == second


def test_item_fields_and_json(repo: CatalogRepository, ids: dict[str, int]) -> None:
    service, _ = make_service(repo)
    result = search(service, "tense stealth level", limit=50)
    by_title = {i.title: i for i in result.items}
    quest = by_title["Epic Quest"]
    assert quest.download_url == "https://example.test/10/download"  # the licence allows it
    assert by_title["Boss Fight"].download_url is None
    assert (quest.source, quest.source_url) == ("jamendo", "https://example.test/10")
    assert (quest.bpm, quest.key, quest.mode, quest.energy) == (110, "C", "minor", 0.8)
    assert (quest.license_code, quest.risk) == ("CC BY 3.0", "green")
    assert quest.license_url and quest.attribution_text == "Epic Quest by Gus"
    assert quest.duration_s == 240 and quest.commercial_license_url is None
    data = json.loads(json.dumps(result.to_dict()))
    assert data["model_id"] == MODEL_ID and data["unembedded_count"] == 1
    assert data["parsed"]["semantic_text"] == "tense stealth level"
    assert data["items"][0]["breakdown"]["semantic"]["weight"] == 1.0
    assert set(data) >= {"items", "total_candidates", "parsed", "relaxed", "elapsed_ms", "notes"}
    assert result.elapsed_ms > 0


def test_explanations(repo: CatalogRepository, ids: dict[str, int]) -> None:
    service, _ = make_service(repo)
    result = search(
        service,
        "tense stealth level, no vocals",
        filters=SearchFilters(bpm_max=100),
        limit=3,
    )
    assert result.items[0].explanation == (
        'Close match for "tense stealth level" · 90 BPM (≤ 100 asked) · instrumental '
        "· CC BY 3.0 (green)"
    )
    calm = next(i for i in search(service, "calm", limit=50).items if i.title == "Lullaby")
    assert calm.explanation == (
        'Close match for "calm" · energy 0.10 (calm asked) · tags calm 0.97 · CC BY 3.0 (green)'
    )
    plain = search(service, "", filters=SearchFilters(vocal="vocal"), limit=1).items[0]
    assert plain.explanation == "Matches your filters · vocal · CC BY 3.0 (green)"
    quiet = search(service, "tense stealth level", explain=False, limit=2)
    assert [i.explanation for i in quiet.items] == [None, None]


def test_the_model_is_loaded_lazily_once_and_kept(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    loads: list[int] = []
    embedder = MapEmbedder(QUERY_TEXTS)

    def loader() -> MapEmbedder:
        loads.append(1)
        return embedder

    service = SearchService(repo, make_settings(), embedder_loader=loader)
    assert loads == []
    search(service, "", filters=SearchFilters(max_risk="green"))
    assert loads == []
    search(service, "epic battle")
    search(service, "calm ambient pad")
    assert loads == [1] and service.embedder_loaded
    service.close()
    assert embedder.closed and not service.embedder_loaded


def test_query_embeddings_are_cached(repo: CatalogRepository, ids: dict[str, int]) -> None:
    service, embedder = make_service(repo)
    for _ in range(3):
        search(service, "epic battle")
    search(service, "  epic   battle ")  # same text once whitespace is normalised
    search(service, "Epic Battle")  # and case: CLAP's text encoder is case-sensitive
    asked = [call for call in embedder.calls if call == ["epic battle"]]
    assert len(asked) == 1
    assert not [call for call in embedder.calls if call == ["Epic Battle"]]


def test_the_index_is_cached_and_rebuilt_when_new_embeddings_arrive(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = make_service(repo)
    before = search(service, "tense stealth level", limit=50)
    assert "Unembedded Tune" not in titles(before) and before.unembedded_count == 1
    index = service._index()
    search(service, "epic battle")
    assert service._index() is index  # nothing changed: same index object

    repo.set_embedding(ids["Unembedded Tune"], MODEL_ID, axis("stealth", 0.98) + axis("dark", 0.02))
    after = search(service, "tense stealth level", limit=50)
    assert service._index() is not index
    assert "Unembedded Tune" in titles(after) and after.unembedded_count == 0
    assert after.notes == []
    assert titles(after)[:2] in (
        ["Unembedded Tune", "Shadow Walk"],
        ["Shadow Walk", "Unembedded Tune"],
    )

    repo.set_embedding(ids["Unembedded Tune"], MODEL_ID, axis("calm"))  # re-embedded in place
    again = search(service, "tense stealth level", limit=50)
    assert titles(again).index("Unembedded Tune") > 5


def test_a_text_search_on_a_catalog_without_embeddings(tmp_path) -> None:  # noqa: ANN001
    with open_path(tmp_path / "empty" / "catalog.db") as empty:
        service, _ = make_service(empty)
        result = search(service, "epic battle")
    assert result.items == [] and result.total_candidates == 0
    assert result.notes == ["No tracks match"]


def test_a_loaded_model_that_does_not_match_the_index_is_an_error(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = make_service(repo, MapEmbedder(QUERY_TEXTS, model_id="glap@79b1301"))
    with pytest.raises(SearchError, match="glap@79b1301"):
        search(service, "epic battle")


def test_bad_requests(repo: CatalogRepository, ids: dict[str, int]) -> None:
    service, _ = make_service(repo)
    with pytest.raises(SearchError, match="limit"):
        search(service, "epic battle", limit=0)
    with pytest.raises(SearchError, match="offset"):
        search(service, "epic battle", offset=-1)
    with pytest.raises(SearchError, match="unknown genre label 'polka'"):
        search(service, "epic battle", filters=SearchFilters(genres=("polka",)))
    with pytest.raises(SearchError, match="unknown moodtheme label 'jazz'"):
        search(service, "epic battle", filters=SearchFilters(moods=("jazz",)))
