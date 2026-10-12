"""Relaxation: duration, then BPM, then vocal; never the licence or the sources."""

from __future__ import annotations

from pathlib import Path

import pytest
from recommend_support import MODEL_ID, axis, make_service

from mcrar.catalog import CatalogRepository, TrackRecord, open_path
from mcrar.recommend import SearchFilters, SearchRequest, SearchResult, SearchService


def search(service: SearchService, text: str, **filters: object) -> SearchResult:
    return service.search(SearchRequest(text=text, filters=SearchFilters(**filters)))  # type: ignore[arg-type]


def test_nothing_is_relaxed_when_the_filters_find_results(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = make_service(repo)
    result = search(service, "epic battle under 300 seconds")
    assert result.items and result.relaxed == []


def test_duration_is_relaxed_first(repo: CatalogRepository, ids: dict[str, int]) -> None:
    service, _ = make_service(repo)
    result = search(service, "epic battle under 5 seconds", sources=("jamendo",))
    assert result.items and result.items[0].title == "Epic Quest"
    assert result.relaxed == ["Relaxed the duration limit (≤ 5 s)"]
    assert result.parsed.filters.duration_max_s == 5  # `parsed` is the query as understood


def test_a_track_of_unknown_duration_satisfies_the_limit_so_nothing_is_relaxed(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = make_service(repo)
    result = search(service, "epic battle under 5 seconds")
    assert result.relaxed == []
    assert {i.title for i in result.items} == {"Local Ambient"}
    unknown = next(i for i in result.items if i.title == "Local Ambient")
    assert unknown.explanation and "duration unknown" in unknown.explanation


def test_then_the_bpm_range_becomes_a_soft_target(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = make_service(repo)
    result = search(service, "epic battle under 5 seconds 300-310 bpm")
    assert result.relaxed == [
        "Relaxed the duration limit (≤ 5 s)",
        "Relaxed the BPM range (300-310) to a target of ~305 BPM",
    ]
    assert result.items
    assert all(i.breakdown["bpm"]["weight"] > 0 for i in result.items)  # now a soft target
    assert result.items[0].explanation and "(~305 asked)" in result.items[0].explanation


def test_a_one_sided_bpm_bound_relaxes_to_a_target_at_the_bound(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = make_service(repo)
    result = search(service, "epic battle", bpm_max=20.0)
    assert result.relaxed == ["Relaxed the BPM range (≤ 20) to a target of ~20 BPM"]
    assert result.items


def test_relaxing_stops_as_soon_as_there_are_results(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = make_service(repo)
    # Only the BPM range blocks this; the vocal filter must stay.
    result = search(service, "epic battle 300-310 bpm", vocal="instrumental")
    assert result.relaxed == ["Relaxed the BPM range (300-310) to a target of ~305 BPM"]
    assert result.items
    assert all(  # known vocal flags still match; unknown ones pass
        repo.get_track(i.track_id).vocal_instrumental in ("instrumental", None)  # type: ignore[union-attr]
        for i in result.items
    )
    assert "Sunny Day" not in {i.title for i in result.items}


def test_steps_that_do_not_apply_are_skipped_silently(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = make_service(repo)
    # No duration bound exists: the BPM step is the first applicable one.
    result = search(service, "epic battle", bpm_min=400.0, bpm_max=410.0)
    assert result.relaxed == ["Relaxed the BPM range (400-410) to a target of ~405 BPM"]


def test_min_results_decides_when_to_relax(repo: CatalogRepository, ids: dict[str, int]) -> None:
    never, _ = make_service(repo, min_results=0)
    result = search(never, "epic battle under 5 seconds", sources=("jamendo",))
    assert result.items == [] and result.relaxed == []
    # One embedded jamendo track lasts 100 s or less; asking for at least 2 relaxes the duration.
    picky, _ = make_service(repo, min_results=2)
    result = search(picky, "epic battle under 100 seconds", sources=("jamendo",))
    assert result.relaxed == ["Relaxed the duration limit (≤ 100 s)"]
    assert result.total_candidates > 2
    modest, _ = make_service(repo, min_results=1)
    assert search(modest, "epic battle under 100 seconds", sources=("jamendo",)).relaxed == []


@pytest.fixture
def red_only(tmp_path: Path) -> CatalogRepository:
    """A catalog whose only tracks are red (or unknown) licensed."""
    repo = open_path(tmp_path / "red" / "catalog.db")
    for n, risk in enumerate(["red", "red", "unknown"], start=1):
        track_id = repo.upsert_track(
            TrackRecord(
                source="jamendo",
                source_id=str(n),
                title=f"Red {n}",
                artist=f"Artist {n}",
                duration_s=100.0,
                risk=risk,
                vocal_instrumental="vocal",
            )
        )
        repo.set_embedding(track_id, MODEL_ID, axis("epic", 1.0) + axis("calm", 0.1 * n))
    return repo


def test_the_vocal_filter_is_relaxed_last(red_only: CatalogRepository) -> None:
    service, _ = make_service(red_only)
    result = search(
        service,
        "epic battle under 5 seconds 300-310 bpm",
        vocal="instrumental",
        max_risk="red",
    )
    assert result.relaxed == [
        "Relaxed the duration limit (≤ 5 s)",
        "Relaxed the BPM range (300-310) to a target of ~305 BPM",
        "Relaxed the vocal filter (instrumental only)",
    ]
    assert {i.title for i in result.items} == {"Red 1", "Red 2"}  # still no unknown-risk track


def test_the_licence_filter_is_never_relaxed(red_only: CatalogRepository) -> None:
    service, _ = make_service(red_only)
    result = search(service, "epic battle under 5 seconds", max_risk="amber", vocal="instrumental")
    assert result.items == []
    assert result.relaxed == [
        "Relaxed the duration limit (≤ 5 s)",
        "Relaxed the vocal filter (instrumental only)",
    ]
    assert result.notes == ["No amber-licence tracks match; try allowing red"]


@pytest.mark.parametrize(
    ("max_risk", "later"), [("green", "amber"), ("amber", "red"), ("red", "unknown")]
)
def test_the_empty_note_names_the_licence_filter(
    red_only: CatalogRepository, max_risk: str, later: str
) -> None:
    service, _ = make_service(red_only)
    result = search(service, "epic battle", max_risk=max_risk)
    if max_risk == "red":
        assert len(result.items) == 2  # the red ones; the unknown-risk one stays out
        return
    assert result.items == [] and result.total_candidates == 0
    assert result.notes == [f"No {max_risk}-licence tracks match; try allowing {later}"]


def test_the_empty_note_without_a_licence_filter_names_the_sources(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = make_service(repo)
    result = search(service, "epic battle", sources=("nowhere",))
    assert result.items == []
    assert result.notes == ["No tracks match in nowhere"]


def test_sources_are_never_relaxed(repo: CatalogRepository, ids: dict[str, int]) -> None:
    service, _ = make_service(repo)
    result = search(service, "epic battle under 5 seconds", sources=("local",), vocal="vocal")
    assert {i.source for i in result.items} == {"local"}


def test_relaxed_results_still_respect_max_risk(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = make_service(repo)
    result = search(service, "epic battle under 5 seconds 300-310 bpm", max_risk="green")
    assert result.relaxed  # relaxation happened
    assert result.items and {i.risk for i in result.items} == {"green"}
