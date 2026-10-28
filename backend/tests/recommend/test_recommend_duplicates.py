"""The same piece uploaded twice (two Jamendo ids, same title, artist and length) shows once."""

from __future__ import annotations

from recommend_support import MODEL_ID, make_service

from mcrar.catalog import CatalogRepository, TrackRecord
from mcrar.config import SearchWeights
from mcrar.recommend import SearchFilters, SearchRequest
from mcrar.recommend.rank import Candidate, piece_key, rank_candidates

W = SearchWeights()


def test_the_piece_key_ignores_case_and_spacing_and_rounds_the_length() -> None:
    key = piece_key("October Sunset", "Doppelganger", 459.0)
    assert key == piece_key("  october   SUNSET ", "doppelganger", 459.4)
    assert key != piece_key("October Sunset", "Doppelganger", 461.0)
    assert key != piece_key("October Sunset", "Someone Else", 459.0)
    assert key != piece_key("October Sunrise", "Doppelganger", 459.0)


def test_without_a_title_an_artist_or_a_length_a_track_is_never_a_duplicate() -> None:
    assert piece_key(None, "Ada", 120.0) is None
    assert piece_key("  ", "Ada", 120.0) is None
    assert piece_key("Shadow Walk", None, 120.0) is None
    assert piece_key("Shadow Walk", "Ada", None) is None


def test_ranking_keeps_only_the_best_copy_of_a_piece() -> None:
    cands = [
        Candidate(1, "A", cosine=0.5, same_piece="p"),
        Candidate(2, "B", cosine=0.9),
        Candidate(3, "A", cosine=0.7, same_piece="p"),
        Candidate(4, "C", cosine=0.6, same_piece=None),
        Candidate(5, "D", cosine=0.6, same_piece=None),
    ]
    ranked = rank_candidates(cands, weights=W, semantic=True, tags=False)
    assert [r.track_id for r in ranked] == [2, 3, 4, 5]  # 1 is 3's weaker copy; None never merges


def test_a_dropped_copy_does_not_count_towards_the_artist_cap() -> None:
    cands = [
        Candidate(1, "A", cosine=0.9, same_piece="p"),
        Candidate(2, "A", cosine=0.8, same_piece="p"),
        Candidate(3, "A", cosine=0.7),
        Candidate(4, "B", cosine=0.6),
    ]
    ranked = rank_candidates(cands, weights=W, semantic=True, tags=False, max_per_artist=2)
    assert [r.track_id for r in ranked] == [1, 3, 4]


def add_copy(repo: CatalogRepository, ids: dict[str, int], title: str) -> int:
    """Another upload of ``title``: a new source id, the same title, artist, length and audio."""
    original = repo.get_track(ids[title])
    assert original is not None
    copy_id = repo.upsert_track(
        TrackRecord(
            source=original.source,
            source_id="copy-of-" + original.source_id,
            title=original.title.upper(),
            artist=original.artist,
            duration_s=original.duration_s,
            source_url="https://example.test/copy",
            license_code=original.license_code,
            license_url=original.license_url,
            risk=original.risk,
        )
    )
    repo.set_embedding(copy_id, MODEL_ID, repo.get_embedding(ids[title], MODEL_ID))
    return copy_id


def test_a_text_search_shows_a_piece_uploaded_twice_once(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = make_service(repo)
    request = SearchRequest(text="tense hallway", filters=SearchFilters(), limit=50)
    before = [item.track_id for item in service.search(request).items]
    copy_id = add_copy(repo, ids, "Shadow Walk")
    result = service.search(request)
    found = [item.track_id for item in result.items]
    assert sum(t in (ids["Shadow Walk"], copy_id) for t in found) == 1
    assert len(found) == len(before) and result.total_candidates == len(before)


def test_a_reference_search_leaves_out_every_copy_of_the_reference(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    service, _ = make_service(repo)
    copy_id = add_copy(repo, ids, "Shadow Walk")
    ref = service.reference_for_track(ids["Shadow Walk"])
    result = service.search(SearchRequest(filters=SearchFilters(), reference=ref, limit=50))
    found = [item.track_id for item in result.items]
    assert copy_id not in found and ids["Shadow Walk"] not in found
    assert found  # its neighbours are still there
