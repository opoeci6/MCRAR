from __future__ import annotations

import numpy as np
import pytest

from mcrar.catalog import CatalogRepository, NumpyVectorIndex, TrackRecord, VectorIndex


def _index() -> NumpyVectorIndex:
    idx = NumpyVectorIndex("m")
    idx.add(
        np.array([10, 20, 30, 40]),
        np.array([[1, 0], [0, 1], [1, 1], [-1, 0]], dtype=np.float32),
    )
    return idx


def test_satisfies_protocol_and_len() -> None:
    idx = _index()
    assert isinstance(idx, VectorIndex)
    assert idx.model_id == "m"
    assert len(idx) == 4
    assert len(NumpyVectorIndex("x")) == 0


def test_top_k_cosine_descending() -> None:
    hits = _index().search(np.array([2.0, 0.1]), k=3)
    assert [i for i, _ in hits] == [10, 30, 20]
    scores = [s for _, s in hits]
    assert scores == sorted(scores, reverse=True)
    assert hits[0][1] == pytest.approx(2.0 / np.hypot(2.0, 0.1))
    assert all(isinstance(i, int) and isinstance(s, float) for i, s in hits)


def test_scale_invariance_of_add_and_query() -> None:
    idx = NumpyVectorIndex("m")
    idx.add(np.array([1, 2]), np.array([[100.0, 0.0], [0.0, 0.001]]))
    hits = idx.search(np.array([0.0, 50.0]), k=2)
    assert hits[0][0] == 2
    assert hits[0][1] == pytest.approx(1.0)
    assert hits[1][1] == pytest.approx(0.0)


def test_k_larger_than_size_and_nonpositive_k() -> None:
    idx = _index()
    assert len(idx.search(np.array([1.0, 0.0]), k=100)) == 4
    assert idx.search(np.array([1.0, 0.0]), k=0) == []


def test_allowed_ids_filters_before_top_k() -> None:
    idx = _index()
    q = np.array([1.0, 0.0])
    assert [i for i, _ in idx.search(q, k=1)] == [10]
    assert [i for i, _ in idx.search(q, k=1, allowed_ids=[20, 40])] == [20]
    assert [i for i, _ in idx.search(q, k=5, allowed_ids={40, 30, 999})] == [30, 40]
    assert idx.search(q, k=3, allowed_ids=[]) == []
    assert idx.search(q, k=3, allowed_ids=[999]) == []


def test_readding_an_id_replaces_its_vector() -> None:
    idx = _index()
    idx.add(np.array([20]), np.array([[1.0, 0.0]]))
    assert len(idx) == 4
    hits = idx.search(np.array([1.0, 0.0]), k=4)
    assert [i for i, _ in hits[:2]] == [10, 20]  # now identical to 10, tie -> smaller id
    assert hits[0][1] == pytest.approx(hits[1][1])
    # duplicate ids inside one call: last wins
    idx.add(np.array([50, 50]), np.array([[0.0, 1.0], [-1.0, 0.0]]))
    assert len(idx) == 5
    assert idx.search(np.array([-1.0, 0.0]), k=2, allowed_ids=[50])[0][1] == pytest.approx(1.0)


def test_ties_break_by_smaller_id_regardless_of_insertion_order() -> None:
    idx = NumpyVectorIndex("m")
    idx.add(np.array([9, 3, 7, 5]), np.tile(np.array([[0.6, 0.8]]), (4, 1)))
    idx.add(np.array([1]), np.array([[0.0, 1.0]]))
    for _ in range(3):
        assert [i for i, _ in idx.search(np.array([0.6, 0.8]), k=4)] == [3, 5, 7, 9]
    assert [i for i, _ in idx.search(np.array([0.6, 0.8]), k=2)] == [3, 5]


def test_dim_mismatch_raises() -> None:
    idx = _index()
    with pytest.raises(ValueError, match="dim"):
        idx.add(np.array([1]), np.ones((1, 3)))
    with pytest.raises(ValueError, match="dim"):
        idx.search(np.ones(3), k=1)
    assert len(idx) == 4


def test_bad_inputs_raise() -> None:
    idx = NumpyVectorIndex("m")
    with pytest.raises(ValueError):
        idx.add(np.array([1, 2]), np.ones((3, 2)))
    with pytest.raises(ValueError):
        idx.add(np.array([1]), np.array([[np.nan, 1.0]]))
    with pytest.raises(ValueError, match="zero"):
        idx.add(np.array([1]), np.zeros((1, 2)))
    with pytest.raises(ValueError):
        idx.add(np.array([1]), np.ones(2))
    assert len(idx) == 0
    idx.add(np.array([1]), np.array([[1.0, 0.0]]))
    with pytest.raises(ValueError):
        idx.search(np.zeros(2), k=1)
    with pytest.raises(ValueError):
        idx.search(np.ones((2, 2)), k=1)


def test_empty_index() -> None:
    idx = NumpyVectorIndex("m")
    assert idx.search(np.array([1.0, 2.0]), k=5) == []
    idx.add(np.array([], dtype=np.int64), np.empty((0, 2)))
    assert len(idx) == 0
    assert idx.search(np.array([1.0, 2.0]), k=5, allowed_ids=[1]) == []


def test_from_repository(repo: CatalogRepository) -> None:
    ids = [repo.upsert_track(TrackRecord(source="local", source_id=str(i))) for i in range(3)]
    repo.set_embedding(ids[0], "m", np.array([1.0, 0.0, 0.0]))
    repo.set_embedding(ids[1], "m", np.array([0.0, 1.0, 0.0]))
    repo.set_embedding(ids[2], "other", np.array([0.0, 0.0, 1.0]))
    idx = NumpyVectorIndex.from_repository(repo, "m")
    assert idx.model_id == "m"
    assert len(idx) == 2
    assert [i for i, _ in idx.search(np.array([0.1, 1.0, 0.0]), k=2)] == [ids[1], ids[0]]
    empty = NumpyVectorIndex.from_repository(repo, "missing")
    assert len(empty) == 0
    assert empty.search(np.ones(3), k=3) == []
