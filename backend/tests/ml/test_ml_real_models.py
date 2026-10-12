"""Opt-in tests with the real models: run with ``pytest -m models``.

They download the pinned weights into HF_HOME (several GB) on first use and want a CUDA GPU for
the fp16 checks. Every model is loaded in commercial mode off, because MuQ-MuLan is CC-BY-NC.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from mcrar.config import Settings, get_settings
from mcrar.ml import MODELS
from mcrar.ml.embedders import embed_track, load_embedder
from mcrar.ml.embedders.loader import probe_audio

pytestmark = pytest.mark.models

KEYS = list(MODELS)
TEXTS = ["a calm piano melody", "heavy metal with distorted guitars", "rain on a window"]


@pytest.fixture(scope="module")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    if not os.environ.get("HF_HOME"):
        pytest.skip("HF_HOME is not set: load the dev env (scripts/with-env.sh) first")
    home = tmp_path_factory.mktemp("home")
    return get_settings(home=home, commercial_mode=False)


@pytest.fixture(scope="module")
def torch_cuda() -> bool:
    torch = pytest.importorskip("torch")
    return bool(torch.cuda.is_available())


@pytest.fixture(scope="module", params=KEYS)
def embedder(request: pytest.FixtureRequest, settings: Settings) -> Iterator[object]:
    pytest.importorskip("torch")
    loaded = load_embedder(request.param, settings=settings)
    yield loaded
    loaded.close()  # type: ignore[attr-defined]


def _clips(embedder: object, n: int = 2) -> list[np.ndarray]:
    sr, window = embedder.sample_rate, embedder.window_s  # type: ignore[attr-defined]
    base = probe_audio(sr, window)
    rng = np.random.default_rng(5)
    return [
        np.roll(base, i * sr // 3) + 0.02 * rng.standard_normal(base.size).astype(np.float32)
        for i in range(n)
    ]


def test_identity_matches_the_registry(embedder: object) -> None:
    spec = MODELS[embedder.key]  # type: ignore[attr-defined]
    assert embedder.model_id == spec.model_id  # type: ignore[attr-defined]
    assert embedder.dim == spec.dim  # type: ignore[attr-defined]
    assert embedder.sample_rate == spec.sample_rate  # type: ignore[attr-defined]
    assert embedder.commercial_ok == spec.commercial_ok  # type: ignore[attr-defined]


def test_audio_embeddings_have_the_right_shape_and_are_unit_norm(embedder: object) -> None:
    out = embedder.embed_audio(_clips(embedder, 3))  # type: ignore[attr-defined]
    assert out.shape == (3, embedder.dim)  # type: ignore[attr-defined]
    assert out.dtype == np.float32
    assert np.isfinite(out).all()
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0, atol=1e-4)


def test_text_embeddings_have_the_right_shape_and_are_unit_norm(embedder: object) -> None:
    out = embedder.embed_text(TEXTS)  # type: ignore[attr-defined]
    assert out.shape == (len(TEXTS), embedder.dim)  # type: ignore[attr-defined]
    assert out.dtype == np.float32
    assert np.isfinite(out).all()
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0, atol=1e-4)
    assert np.abs(out[0] - out[1]).max() > 1e-4  # different prompts give different vectors
    assert embedder.embed_text([]).shape == (0, embedder.dim)  # type: ignore[attr-defined]


def test_audio_and_text_live_in_the_same_space(embedder: object) -> None:
    audio = embedder.embed_audio(_clips(embedder, 2))  # type: ignore[attr-defined]
    text = embedder.embed_text(TEXTS)  # type: ignore[attr-defined]
    assert audio.shape[1] == text.shape[1] == embedder.dim  # type: ignore[attr-defined]
    similarity = audio @ text.T
    assert similarity.shape == (2, len(TEXTS))
    assert np.isfinite(similarity).all() and np.abs(similarity).max() <= 1.0 + 1e-4


def test_embedding_is_deterministic_and_batch_independent(embedder: object) -> None:
    a, b = _clips(embedder, 2)
    together = embedder.embed_audio([a, b])  # type: ignore[attr-defined]
    alone = np.concatenate([embedder.embed_audio([a]), embedder.embed_audio([b])])  # type: ignore[attr-defined]
    assert np.allclose(together, alone, atol=2e-3)
    again = embedder.embed_audio([a])  # type: ignore[attr-defined]
    assert float(again[0] @ alone[0]) > 0.9999


def test_track_embedding_of_a_longer_clip(embedder: object) -> None:
    sr = embedder.sample_rate  # type: ignore[attr-defined]
    track = np.tile(probe_audio(sr, 10.0), 4)  # 40 s
    vector = embed_track(embedder, track, sr)  # type: ignore[arg-type]
    assert vector.shape == (embedder.dim,)  # type: ignore[attr-defined]
    assert np.isfinite(vector).all()
    assert np.linalg.norm(vector) == pytest.approx(1.0, abs=1e-4)
    short = embed_track(embedder, track[: sr * 2], sr)  # type: ignore[arg-type]
    assert np.linalg.norm(short) == pytest.approx(1.0, abs=1e-4)


def test_auto_precision_is_recorded(embedder: object, torch_cuda: bool) -> None:
    if torch_cuda:
        assert embedder.device == "cuda"  # type: ignore[attr-defined]
        if embedder.dtype == "fp16":  # type: ignore[attr-defined]
            assert embedder.fp16_cosine is not None and embedder.fp16_cosine >= 0.99  # type: ignore[attr-defined]
        else:
            assert embedder.fp16_cosine is not None and embedder.fp16_cosine < 0.99  # type: ignore[attr-defined]
    else:
        assert (embedder.device, embedder.dtype) == ("cpu", "fp32")  # type: ignore[attr-defined]


@pytest.mark.parametrize("key", KEYS)
def test_fp16_agrees_with_fp32(key: str, settings: Settings, torch_cuda: bool) -> None:
    if not torch_cuda:
        pytest.skip("needs a CUDA GPU")
    outputs: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for dtype in ("fp32", "fp16"):  # one at a time: GLAP in fp32 takes most of a 6 GB card
        loaded = load_embedder(key, settings=settings, device="cuda", dtype=dtype)
        try:
            assert loaded.dtype == dtype  # type: ignore[attr-defined]
            outputs[dtype] = (
                loaded.embed_audio(_clips(loaded, 2)),
                loaded.embed_text(TEXTS),
            )
        finally:
            loaded.close()  # type: ignore[attr-defined]
    for modality in (0, 1):
        cosines = (outputs["fp32"][modality] * outputs["fp16"][modality]).sum(axis=1)
        assert cosines.min() >= 0.99, (key, modality, cosines)


def test_models_are_cached_under_hf_home(settings: Settings) -> None:
    from mcrar.ml.registry import is_downloaded

    hf_home = Path(os.environ["HF_HOME"])
    for spec in MODELS.values():
        assert is_downloaded(spec, settings) is True
    assert (hf_home / "hub").is_dir()


def test_distinct_prompts_get_distinct_text_embeddings(embedder: object) -> None:
    # Regression guard: the laion/larger_clap_music checkpoint maps every prompt to one vector
    # (pairwise cosine 0.999), which passes the shape/norm checks above but cannot rank anything.
    emb = embedder.embed_text(TEXTS)  # type: ignore[attr-defined]
    sims = emb @ emb.T
    off_diagonal = sims[~np.eye(len(TEXTS), dtype=bool)]
    assert float(off_diagonal.max()) < 0.95
