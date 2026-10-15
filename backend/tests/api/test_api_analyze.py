"""POST /api/analyze: a reference-track upload is analysed in memory and nothing is stored."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from api_support import ApiClient, make_client

from mcrar.api.routes import analyze as analyze_routes


def wav_bytes(seconds: float = 2.0, sr: int = 22050) -> bytes:
    t = np.arange(int(seconds * sr)) / sr
    samples = (np.sin(2 * np.pi * 220 * t) * 0.3).astype(np.float32)
    samples[:: sr // 2] += 0.5  # a click twice a second
    buffer = io.BytesIO()
    sf.write(buffer, samples, sr, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


def upload(client: ApiClient, name: str, data: bytes):
    return client.post("/api/analyze", files={"file": (name, data, "application/octet-stream")})


def test_a_wav_is_analysed(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = upload(client, "ref.wav", wav_bytes())
    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "ref.wav"
    features = body["features"]
    assert {"bpm", "key", "mode", "energy", "loudness_lufs", "duration_s"} <= set(features)
    assert features["duration_s"] == pytest.approx(2.0, abs=0.05)
    assert features["sample_rate"] == 22050


def test_only_the_base_name_is_returned(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        for sent in ("../../etc/ref.wav", "C:\\Users\\me\\music\\ref.wav", "/abs/dir/ref.wav"):
            assert upload(client, sent, wav_bytes(1.0)).json()["filename"] == "ref.wav"


def test_nothing_is_stored(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        home = client.app.state.mcrar.settings.home
        files = sorted(tmp_path.rglob("*")), sorted(home.rglob("*"))
        assert upload(client, "ref.wav", wav_bytes(1.0)).status_code == 200
        assert (sorted(tmp_path.rglob("*")), sorted(home.rglob("*"))) == files


@pytest.mark.parametrize("name", ["notes.txt", "ref", "ref.exe", "ref.wav.txt", ""])
def test_a_wrong_extension_is_422(tmp_path: Path, name: str) -> None:
    with make_client(tmp_path) as client:
        response = upload(client, name, wav_bytes(1.0))
    assert response.status_code == 422


def test_an_oversized_upload_is_413(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = wav_bytes(1.0)
    monkeypatch.setattr(analyze_routes, "MAX_UPLOAD_BYTES", len(data) - 1)
    with make_client(tmp_path) as client:
        assert upload(client, "ref.wav", data).status_code == 413
        monkeypatch.setattr(analyze_routes, "MAX_UPLOAD_BYTES", len(data))
        assert upload(client, "ref.wav", data).status_code == 200


def test_the_limit_is_50_megabytes() -> None:
    assert analyze_routes.MAX_UPLOAD_BYTES == 50 * 1024 * 1024


def test_corrupt_audio_is_422_with_the_audio_error_message(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = upload(client, "ref.wav", b"this is not audio at all")
    assert response.status_code == 422
    assert response.json()["detail"]


def test_a_missing_file_part_is_422(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert client.post("/api/analyze", data={"x": "y"}).status_code == 422
