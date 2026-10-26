"""Tag scoring: stored rows, the zero-shot fallback and the composite that mixes them."""

from __future__ import annotations

import numpy as np
import pytest
from recommend_support import (
    MODEL_ID,
    QUERY_TEXTS,
    MapEmbedder,
    catalog_score,
    make_service,
    make_settings,
)

from mcrar.catalog import CatalogRepository, NumpyVectorIndex, TrackRecord
from mcrar.recommend import (
    CompositeTagScorer,
    SearchFilters,
    SearchRequest,
    SearchService,
    StoredTagScorer,
    TagScorer,
    Vocabulary,
    ZeroShotTagScorer,
)

VOCAB = Vocabulary.default()


def zero_shot(repo: CatalogRepository, embedder: MapEmbedder) -> ZeroShotTagScorer:
    index = NumpyVectorIndex.from_repository(repo, MODEL_ID)
    return ZeroShotTagScorer(lambda: index, embedder.embed_text, VOCAB)


def sigmoid_z(index: NumpyVectorIndex, label_vector: np.ndarray, track_id: int) -> float:
    """The documented score of a track, computed the long way."""
    cosines = index.matrix @ (label_vector / np.linalg.norm(label_vector))
    row = int(np.flatnonzero(index.ids == track_id)[0])
    z = (cosines[row] - cosines.mean()) / cosines.std()
    return float(1.0 / (1.0 + np.exp(-1.7 * z)))


def test_stored_scorer_reads_tag_probs_and_reports_coverage(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    a, b, c = ids["Smooth Cafe"], ids["Garage Band"], ids["Lullaby"]
    repo.set_tag_probs(a, "genre", "head", "genre-mlp@1", {"jazz": 0.9, "rock": 0.1})
    repo.set_tag_probs(b, "genre", "zeroshot", "genre-zs@1", {"rock": 0.8})
    repo.set_tag_probs(c, "moodtheme", "head", "mood@1", {"calm": 0.7})  # another label set
    scorer = StoredTagScorer(repo)
    scores, covered = scorer.scores_with_coverage([a, b, c], "genre", ["jazz", "rock", "blues"])
    assert covered.tolist() == [True, True, False]
    assert scores["jazz"].tolist() == [0.9, 0.0, 0.0]
    assert scores["rock"].tolist() == [0.1, 0.8, 0.0]
    assert scores["blues"].tolist() == [0.0, 0.0, 0.0]
    assert scorer.scores([c], "moodtheme", ["calm"])["calm"].tolist() == [0.7]
    assert isinstance(scorer, TagScorer)


def test_zero_shot_is_a_sigmoid_of_the_catalog_wide_z_score(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    embedder = MapEmbedder(QUERY_TEXTS)
    index = NumpyVectorIndex.from_repository(repo, MODEL_ID)
    scorer = ZeroShotTagScorer(lambda: index, embedder.embed_text, VOCAB)
    pool = [ids[t] for t in ("Smooth Cafe", "Misty Lake", "Garage Band", "Lullaby")]
    scores = scorer.scores(pool, "genre", ["jazz", "rock"])
    assert embedder.calls == [["Jazz music", "Rock music"]]  # "<display name> music"
    for label, vector in (("jazz", QUERY_TEXTS["Jazz music"]), ("rock", QUERY_TEXTS["Rock music"])):
        for track_id, got in zip(pool, scores[label], strict=True):
            assert got == pytest.approx(sigmoid_z(index, vector, track_id))
        assert ((scores[label] > 0) & (scores[label] < 1)).all()
    assert scores["jazz"].argmax() == 0 and scores["rock"].argmax() == 2
    assert scores["jazz"][0] > 0.5 > scores["jazz"][3]  # above and below the catalog average
    assert scores["jazz"][1] > scores["jazz"][3]  # Misty Lake has some jazz in it


def test_zero_shot_scores_do_not_depend_on_the_pool(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    scorer = zero_shot(repo, MapEmbedder(QUERY_TEXTS))
    track = ids["Smooth Cafe"]
    alone = scorer.scores([track], "genre", ["jazz"])["jazz"][0]
    for pool in (
        [track, ids["Lullaby"]],
        [ids["Garage Band"], track, ids["Epic Quest"], ids["Sunny Day"]],
        list(ids.values()),
    ):
        got = scorer.scores(pool, "genre", ["jazz", "rock"])["jazz"][pool.index(track)]
        assert got == pytest.approx(alone)
    assert 0.5 < alone < 1.0  # not pushed to 0 or 1 by the pool


def test_zero_shot_scores_are_monotonic_in_the_cosine(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    embedder = MapEmbedder(QUERY_TEXTS)
    index = NumpyVectorIndex.from_repository(repo, MODEL_ID)
    scorer = ZeroShotTagScorer(lambda: index, embedder.embed_text, VOCAB)
    pool = [int(i) for i in index.ids]
    got = scorer.scores(pool, "genre", ["jazz"])["jazz"]
    cosines = index.matrix @ QUERY_TEXTS["Jazz music"]
    order = np.argsort(cosines)
    assert (np.diff(got[order]) >= -1e-12).all()
    assert len(set(np.round(cosines, 6))) > 1 and got.min() < got.max()
    assert ((got >= 0) & (got <= 1)).all()


def test_zero_shot_with_no_spread_scores_everything_one_half(repo: CatalogRepository) -> None:
    from recommend_support import axis

    for n in (1, 2, 3):  # identical embeddings: sigma = 0
        track_id = repo.upsert_track(TrackRecord(source="local", source_id=str(n), risk="green"))
        repo.set_embedding(track_id, MODEL_ID, axis("calm"))
    scorer = zero_shot(repo, MapEmbedder(QUERY_TEXTS))
    got = scorer.scores([1, 2, 3], "moodtheme", ["calm", "dark"])
    assert got["calm"].tolist() == [0.5, 0.5, 0.5] and got["dark"].tolist() == [0.5, 0.5, 0.5]


def test_zero_shot_caches_text_embeddings_and_statistics_per_index(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    embedder = MapEmbedder(QUERY_TEXTS)
    current = [NumpyVectorIndex.from_repository(repo, MODEL_ID)]
    scorer = ZeroShotTagScorer(lambda: current[0], embedder.embed_text, VOCAB)
    pool = [ids["Smooth Cafe"], ids["Lullaby"]]
    first = scorer.scores(pool, "genre", ["jazz"])["jazz"]
    scorer.scores(pool, "genre", ["jazz"])
    scorer.scores(pool, "genre", ["jazz", "rock"])
    assert embedder.calls == [["Jazz music"], ["Rock music"]]
    assert set(scorer._stats) == {("genre", "jazz"), ("genre", "rock")}

    # New embeddings arrive: the service builds a new index, and the statistics start over.
    repo.set_embedding(ids["Unembedded Tune"], MODEL_ID, QUERY_TEXTS["Jazz music"])
    current[0] = NumpyVectorIndex.from_repository(repo, MODEL_ID)
    again = scorer.scores(pool, "genre", ["jazz"])["jazz"]
    assert set(scorer._stats) == {("genre", "jazz")}
    assert not np.allclose(first, again)  # the catalog average moved
    assert embedder.calls == [["Jazz music"], ["Rock music"]]  # text embeddings are kept


def test_zero_shot_edge_cases(repo: CatalogRepository, ids: dict[str, int]) -> None:
    scorer = zero_shot(repo, MapEmbedder(QUERY_TEXTS))
    mixed = scorer.scores([ids["Unembedded Tune"], ids["Smooth Cafe"]], "genre", ["jazz"])
    assert mixed["jazz"][0] == 0.0 and mixed["jazz"][1] > 0.5  # no embedding: 0
    assert scorer.scores([], "genre", ["jazz"])["jazz"].tolist() == []
    assert scorer.scores([ids["Smooth Cafe"]], "genre", []) == {}


def test_composite_uses_stored_rows_where_present_and_zero_shot_elsewhere(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    embedder = MapEmbedder(QUERY_TEXTS)
    spy = zero_shot(repo, embedder)
    seen: list[list[int]] = []

    class Spy:
        def scores(self, track_ids, label_set, labels):  # noqa: ANN001, ANN202
            seen.append(list(track_ids))
            return spy.scores(track_ids, label_set, labels)

    tagged, other, third = ids["Garage Band"], ids["Smooth Cafe"], ids["Lullaby"]
    repo.set_tag_probs(tagged, "genre", "head", "genre-mlp@1", {"rock": 0.42, "jazz": 0.0})
    composite = CompositeTagScorer(StoredTagScorer(repo), Spy())
    scores = composite.scores([other, tagged, third], "genre", ["jazz", "rock"])
    assert seen == [[other, third]]  # zero-shot only for the tracks with no stored rows
    assert scores["rock"][1] == 0.42  # the stored value
    assert scores["jazz"][1] == 0.0
    alone = spy.scores([other, third], "genre", ["jazz"])["jazz"]
    assert scores["jazz"][0] == alone[0] > 0.5  # Smooth Cafe: zero-shot, a jazz track
    assert scores["jazz"][2] == alone[1] < 0.5  # Lullaby: zero-shot, not jazz

    seen.clear()
    repo.set_tag_probs(other, "genre", "head", "genre-mlp@1", {"jazz": 1.0})
    repo.set_tag_probs(third, "genre", "head", "genre-mlp@1", {"jazz": 0.0})
    composite.scores([other, tagged, third], "genre", ["jazz"])
    assert seen == []  # everything tagged: zero-shot is not consulted

    without = CompositeTagScorer(StoredTagScorer(repo), None)
    assert without.scores([ids["Epic Quest"]], "genre", ["jazz"])["jazz"].tolist() == [0.0]


def test_search_ranks_by_stored_tags_when_they_exist(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    for title in ("Garage Band", "Metal Gods"):
        repo.set_tag_probs(ids[title], "genre", "head", "genre-mlp@1", {"rock": 0.99, "jazz": 0.0})
    for title in ("Smooth Cafe", "Epic Quest"):
        repo.set_tag_probs(ids[title], "genre", "head", "genre-mlp@1", {"rock": 0.0, "jazz": 0.5})
    for title in ("Lullaby", "Ambient Pad", "Sunny Day", "Shadow Walk"):
        repo.set_tag_probs(ids[title], "genre", "head", "genre-mlp@1", {"rock": 0.0, "jazz": 0.1})
    service, embedder = make_service(repo)
    result = service.search(
        SearchRequest("", SearchFilters(genres=("rock",), max_risk="red"), limit=50)
    )
    best = {i.title: i for i in result.items}
    # Stored values are standardised over the eight tagged tracks: rock is 0.99 twice, else 0.
    rock = [0.99, 0.99] + [0.0] * 6
    high, low = catalog_score(rock, 0), catalog_score(rock, 2)
    assert 0.9 < high < 1.0 and 0.0 < low < 0.5
    assert best["Garage Band"].breakdown["tags"]["raw"] == pytest.approx(high)
    assert best["Garage Band"].top_tags[0].label == "rock"
    assert best["Garage Band"].top_tags[0].score == pytest.approx(high)
    assert best["Garage Band"].top_tags[0].display == "Rock"
    assert best["Garage Band"].top_tags[0].label_set == "genre"
    assert best["Smooth Cafe"].breakdown["tags"]["raw"] == pytest.approx(low)  # tagged, not rock
    # Untagged tracks are scored zero-shot against the whole catalog: stable, in (0, 1).
    assert embedder.calls
    party = best["Party Time"].breakdown["tags"]["raw"]
    assert 0.5 < party < best["Garage Band"].breakdown["tags"]["raw"]
    assert [i.title for i in result.items[:2]] == ["Garage Band", "Metal Gods"]


def test_a_fully_tagged_catalog_never_needs_the_model(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    for track_id in ids.values():
        repo.set_tag_probs(track_id, "genre", "head", "genre-mlp@1", {"jazz": 0.2, "rock": 0.3})
    # One track stands out, so the label statistics have a spread.
    repo.set_tag_probs(ids["Smooth Cafe"], "genre", "head", "genre-mlp@1", {"jazz": 0.9})
    service, embedder = make_service(repo)
    result = service.search(
        SearchRequest("", SearchFilters(genres=("jazz",), vocal="instrumental"), limit=5)
    )
    assert result.items and embedder.calls == [] and not service.embedder_loaded
    assert result.items[0].title == "Smooth Cafe"
    other = next(i for i in result.items if i.title != "Smooth Cafe")
    # Below average for jazz (0.2 against a mean of ~0.23), above for rock (0.3 against ~0.29).
    assert [t.label for t in other.top_tags] == ["rock", "jazz"]
    assert other.top_tags[0].score > 0.5 > other.top_tags[1].score


def test_top_tags_cover_the_requested_label_sets(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    track = ids["Smooth Cafe"]
    others = [ids["Lullaby"], ids["Epic Quest"]]
    probs = {
        "genre": {"jazz": [0.9, 0.1, 0.3], "blues": [0.4, 0.0, 0.2]},
        "moodtheme": {"calm": [0.8, 0.1, 0.4], "dark": [0.6, 0.7, 0.1]},
    }
    for label_set, labels in probs.items():
        for n, track_id in enumerate([track, *others]):
            row = {label: values[n] for label, values in labels.items()}
            repo.set_tag_probs(track_id, label_set, "head", "g@1", row)
    service, _ = make_service(repo)

    both = service.search(SearchRequest("", SearchFilters(vocal="instrumental", max_risk="green")))
    item = next(i for i in both.items if i.track_id == track)
    assert [(t.label_set, t.label) for t in item.top_tags] == [
        ("genre", "jazz"),
        ("moodtheme", "calm"),
        ("genre", "blues"),
        ("moodtheme", "dark"),
    ]  # best standardised score first
    for tag in item.top_tags:
        assert tag.score == pytest.approx(catalog_score(probs[tag.label_set][tag.label], 0))
    only_genre = service.search(
        SearchRequest("", SearchFilters(genres=("jazz",), vocal="instrumental", max_risk="green"))
    )
    item = next(i for i in only_genre.items if i.track_id == track)
    assert {t.label_set for t in item.top_tags} == {"genre"}  # only the requested set
    assert len(item.top_tags) <= 5


def test_a_custom_tag_scorer_replaces_the_built_in_one(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []

    class Constant:
        def scores(self, track_ids, label_set, labels):  # noqa: ANN001, ANN202
            calls.append((label_set, tuple(labels)))
            return {label: np.full(len(track_ids), 0.25) for label in labels}

    service = SearchService(
        repo,
        make_settings(),
        embedder_loader=lambda: MapEmbedder(QUERY_TEXTS),
        tag_scorer=Constant(),
    )
    result = service.search(SearchRequest("epic battle", limit=3))
    assert {label_set for label_set, _ in calls} == {"moodtheme", "scene"}  # "epic", "battle"
    assert result.items[0].breakdown["tags"]["raw"] == 0.25  # the "epic" hint, scored by it
    assert all(t.score == 0.25 for t in result.items[0].top_tags)
    calls.clear()
    service.search(SearchRequest("tense hallway", limit=3))
    assert {label_set for label_set, _ in calls} == {"genre", "moodtheme", "scene"}  # top tags


def test_index_vectors_and_ids(repo: CatalogRepository, ids: dict[str, int]) -> None:
    index = NumpyVectorIndex.from_repository(repo, MODEL_ID)
    assert sorted(index.ids.tolist()) == sorted(v for k, v in ids.items() if k != "Unembedded Tune")
    wanted = [ids["Lullaby"], ids["Unembedded Tune"], ids["Shadow Walk"], 99999]
    found, matrix = index.vectors(wanted)
    assert found.tolist() == [True, False, True, False]
    assert matrix.shape == (2, 8)
    assert np.allclose(np.linalg.norm(matrix, axis=1), 1.0)
    assert np.allclose(matrix[0], repo.get_embedding(ids["Lullaby"], MODEL_ID))
    none_found, empty = index.vectors([99999])
    assert none_found.tolist() == [False] and empty.shape == (0, 8)
