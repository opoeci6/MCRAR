"""The Song Describer loader, the audio embedding step and the retrieval evaluation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from ml_bakeoff_support import TRACK_ID_BASE, ToneEmbedder, make_sdd

from mcrar.ml.bakeoff import sdd
from mcrar.ml.bakeoff.common import BakeoffError


def test_audio_path_maps_the_csv_path(tmp_path: Path) -> None:
    assert sdd.audio_path(tmp_path, "34/1004034.mp3") == (
        tmp_path / "audio" / "audio" / "34" / "1004034.2min.mp3"
    )


def test_load_sdd_keeps_only_validated_captions_by_default(tmp_path: Path) -> None:
    ids = make_sdd(tmp_path)
    default = sdd.load_sdd(tmp_path)
    assert [c.text for c in default.captions] == [f"tone {i}" for i in range(5)]
    assert all(c.valid for c in default.captions)
    assert set(default.tracks) == set(ids)  # the gallery covers every track of the CSV
    everything = sdd.load_sdd(tmp_path, all_captions=True)
    assert len(everything.captions) == 12
    assert sum(c.valid for c in everything.captions) == 5


def test_load_sdd_skips_and_counts_missing_files(tmp_path: Path) -> None:
    ids = make_sdd(tmp_path, absent=[1, 4])
    data = sdd.load_sdd(tmp_path)
    assert data.missing == [ids[1], ids[4]]
    assert set(data.tracks) == set(ids) - {ids[1], ids[4]}
    assert all(path.is_file() for path in data.tracks.values())


def test_load_sdd_without_the_dataset_is_a_readable_error(tmp_path: Path) -> None:
    with pytest.raises(BakeoffError, match="not found"):
        sdd.load_sdd(tmp_path / "nowhere")


def test_load_sdd_rejects_a_malformed_csv(tmp_path: Path) -> None:
    (tmp_path / "song_describer.csv").write_text("caption_id,track_id\n1,2\n", encoding="utf-8")
    with pytest.raises(BakeoffError, match="cannot parse"):
        sdd.load_sdd(tmp_path)


def test_embed_sdd_tracks_embeds_each_file_and_counts_decode_failures(tmp_path: Path) -> None:
    ids = make_sdd(tmp_path, broken=[2])
    data = sdd.load_sdd(tmp_path)
    embedder = ToneEmbedder("tone", dim=8)
    events: list[tuple[int, str]] = []
    result = sdd.embed_sdd_tracks(
        embedder, data.tracks, on_progress=lambda i, n, t, status, why: events.append((t, status))
    )
    assert result.track_ids.tolist() == [t for t in ids if t != ids[2]]
    assert result.matrix.shape == (5, 8)
    assert [t for t, _ in result.failures] == [ids[2]]
    assert (ids[2], "failed") in events
    # the audio was handed over at the model's own sample rate
    assert all(len(clip) == embedder.sample_rate for call in embedder.audio_calls for clip in call)


def test_embed_sdd_saves_the_npz_with_track_ids_and_matrix(tmp_path: Path) -> None:
    ids = make_sdd(tmp_path, absent=[0])
    data = sdd.load_sdd(tmp_path)
    embedder = ToneEmbedder("tone", dim=8)
    report = sdd.embed_sdd(embedder, data, tmp_path)
    assert report.embedded == 5 and report.missing == 1 and report.failed == []
    assert report.path == tmp_path / "embeddings" / f"{embedder.model_id}.npz"
    with np.load(report.path) as saved:
        assert sorted(saved.files) == ["matrix", "track_ids"]
        assert saved["track_ids"].tolist() == ids[1:]
        assert saved["matrix"].shape == (5, 8)
        assert saved["matrix"].dtype == np.float32


def test_embed_sdd_fails_when_nothing_can_be_embedded(tmp_path: Path) -> None:
    make_sdd(tmp_path, n_tracks=2, broken=[0, 1])
    with pytest.raises(BakeoffError, match="no SDD track"):
        sdd.embed_sdd(ToneEmbedder("tone"), sdd.load_sdd(tmp_path), tmp_path)


def test_load_embeddings_file_errors_name_the_fix(tmp_path: Path) -> None:
    with pytest.raises(BakeoffError, match="sdd-embed"):
        sdd.load_embeddings_file(tmp_path / "missing.npz")


# -- evaluation -----------------------------------------------------------------------------------


def _captions(per_track: list[list[int]]) -> list[sdd.Caption]:
    """``per_track[t]`` lists caption ids of track ``t``."""
    return [
        sdd.Caption(cid, TRACK_ID_BASE + t, f"tone {t}", True)
        for t, cids in enumerate(per_track)
        for cid in cids
    ]


def _identity(captions: list[sdd.Caption], n_tracks: int, dim: int = 8):
    gallery = np.arange(TRACK_ID_BASE, TRACK_ID_BASE + n_tracks)
    tracks = np.eye(n_tracks, dim, dtype=np.float32)
    texts = np.stack([tracks[c.track_id - TRACK_ID_BASE] for c in captions])
    return gallery, tracks, texts


def test_evaluate_sdd_perfect_model() -> None:
    captions = _captions([[1, 2], [3], [4], [5, 6]])
    gallery, tracks, texts = _identity(captions, 4)
    out = sdd.evaluate_sdd(captions, gallery, {"m": tracks}, {"m": texts}, n_resamples=50)
    t2a = out["results"]["m"]["t2a"]
    assert (t2a["R@1"], t2a["R@5"], t2a["R@10"], t2a["mrr"], t2a["median_rank"]) == (1, 1, 1, 1, 1)
    assert t2a["n_captions"] == 6 and t2a["n_tracks"] == 4
    assert out["results"]["m"]["a2t"]["R@1"] == 1.0
    assert out["n_query_tracks"] == 4
    assert out["pairwise"] == []  # one model: nothing to compare


def test_evaluate_sdd_known_ranks_and_audio_to_text_hit_on_any_caption() -> None:
    # 3 tracks in 2-d. Track 0 has two captions: the first points at track 1, the second at 0.
    captions = _captions([[1, 2], [3], [4]])
    gallery = np.arange(TRACK_ID_BASE, TRACK_ID_BASE + 3)
    tracks = np.array([[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]], dtype=np.float32)
    texts = np.array([[0.4, 1.0], [1.0, 0.1], [0.0, 1.0], [-1.0, 0.0]], dtype=np.float32)
    out = sdd.evaluate_sdd(captions, gallery, {"m": tracks}, {"m": texts}, n_resamples=20)
    t2a = out["results"]["m"]["t2a"]
    assert t2a["n_captions"] == 4 and t2a["n_tracks"] == 3
    assert t2a["R@1"] == 0.75  # the first caption of track 0 retrieves track 1 first
    assert t2a["R@5"] == 1.0
    assert t2a["median_rank"] == 1.0
    assert t2a["mrr"] == pytest.approx((0.5 + 1 + 1 + 1) / 4)
    # audio to text: any caption of the track counts as a hit, so every track is found at once
    assert out["results"]["m"]["a2t"]["R@1"] == 1.0
    assert out["results"]["m"]["a2t"]["n_tracks"] == 3


def test_evaluate_sdd_pairwise_flags_the_better_model() -> None:
    n = 40
    captions = _captions([[i + 1] for i in range(n)])
    gallery, good_tracks, good_texts = _identity(captions, n, dim=n)
    rng = np.random.default_rng(0)
    bad_tracks = rng.standard_normal((n, 16)).astype(np.float32)
    bad_texts = rng.standard_normal((n, 16)).astype(np.float32)
    out = sdd.evaluate_sdd(
        captions,
        gallery,
        {"good": good_tracks, "bad": bad_tracks},
        {"good": good_texts, "bad": bad_texts},
        n_resamples=200,
    )
    r10 = next(p for p in out["pairwise"] if p["metric"] == "R@10")
    assert (r10["a"], r10["b"]) == ("good", "bad")
    assert r10["diff"] > 0 and r10["ci"][0] > 0 and r10["significant"]
    assert {p["metric"] for p in out["pairwise"]} == {"R@10", "MRR"}


def test_evaluate_sdd_is_deterministic() -> None:
    captions = _captions([[i + 1] for i in range(30)])
    rng = np.random.default_rng(5)
    gallery = np.arange(TRACK_ID_BASE, TRACK_ID_BASE + 30)
    args = (
        captions,
        gallery,
        {"m": rng.standard_normal((30, 6)).astype(np.float32)},
        {"m": rng.standard_normal((30, 6)).astype(np.float32)},
    )
    assert sdd.evaluate_sdd(*args, n_resamples=100, seed=1) == sdd.evaluate_sdd(
        *args, n_resamples=100, seed=1
    )


def test_evaluate_sdd_rejects_a_caption_whose_track_is_not_in_the_gallery() -> None:
    captions = _captions([[1], [2]])
    gallery = np.array([TRACK_ID_BASE])
    with pytest.raises(ValueError, match="gallery"):
        sdd.evaluate_sdd(
            captions, gallery, {"m": np.eye(1, 4, dtype=np.float32)}, {"m": np.eye(2, 4)}
        )


def test_common_gallery_is_the_intersection_within_the_csv() -> None:
    a = (np.array([1, 2, 3, 4]), np.zeros((4, 2)))
    b = (np.array([2, 3, 4, 9]), np.zeros((4, 2)))
    assert sdd.common_gallery({"a": a, "b": b}, {2, 3, 9}).tolist() == [2, 3]
