"""Shared helpers for the search tests (not a test module; unique basename on purpose).

``build_catalog`` fills a repository with a synthetic catalog of 21 tracks whose 8-d embeddings
are blends of a few "concept" axes, so a fake text embedder can point at known tracks:

    axis 0 stealth/tense, 1 happy, 2 epic, 3 calm, 4 rock, 5 jazz, 6 electronic, 7 dark

Nothing here imports torch.
"""

from __future__ import annotations

import io
import zlib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from mcrar.audio import AudioFeatures
from mcrar.catalog import CatalogRepository, TrackRecord
from mcrar.config import Settings, get_settings
from mcrar.ml import MODELS
from mcrar.recommend import SearchService, StoredTagScorer
from mcrar.sources import SourceTrack

DIM = 8
MODEL_ID = MODELS["clap"].model_id
AXES = {
    "stealth": 0,
    "happy": 1,
    "epic": 2,
    "calm": 3,
    "rock": 4,
    "jazz": 5,
    "electronic": 6,
    "dark": 7,
}


def axis(name: str, weight: float = 1.0) -> np.ndarray:
    v = np.zeros(DIM, dtype=np.float32)
    v[AXES[name]] = weight
    return v


@dataclass(frozen=True)
class Spec:
    name: str
    artist: str | None
    blend: dict[str, float]
    bpm: float | None
    conf: float
    energy: float | None
    risk: str
    vocal: str | None
    duration: float | None
    source: str = "jamendo"
    license_code: str = "CC BY 3.0"
    embedded: bool = True
    download: bool = False


SPECS = [
    Spec("Shadow Walk", "Ada", {"stealth": 1.0}, 90, 0.9, 0.30, "green", "instrumental", 120),
    Spec(
        "Quiet Vents",
        "Ada",
        {"stealth": 0.9, "calm": 0.1},
        96,
        0.8,
        0.31,
        "green",
        "instrumental",
        150,
    ),
    Spec(
        "Night Heist",
        "Ada",
        {"stealth": 0.8, "dark": 0.3},
        100,
        0.9,
        0.45,
        "green",
        "instrumental",
        180,
    ),
    Spec(
        "Creeping Dread",
        "Bo",
        {"stealth": 0.7, "dark": 0.5},
        85,
        0.9,
        0.25,
        "amber",
        "instrumental",
        200,
        license_code="CC BY-SA 3.0",
    ),
    Spec(
        "Red Alert",
        "Cy",
        {"stealth": 0.6, "epic": 0.4},
        130,
        0.9,
        0.80,
        "red",
        "vocal",
        180,
        license_code="CC BY-NC 3.0",
    ),
    Spec(
        "Mystery Box",
        "Di",
        {"stealth": 0.5, "happy": 0.3},
        70,
        0.3,
        0.40,
        "unknown",
        None,
        15,
        license_code="Unknown license",
    ),
    Spec("Sunny Day", "Ed", {"happy": 1.0}, 125, 0.9, 0.70, "green", "vocal", 180),
    Spec(
        "Happy Feet", "Ed", {"happy": 0.9, "electronic": 0.2}, 128, 0.9, 0.75, "green", "vocal", 200
    ),
    Spec(
        "Party Time",
        "Fay",
        {"happy": 0.7, "rock": 0.4},
        140,
        0.9,
        0.85,
        "amber",
        "vocal",
        190,
        license_code="CC BY-SA 3.0",
    ),
    Spec(
        "Epic Quest",
        "Gus",
        {"epic": 1.0},
        110,
        0.9,
        0.80,
        "green",
        "instrumental",
        240,
        download=True,
    ),
    Spec("Boss Fight", "Gus", {"epic": 0.8, "rock": 0.3}, 150, 0.9, 0.95, "green", "vocal", 220),
    Spec(
        "Glory March",
        "Hal",
        {"epic": 0.9, "calm": 0.1},
        100,
        0.9,
        0.70,
        "amber",
        "instrumental",
        260,
        license_code="CC BY-SA 3.0",
    ),
    Spec("Lullaby", "Ivy", {"calm": 1.0}, 60, 0.9, 0.10, "green", "instrumental", 300),
    Spec(
        "Ambient Pad",
        "Ivy",
        {"calm": 0.9, "dark": 0.1},
        55,
        0.9,
        0.15,
        "green",
        "instrumental",
        400,
    ),
    Spec("Misty Lake", "Jo", {"calm": 0.8, "jazz": 0.2}, 65, 0.5, 0.20, "green", "vocal", 330),
    Spec(
        "Garage Band",
        "Kim",
        {"rock": 1.0},
        145,
        0.9,
        0.90,
        "amber",
        "vocal",
        170,
        license_code="CC BY-SA 3.0",
    ),
    Spec(
        "Metal Gods",
        "Kim",
        {"rock": 0.8, "dark": 0.3},
        160,
        0.9,
        0.95,
        "red",
        "vocal",
        210,
        license_code="CC BY-NC 3.0",
    ),
    Spec("Smooth Cafe", "Lee", {"jazz": 1.0}, 95, 0.9, 0.35, "green", "instrumental", 250),
    Spec(
        "Chip Hero",
        "Mo",
        {"electronic": 0.9, "epic": 0.2},
        150,
        0.9,
        0.80,
        "green",
        "instrumental",
        90,
        source="local",
        license_code="CC0 1.0",
    ),
    Spec(
        "Local Ambient",
        None,
        {"calm": 0.8, "dark": 0.2},
        None,
        0.0,
        None,
        "unknown",
        None,
        None,
        source="local",
        license_code="Unknown license",
    ),
    Spec(
        "Unembedded Tune",
        "Nan",
        {"stealth": 1.0},
        100,
        0.9,
        0.30,
        "green",
        "instrumental",
        100,
        embedded=False,
    ),
]


def spec_vector(spec: Spec, seed: int) -> np.ndarray:
    """The track's embedding: its blend of axes plus a little deterministic noise."""
    v = sum((axis(n, w) for n, w in spec.blend.items()), np.zeros(DIM, dtype=np.float32))
    v = v + 0.02 * np.random.default_rng(seed).standard_normal(DIM).astype(np.float32)
    return (v / np.linalg.norm(v)).astype(np.float32)


def build_catalog(repo: CatalogRepository, specs: Sequence[Spec] = SPECS) -> dict[str, int]:
    """Insert the tracks, their features and embeddings. Returns title -> track id."""
    ids: dict[str, int] = {}
    for n, spec in enumerate(specs, start=1):
        track_id = repo.upsert_track(
            TrackRecord(
                source=spec.source,
                source_id=str(n),
                title=spec.name,
                artist=spec.artist,
                duration_s=spec.duration,
                source_url=f"https://example.test/{n}",
                download_url=f"https://example.test/{n}/download" if spec.download else None,
                audiodownload_allowed=spec.download,
                license_code=spec.license_code,
                license_url="https://creativecommons.org/licenses/by/3.0/",
                risk=spec.risk,
                vocal_instrumental=spec.vocal,
                attribution_text=f"{spec.name} by {spec.artist}",
            )
        )
        ids[spec.name] = track_id
        if spec.bpm is not None:
            repo.set_features(
                track_id,
                {
                    "bpm": spec.bpm,
                    "bpm_raw": spec.bpm,
                    "bpm_confidence": spec.conf,
                    "key": "C",
                    "mode": "minor",
                    "energy": spec.energy,
                    "analysis_version": "test-v1",
                },
            )
        if spec.embedded:
            repo.set_embedding(track_id, MODEL_ID, spec_vector(spec, n))
    return ids


class MapEmbedder:
    """A text embedder whose vectors for known texts are given; other texts get a stable random
    vector. ``embed_audio`` is not needed by search."""

    def __init__(
        self,
        texts: Mapping[str, Any] | None = None,
        *,
        key: str = "clap",
        model_id: str | None = None,
    ) -> None:
        self.key = key
        self.model_id = model_id or MODELS[key].model_id
        self.dim = DIM
        self.sample_rate = 8000
        self.window_s = 1.0
        self.commercial_ok = True
        self.texts = dict(texts or {})
        self.calls: list[list[str]] = []
        self.closed = False

    def embed_text(self, texts: Sequence[str]) -> np.ndarray:
        self.calls.append(list(texts))
        rows = []
        for t in texts:
            if t in self.texts:
                v = np.asarray(self.texts[t], dtype=np.float32)
            else:
                v = np.random.default_rng(zlib.crc32(t.encode())).standard_normal(DIM)
            rows.append(v / np.linalg.norm(v))
        return np.stack(rows).astype(np.float32)

    def embed_audio(self, clips: Sequence[np.ndarray]) -> np.ndarray:
        """Used by ingest: a stable vector per clip."""
        rows = []
        for clip in clips:
            seed = int(float(np.abs(clip).sum()) * 1000) % (2**32)
            rows.append(np.random.default_rng(seed).standard_normal(DIM) + 0.01)
        arr = np.stack(rows).astype(np.float32)
        return arr / np.linalg.norm(arr, axis=1, keepdims=True)

    def close(self) -> None:
        self.closed = True


QUERY_TEXTS = {
    "tense stealth level": axis("stealth"),
    "happy upbeat tune": axis("happy"),
    "epic battle": axis("epic"),
    "calm ambient pad": axis("calm"),
    "calm": axis("calm"),
    "dark": axis("dark"),
    # zero-shot label prompts ("<display> music")
    "Jazz music": axis("jazz"),
    "Rock music": axis("rock"),
    "Electronic music": axis("electronic"),
    "Calm music": axis("calm"),
    "Dark music": axis("dark"),
    "Happy music": axis("happy"),
    "Epic music": axis("epic"),
}


def catalog_score(probs: Sequence[float], i: int) -> float:
    """The documented standardised tag score of the i-th of the tagged tracks' probabilities
    for one label: ``sigmoid(1.7 * z)`` (0.5 when they are all equal)."""
    values = np.asarray(probs, dtype=np.float64)
    std = values.std()
    z = 0.0 if std < 1e-9 else (values[i] - values.mean()) / std
    return float(1.0 / (1.0 + np.exp(-1.7 * z)))


def make_settings(**search: Any) -> Settings:
    """Settings for the tests; ``search`` overrides ``[search]`` (for example ``pool_size=5``)."""
    base: dict[str, Any] = {"max_per_artist": 50}  # most tests do not want the artist cap
    base.update(search)
    return get_settings(search=base)


def make_service(
    repo: CatalogRepository,
    embedder: MapEmbedder | None = None,
    **search: Any,
) -> tuple[SearchService, MapEmbedder]:
    embedder = embedder or MapEmbedder(QUERY_TEXTS)
    # Stored tags are trusted whatever their model version (the licence gate has its own tests).
    service = SearchService(
        repo,
        make_settings(**search),
        embedder_loader=lambda: embedder,
        stored_tags=StoredTagScorer(repo),
    )
    return service, embedder


# -- ingest stand-ins ----------------------------------------------------------------------------


def write_wav(path: Path, freq: float = 440.0, seconds: float = 3.0, sr: int = 22050) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(round(seconds * sr)) / sr
    sf.write(path, (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32), sr)
    return path


def fake_features(source: object, *, max_seconds: float | None = None) -> AudioFeatures:
    """Replaces ``analyze_audio`` in the ingest pipeline."""
    return AudioFeatures(
        bpm=120.0,
        bpm_raw=120.0,
        bpm_confidence=0.9,
        key="C",
        mode="major",
        key_confidence=0.5,
        loudness_lufs=-14.0,
        rms_db=-20.0,
        energy=0.5,
        duration_s=3.0,
        sample_rate=22050,
        channels=1,
    )


class FakeJamendoClient:
    """Stands in for ``JamendoClient`` in ``mcrar ingest jamendo``: two tracks, synthetic audio."""

    def __init__(self, count: int = 2) -> None:
        buf = io.BytesIO()
        sf.write(buf, np.sin(np.arange(22050) / 20).astype(np.float32) * 0.5, 22050, format="WAV")
        self.audio = buf.getvalue()
        self.count = count
        self.closed = False

    def search_tracks(self, **kwargs: Any) -> Iterator[SourceTrack]:
        return iter(
            SourceTrack(
                source="jamendo",
                source_id=str(n),
                title=f"Track {n}",
                artist=f"Artist {n}",
                stream_url=f"https://audio.example/{n}",
                license_url="https://creativecommons.org/licenses/by/4.0/",
            )
            for n in range(1, self.count + 1)
        )

    def fetch_audio(self, track: SourceTrack, **kwargs: Any) -> bytes:
        return self.audio

    def get_tracks(self, ids: Sequence[str | int], **kwargs: Any) -> list[SourceTrack]:
        return []

    def usage(self) -> dict[str, Any]:
        return {"month": "2026-10", "requests": 1}

    def close(self) -> None:
        self.closed = True


# -- the optional LLM (M7) -------------------------------------------------------------------------


class FakeProvider:
    """A ``LLMProvider`` that returns a canned reply (a dict, an exception to raise, or a function
    of the call) and records every call. No network."""

    def __init__(self, reply: Any = None, *, model: str = "fake-model", models: Any = None) -> None:
        self.reply = reply if reply is not None else {}
        self.model = model
        self.models = models if models is not None else []  # a list of ModelInfo or an exception
        self.label = "Fake"
        self.calls: list[dict[str, Any]] = []
        self.model_calls: list[float] = []  # the timeout of each list_models call
        self.closed = 0

    def complete_json(
        self,
        messages: Any,
        schema: dict[str, Any],
        *,
        name: str,
        max_tokens: int,
        timeout_s: float,
    ) -> dict[str, Any]:
        call = {
            "messages": messages,
            "schema": schema,
            "name": name,
            "max_tokens": max_tokens,
            "timeout_s": timeout_s,
        }
        self.calls.append(call)
        reply = self.reply(call) if callable(self.reply) else self.reply
        if isinstance(reply, Exception):
            raise reply
        return reply

    def list_models(self, *, timeout_s: float) -> list[Any]:
        self.model_calls.append(timeout_s)
        if isinstance(self.models, Exception):
            raise self.models
        return list(self.models)

    def close(self) -> None:
        self.closed += 1


def parse_reply(**fields: Any) -> dict[str, Any]:
    """A complete reply of the query-parsing prompt: nothing found, except what is given."""
    reply: dict[str, Any] = {
        "semantic_text": "",
        "genres": [],
        "moods": [],
        "energy": None,
        "bpm_target": None,
        "vocal": None,
        "duration_min_s": None,
        "duration_max_s": None,
        "search_terms": [],
    }
    reply.update(fields)
    return reply


def llm_settings(**llm: Any) -> Settings:
    """Settings with the LLM enabled on the key-less ``custom`` preset (so no secret is needed)."""
    options = {"enabled": True, "preset": "custom", "model": "fake-model", **llm}
    return get_settings(search={"max_per_artist": 50}, llm=options)


def fake_llm_client(provider: FakeProvider, **llm: Any) -> Any:
    from mcrar.llm.client import LLMClient

    return LLMClient(llm_settings(**llm), None, provider_factory=lambda *args: provider)
