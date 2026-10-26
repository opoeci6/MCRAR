"""Hand labels of game scenes (M9): checking them and merging several labellers into one truth.

A label says which scenes of the 14 in the ``scene`` set a track fits and how intense it is. The
owner and a collaborator each label their own part of the labelling pool (plus a shared slice,
so their agreement can be measured). ``merge_labels`` combines them per track for evaluation and
training: a scene counts as present when at least half of the track's labellers marked it (so a
tie between two labellers counts as present), and the intensity is the mean of the labellers'
``low``/``mid``/``high`` (1, 2, 3). Skipped tracks carry no label and are left out.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np

from mcrar.catalog import SceneLabel
from mcrar.recommend.vocab import SCENE, Vocabulary

INTENSITY_VALUE = {"low": 1, "mid": 2, "high": 3}


def check_scenes(vocab: Vocabulary, scenes: Iterable[str]) -> list[str]:
    """The scene ids, in order and without repeats, or ``ValueError`` naming every unknown one.

    Only ids are accepted (not display names or synonyms): the labels are data, not queries.
    """
    listed = list(dict.fromkeys(scenes))
    unknown = [s for s in listed if not isinstance(s, str) or not vocab.has(SCENE, s)]
    if unknown:
        valid = ", ".join(vocab.labels(SCENE))
        raise ValueError(
            f"unknown scene label(s): {', '.join(repr(u) for u in unknown)}; choose from: {valid}"
        )
    return listed


@dataclass(frozen=True)
class MergedLabels:
    """One truth per labelled track: ``scenes`` is a bool matrix ``[track, scene]`` (columns in
    the order of ``labels``), ``intensity`` the mean intensity value (NaN: nobody gave one) and
    ``labellers`` how many people labelled each track."""

    track_ids: np.ndarray
    labels: list[str]
    scenes: np.ndarray
    intensity: np.ndarray
    labellers: np.ndarray

    def __len__(self) -> int:
        return len(self.track_ids)


def merge_labels(labels: Iterable[SceneLabel], scene_ids: Sequence[str]) -> MergedLabels:
    """Merge the ``labelled`` labels per track (see the module docstring).

    Scenes outside ``scene_ids`` are ignored. Tracks are ordered by id.
    """
    by_track: dict[int, list[SceneLabel]] = {}
    for label in labels:
        if label.status == "labelled":
            by_track.setdefault(label.track_id, []).append(label)
    ids = sorted(by_track)
    column = {scene: i for i, scene in enumerate(scene_ids)}
    scenes = np.zeros((len(ids), len(column)), dtype=bool)
    intensity = np.full(len(ids), np.nan)
    count = np.zeros(len(ids), dtype=int)
    for row, track_id in enumerate(ids):
        people = by_track[track_id]
        count[row] = len(people)
        votes = np.zeros(len(column))
        for person in people:
            for scene in person.scenes:
                if scene in column:
                    votes[column[scene]] += 1
        scenes[row] = votes * 2 >= len(people)  # at least half of the labellers
        values = [INTENSITY_VALUE[p.intensity] for p in people if p.intensity is not None]
        if values:
            intensity[row] = float(np.mean(values))
    return MergedLabels(np.array(ids, dtype=np.int64), list(scene_ids), scenes, intensity, count)
