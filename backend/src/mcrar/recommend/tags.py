"""Tag scores for the ranking: ``TagScorer`` and its implementations.

``scores(track_ids, label_set, labels)`` returns, per label, an array aligned with ``track_ids``
with values in [0, 1].

- :class:`StoredTagScorer` reads the ``tag_probs`` rows written by the tagging models (M3b).
- :class:`ZeroShotTagScorer` is the fallback until a track is tagged: the cosine between the
  track's embedding and the text embedding of ``"<display name> music"``, standardised over the
  whole catalog and squashed with a sigmoid, so a score does not depend on the query's pool.
- :class:`CompositeTagScorer` uses stored rows for the tracks that have them and zero-shot for
  the rest. Both are in [0, 1] and stable across queries, so they mix reasonably while a
  catalog is only partly tagged.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import numpy as np

from mcrar.recommend.vocab import Vocabulary

if TYPE_CHECKING:
    from mcrar.catalog import CatalogRepository, NumpyVectorIndex

PROMPT = "{} music"  # text prompt per label, filled with the label's display name
SLOPE = 1.7  # sigmoid slope on the z-score of a track's cosine
MIN_STD = 1e-9  # a smaller spread counts as none: every track scores 0.5


@runtime_checkable
class TagScorer(Protocol):
    def scores(
        self, track_ids: Sequence[int], label_set: str, labels: Sequence[str]
    ) -> dict[str, np.ndarray]: ...


class StoredTagScorer:
    """Probabilities stored in ``tag_probs`` under ``head == label_set``."""

    def __init__(self, repo: CatalogRepository) -> None:
        self._repo = repo

    def scores_with_coverage(
        self, track_ids: Sequence[int], label_set: str, labels: Sequence[str]
    ) -> tuple[dict[str, np.ndarray], np.ndarray]:
        """The scores (0 where unknown) and a bool array: which tracks have rows for the set."""
        rows = self._repo.get_tag_probs_many(track_ids, heads=[label_set])
        out = {label: np.zeros(len(track_ids)) for label in labels}
        covered = np.zeros(len(track_ids), dtype=bool)
        for i, track_id in enumerate(track_ids):
            probs = rows.get(int(track_id))
            if not probs:
                continue
            covered[i] = True
            for row in probs:
                if row.label in out:
                    out[row.label][i] = min(max(row.prob, 0.0), 1.0)
        return out, covered

    def scores(
        self, track_ids: Sequence[int], label_set: str, labels: Sequence[str]
    ) -> dict[str, np.ndarray]:
        return self.scores_with_coverage(track_ids, label_set, labels)[0]


class ZeroShotTagScorer:
    """Cosine to ``"<display name> music"``, standardised over the whole catalog.

    For each label the cosine of every embedded track in the index to the label's text embedding
    gives a mean and a standard deviation (computed once and cached with the index; a new index
    drops them). A track scores ``sigmoid(1.7 * (cos - mean) / std)``: 0.5 is an average track,
    and the score does not depend on which other tracks are being scored. If every track has the
    same cosine (std 0) all tracks score 0.5. Tracks without an embedding score 0.

    ``index`` returns the current :class:`NumpyVectorIndex` of the default model; ``embed_text``
    embeds strings with the same model. Text embeddings are cached per label.
    """

    def __init__(
        self,
        index: Callable[[], NumpyVectorIndex],
        embed_text: Callable[[Sequence[str]], np.ndarray],
        vocab: Vocabulary,
    ) -> None:
        self._index = index
        self._embed_text = embed_text
        self._vocab = vocab
        self._text: dict[tuple[str, str], np.ndarray] = {}
        self._stats: dict[tuple[str, str], tuple[float, float]] = {}
        self._stats_index: NumpyVectorIndex | None = None

    def _label_vectors(self, label_set: str, labels: Sequence[str]) -> np.ndarray:
        missing = [label for label in labels if (label_set, label) not in self._text]
        if missing:
            prompts = [
                PROMPT.format(self._vocab.display_name(label_set, label)) for label in missing
            ]
            embedded = np.asarray(self._embed_text(prompts), dtype=np.float32)
            norms = np.maximum(np.linalg.norm(embedded, axis=1, keepdims=True), 1e-12)
            for label, vector in zip(missing, embedded / norms, strict=True):
                self._text[(label_set, label)] = vector
        return np.stack([self._text[(label_set, label)] for label in labels])

    def _label_stats(
        self, index: NumpyVectorIndex, label_set: str, labels: Sequence[str], vectors: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Mean and standard deviation of the catalog's cosines, per label."""
        if index is not self._stats_index:  # the catalog's embeddings changed: start over
            self._stats.clear()
            self._stats_index = index
        todo = [j for j, label in enumerate(labels) if (label_set, label) not in self._stats]
        if todo:
            sims = index.matrix @ vectors[todo].T  # (tracks in the index, labels to do)
            for k, j in enumerate(todo):
                self._stats[(label_set, labels[j])] = (
                    float(sims[:, k].mean()),
                    float(sims[:, k].std()),
                )
        pairs = [self._stats[(label_set, label)] for label in labels]
        return np.array([m for m, _ in pairs]), np.array([sd for _, sd in pairs])

    def scores(
        self, track_ids: Sequence[int], label_set: str, labels: Sequence[str]
    ) -> dict[str, np.ndarray]:
        out = {label: np.zeros(len(track_ids)) for label in labels}
        if not labels or not len(track_ids):
            return out
        index = self._index()
        found, matrix = index.vectors(track_ids)
        if not found.any():
            return out
        vectors = self._label_vectors(label_set, labels)
        mean, std = self._label_stats(index, label_set, labels, vectors)
        z = np.zeros((int(found.sum()), len(labels)))
        np.divide(matrix @ vectors.T - mean, std, out=z, where=std > MIN_STD)
        scores = np.clip(1.0 / (1.0 + np.exp(-SLOPE * np.clip(z, -50.0, 50.0))), 0.0, 1.0)
        for j, label in enumerate(labels):
            out[label][found] = scores[:, j]
        return out


class CompositeTagScorer:
    """Stored rows where a track has them, zero-shot for the other tracks."""

    def __init__(self, stored: StoredTagScorer, zero_shot: TagScorer | None) -> None:
        self._stored = stored
        self._zero_shot = zero_shot

    def scores(
        self, track_ids: Sequence[int], label_set: str, labels: Sequence[str]
    ) -> dict[str, np.ndarray]:
        out, covered = self._stored.scores_with_coverage(track_ids, label_set, labels)
        if self._zero_shot is None or covered.all():
            return out
        missing = np.flatnonzero(~covered)
        fallback = self._zero_shot.scores([track_ids[i] for i in missing], label_set, labels)
        for label in labels:
            out[label][missing] = fallback[label]
        return out
