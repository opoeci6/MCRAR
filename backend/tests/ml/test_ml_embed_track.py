"""embed_track: window math, averaging and normalisation (with a fake embedder)."""

from __future__ import annotations

import numpy as np
import pytest
from ml_support import BrokenDimEmbedder, FakeEmbedder, tone

from mcrar.ml.embedders import embed_track, l2_normalize, track_windows
from mcrar.ml.embedders.base import window_starts

SR = 8000
WINDOW = SR  # window_s = 1.0


def test_long_clip_uses_three_windows_centred_at_20_50_80_percent() -> None:
    n = 10 * SR
    assert window_starts(n, WINDOW) == [
        round(0.2 * n) - WINDOW // 2,
        round(0.5 * n) - WINDOW // 2,
        round(0.8 * n) - WINDOW // 2,
    ]


def test_windows_are_moved_inward_at_the_edges() -> None:
    n = 3 * WINDOW
    starts = window_starts(n, WINDOW)
    assert all(0 <= s <= n - WINDOW for s in starts)
    n = round(1.2 * WINDOW)  # the 20% window would start before 0 and the 80% one end after n
    assert window_starts(n, WINDOW) == [0, round(0.5 * n) - WINDOW // 2, n - WINDOW]


def test_clip_barely_longer_than_a_window_dedupes_identical_windows() -> None:
    assert window_starts(WINDOW + 1, WINDOW) == [0, 1]
    assert len(window_starts(WINDOW + 1, WINDOW)) == 2


def test_short_clip_is_one_zero_padded_window() -> None:
    clip = tone(0.25, SR)
    windows = track_windows(clip, SR, 1.0)
    assert len(windows) == 1
    assert windows[0].shape == (WINDOW,)
    assert np.array_equal(windows[0][: clip.size], clip)
    assert not windows[0][clip.size :].any()


def test_clip_of_exactly_one_window_is_not_padded() -> None:
    clip = tone(1.0, SR)
    (window,) = track_windows(clip, SR, 1.0)
    assert np.array_equal(window, clip)


def test_windows_are_float32_contiguous_copies_of_the_right_slices() -> None:
    clip = tone(8.0, SR)
    windows = track_windows(clip, SR, 1.0)
    assert len(windows) == 3
    for window, start in zip(windows, window_starts(clip.size, WINDOW), strict=True):
        assert window.dtype == np.float32
        assert window.flags["C_CONTIGUOUS"]
        assert np.array_equal(window, clip[start : start + WINDOW])


def test_windows_are_embedded_in_one_batch_and_averaged_then_renormalised() -> None:
    embedder = FakeEmbedder(sample_rate=SR, window_s=1.0)
    rng = np.random.default_rng(3)
    clip = (rng.standard_normal(10 * SR) * np.linspace(0.1, 1.0, 10 * SR)).astype(np.float32)
    vector = embed_track(embedder, clip, SR)

    assert len(embedder.audio_calls) == 1  # one batch
    batch = embedder.audio_calls[0]
    assert len(batch) == 3 and all(w.shape == (WINDOW,) for w in batch)
    manual = l2_normalize(embedder.embed_audio(batch)).mean(axis=0)
    assert np.allclose(vector, manual / np.linalg.norm(manual), atol=1e-6)
    assert vector.shape == (embedder.dim,)
    assert vector.dtype == np.float32
    assert np.linalg.norm(vector) == pytest.approx(1.0, abs=1e-6)


def test_short_clip_embeds_a_single_window() -> None:
    embedder = FakeEmbedder(sample_rate=SR, window_s=1.0)
    vector = embed_track(embedder, tone(0.5, SR), SR)
    assert [len(call) for call in embedder.audio_calls] == [1]
    assert np.linalg.norm(vector) == pytest.approx(1.0, abs=1e-6)


def test_the_result_depends_on_the_audio() -> None:
    embedder = FakeEmbedder(sample_rate=SR, window_s=1.0)
    low = embed_track(embedder, tone(4.0, SR, 110.0), SR)
    high = embed_track(embedder, tone(4.0, SR, 3000.0), SR)
    assert not np.allclose(low, high)


def test_wrong_sample_rate_is_rejected() -> None:
    embedder = FakeEmbedder(sample_rate=SR)
    with pytest.raises(ValueError, match="needs audio at 8000 Hz, got 22050 Hz"):
        embed_track(embedder, tone(2.0, 22050), 22050)


@pytest.mark.parametrize(
    ("samples", "message"),
    [
        (np.zeros(0, dtype=np.float32), "empty"),
        (np.zeros((SR, 2), dtype=np.float32), "mono"),
    ],
)
def test_empty_and_multichannel_audio_are_rejected(samples: np.ndarray, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        embed_track(FakeEmbedder(sample_rate=SR), samples, SR)


def test_an_embedder_returning_the_wrong_dimension_is_rejected() -> None:
    with pytest.raises(ValueError, match="returned 7-d embeddings, expected 8"):
        embed_track(BrokenDimEmbedder(sample_rate=SR, dim=8), tone(2.0, SR), SR)


def test_l2_normalize_keeps_zero_rows_zero() -> None:
    out = l2_normalize(np.array([[3.0, 4.0], [0.0, 0.0]]))
    assert out.dtype == np.float32
    assert np.allclose(out, [[0.6, 0.8], [0.0, 0.0]])
