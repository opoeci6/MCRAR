"""Vector search behind a small Protocol (a pgvector-backed index can implement it later)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import numpy as np

if TYPE_CHECKING:
    from mcrar.catalog.repository import CatalogRepository


@runtime_checkable
class VectorIndex(Protocol):
    model_id: str

    def add(self, ids: np.ndarray, matrix: np.ndarray) -> None:
        """Add or replace vectors; ``ids`` is shape (n,), ``matrix`` shape (n, dim)."""
        ...

    def search(
        self, query: np.ndarray, k: int, allowed_ids: Iterable[int] | None = None
    ) -> list[tuple[int, float]]:
        """Top-``k`` ``(id, cosine similarity)`` pairs, best first, within ``allowed_ids``."""
        ...

    def __len__(self) -> int: ...


def _normalise(matrix: np.ndarray, what: str) -> np.ndarray:
    if not np.isfinite(matrix).all():
        raise ValueError(f"{what} contains non-finite values")
    norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
    if (norms == 0).any():
        raise ValueError(f"{what} contains a zero vector")
    return (matrix / norms).astype(np.float32)


class NumpyVectorIndex:
    """Brute-force cosine index held in memory. Ties break by the smaller id."""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self._dim: int | None = None
        self._ids = np.empty(0, dtype=np.int64)
        self._matrix = np.empty((0, 0), dtype=np.float32)
        self._pos: dict[int, int] = {}

    @classmethod
    def from_repository(cls, repo: CatalogRepository, model_id: str) -> NumpyVectorIndex:
        index = cls(model_id)
        ids, matrix = repo.load_embeddings(model_id)
        index.add(ids, matrix)
        return index

    def __len__(self) -> int:
        return len(self._ids)

    @property
    def dim(self) -> int | None:
        return self._dim

    def add(self, ids: np.ndarray, matrix: np.ndarray) -> None:
        id_arr = np.asarray(ids)
        if id_arr.ndim != 1:
            raise ValueError(f"ids must be 1-D, got shape {id_arr.shape}")
        if not np.issubdtype(id_arr.dtype, np.integer):
            if id_arr.size == 0:
                id_arr = id_arr.astype(np.int64)
            else:
                raise ValueError(f"ids must be integers, got dtype {id_arr.dtype}")
        mat = np.asarray(matrix, dtype=np.float32)
        if len(id_arr) == 0:
            return
        if mat.ndim != 2 or mat.shape[0] != len(id_arr):
            raise ValueError(
                f"matrix shape {mat.shape} does not match {len(id_arr)} ids (expected (n, dim))"
            )
        if self._dim is not None and mat.shape[1] != self._dim:
            raise ValueError(f"vector dim {mat.shape[1]} does not match index dim {self._dim}")
        mat = _normalise(mat, "matrix")

        if self._dim is None:
            self._dim = int(mat.shape[1])
            self._matrix = np.empty((0, self._dim), dtype=np.float32)

        # Within one call the last occurrence of an id wins.
        last: dict[int, int] = {int(i): row for row, i in enumerate(id_arr)}
        new_ids: list[int] = []
        new_rows: list[int] = []
        for track_id, row in last.items():
            pos = self._pos.get(track_id)
            if pos is None:
                new_ids.append(track_id)
                new_rows.append(row)
            else:
                self._matrix[pos] = mat[row]
        if new_ids:
            start = len(self._ids)
            self._ids = np.concatenate([self._ids, np.asarray(new_ids, dtype=np.int64)])
            self._matrix = np.vstack([self._matrix, mat[new_rows]])
            for offset, track_id in enumerate(new_ids):
                self._pos[track_id] = start + offset

    def search(
        self, query: np.ndarray, k: int, allowed_ids: Iterable[int] | None = None
    ) -> list[tuple[int, float]]:
        q = np.asarray(query, dtype=np.float32)
        if q.ndim != 1:
            raise ValueError(f"query must be 1-D, got shape {q.shape}")
        if self._dim is not None and q.shape[0] != self._dim:
            raise ValueError(f"query dim {q.shape[0]} does not match index dim {self._dim}")
        q = _normalise(q, "query")
        if k <= 0 or len(self._ids) == 0:
            return []

        ids = self._ids
        matrix = self._matrix
        if allowed_ids is not None:
            allowed = np.fromiter((int(i) for i in allowed_ids), dtype=np.int64)
            mask = np.isin(ids, allowed)
            ids, matrix = ids[mask], matrix[mask]
            if len(ids) == 0:
                return []

        scores = matrix @ q
        order = np.lexsort((ids, -scores))[:k]  # primary: score desc, secondary: id asc
        return [(int(ids[i]), float(scores[i])) for i in order]
