"""`mcrar embed`, `mcrar models ...` and `--embed` through the CLI runner, with fake embedders."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ml_support import FakeEmbedder, FakeJamendo, add_jamendo, add_local, write_wav
from typer.testing import CliRunner

from mcrar import cli
from mcrar.audio import AudioFeatures
from mcrar.catalog import open_catalog
from mcrar.cli import app
from mcrar.config import get_settings
from mcrar.ingest import pipeline
from mcrar.ml import MODELS, EmbedderMemoryError, ModelLoadError
from mcrar.secrets import SecretError
from mcrar.sources import SourceTrack

runner = CliRunner()


DIMS = {"clap": 8, "glap": 9, "muq-mulan": 10}


class Loader:
    """Replaces ``cli._load_embedder``: builds fakes with the real models' ids and records calls."""

    def __init__(self, errors: dict[str, Exception] | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.loaded: list[FakeEmbedder] = []
        self.errors = errors or {}

    def __call__(self, key: str, settings: object, **kwargs: object) -> FakeEmbedder:
        self.calls.append((key, kwargs))
        if key in self.errors:
            raise self.errors[key]
        spec = MODELS[key]
        embedder = FakeEmbedder(
            key, dim=DIMS[key], revision=spec.revision, sample_rate=8000, window_s=1.0
        )
        self.loaded.append(embedder)
        return embedder


@pytest.fixture
def loader(monkeypatch: pytest.MonkeyPatch) -> Loader:
    fake = Loader()
    monkeypatch.setattr(cli, "_load_embedder", fake)
    return fake


@pytest.fixture
def no_torch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any attempt to load a real model fails loudly."""

    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("a real model must not be loaded")

    monkeypatch.setattr(cli, "_load_embedder", boom)


def _stats() -> dict:
    result = runner.invoke(app, ["catalog", "stats", "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def _local_catalog(tmp_path: Path, count: int = 3) -> None:
    with open_catalog(get_settings()) as repo:
        for n in range(count):
            add_local(
                repo, f"{n}.wav", write_wav(tmp_path / "lib" / f"{n}.wav", freq=200.0 * (n + 1))
            )


def _fake_features(source: object, *, max_seconds: float | None = None) -> AudioFeatures:
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


# -- help and models list ------------------------------------------------------------------------


def test_help_lists_the_new_commands() -> None:
    top = runner.invoke(app, ["--help"])
    assert top.exit_code == 0
    assert "embed" in top.output and "models" in top.output
    sub = runner.invoke(app, ["models", "--help"])
    assert "list" in sub.output and "benchmark" in sub.output


def test_models_list_in_commercial_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    downloaded = {"clap": True, "glap": False, "muq-mulan": True}
    monkeypatch.setattr(
        "mcrar.ml.registry.is_downloaded", lambda spec, settings: downloaded[spec.key]
    )
    result = runner.invoke(app, ["models", "list"])
    assert result.exit_code == 0, result.output
    rows = {line.split()[0]: line.split() for line in result.output.splitlines()[1:4]}
    assert result.output.splitlines()[0].split() == [
        "KEY", "MODEL", "ID", "LICENSE", "COMMERCIAL", "ALLOWED", "DOWNLOADED"
    ]  # fmt: skip
    assert rows["clap"] == ["clap", "clap@195c3a3", "Apache-2.0", "yes", "yes", "yes"]
    assert rows["glap"] == ["glap", "glap@79b1301", "Apache-2.0", "yes", "yes", "no"]
    assert rows["muq-mulan"] == [
        "muq-mulan",
        "muq-mulan@2e01c79",
        "CC-BY-NC-4.0",
        "no",
        "no",
        "yes",
    ]
    assert "Commercial mode is on" in result.output
    assert "MCRAR_COMMERCIAL_MODE=false" in result.output


def test_models_list_with_commercial_mode_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCRAR_COMMERCIAL_MODE", "false")
    monkeypatch.setattr("mcrar.ml.registry.is_downloaded", lambda spec, settings: None)
    result = runner.invoke(app, ["models", "list"])
    assert result.exit_code == 0, result.output
    muq = next(line for line in result.output.splitlines() if line.startswith("muq-mulan"))
    assert muq.split()[3:6] == ["no", "yes", "unknown"]  # not commercial, but allowed now
    assert "Commercial mode is off" in result.output


# -- the commercial gate -------------------------------------------------------------------------


def test_embed_refuses_a_non_commercial_model_in_commercial_mode(no_torch: None) -> None:
    result = runner.invoke(app, ["embed", "--models", "muq-mulan"])
    assert result.exit_code == 1
    assert result.output.startswith("error: model 'muq-mulan'")
    assert "MCRAR_COMMERCIAL_MODE=false" in result.output
    assert "Traceback" not in result.output


def test_embed_allows_it_when_commercial_mode_is_off(
    monkeypatch: pytest.MonkeyPatch, loader: Loader, tmp_path: Path
) -> None:
    monkeypatch.setenv("MCRAR_COMMERCIAL_MODE", "false")
    _local_catalog(tmp_path, 1)
    result = runner.invoke(app, ["embed", "--models", "muq-mulan"])
    assert result.exit_code == 0, result.output
    assert [key for key, _ in loader.calls] == ["muq-mulan"]


def test_ingest_embed_checks_the_gate_before_doing_any_work(tmp_path: Path, no_torch: None) -> None:
    write_wav(tmp_path / "lib" / "a.wav")
    result = runner.invoke(app, ["ingest", "local", str(tmp_path / "lib"), "--embed", "muq-mulan"])
    assert result.exit_code == 1
    assert "MCRAR_COMMERCIAL_MODE=false" in result.output
    assert _stats()["tracks"] == 0  # nothing was ingested


def test_embed_rejects_unknown_models_and_sources(no_torch: None) -> None:
    unknown = runner.invoke(app, ["embed", "--models", "clap,nope"])
    assert unknown.exit_code == 2
    assert "unknown model 'nope'" in unknown.output
    bad_source = runner.invoke(app, ["embed", "--source", "spotify"])
    assert bad_source.exit_code == 2
    assert "--source must be one of: jamendo, local" in bad_source.output


# -- mcrar embed ---------------------------------------------------------------------------------


def test_embed_runs_every_selected_model_in_one_pass(
    loader: Loader, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _local_catalog(tmp_path, 3)
    result = runner.invoke(app, ["embed", "--models", "clap,glap", "--batch-size", "4"])
    assert result.exit_code == 0, result.output
    assert [key for key, _ in loader.calls] == ["clap", "glap"]  # each loaded once
    assert all(
        kwargs["batch_size"] == 4 and kwargs["device"] == "auto" for _, kwargs in loader.calls
    )
    assert "Loading clap ..." in result.output and "clap@195c3a3" in result.output
    assert "[1/3] ok  0.wav — embed:clap, embed:glap (unknown)" in result.output
    assert "3 seen (0 new, 0 updated), 3 processed, 0 skipped, 0 failed" in result.output
    assert all(e.closed for e in loader.loaded)  # models are released
    # one decode and one batch per track and model
    assert [len(e.audio_calls) for e in loader.loaded] == [3, 3]
    embeddings = _stats()["embeddings_by_model"]
    assert embeddings == {"clap@195c3a3": 3, "glap@79b1301": 3}

    shown = runner.invoke(app, ["catalog", "stats"])
    assert "Embeddings:       clap@195c3a3=3, glap@79b1301=3" in shown.output


def test_embed_defaults_to_the_default_embedder_setting(loader: Loader, tmp_path: Path) -> None:
    _local_catalog(tmp_path, 1)
    result = runner.invoke(app, ["embed"])
    assert result.exit_code == 0, result.output
    assert [key for key, _ in loader.calls] == ["clap"]


def test_embed_default_embedder_comes_from_settings(
    loader: Loader, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _local_catalog(tmp_path, 1)
    monkeypatch.setenv("MCRAR_DEFAULT_EMBEDDER", "glap")
    result = runner.invoke(app, ["embed"])
    assert result.exit_code == 0, result.output
    assert [key for key, _ in loader.calls] == ["glap"]


def test_embed_non_commercial_default_is_refused_in_commercial_mode(
    loader: Loader, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _local_catalog(tmp_path, 1)
    monkeypatch.setenv("MCRAR_DEFAULT_EMBEDDER", "muq-mulan")
    result = runner.invoke(app, ["embed"])
    assert result.exit_code == 1
    assert loader.calls == []


def test_embed_with_everything_current_loads_no_model(loader: Loader, tmp_path: Path) -> None:
    _local_catalog(tmp_path, 2)
    assert runner.invoke(app, ["embed", "--models", "clap"]).exit_code == 0
    loader.calls.clear()
    again = runner.invoke(app, ["embed", "--models", "clap"])
    assert again.exit_code == 0
    assert "Nothing to embed" in again.output
    assert loader.calls == []
    # a new model has work to do for the same tracks
    third = runner.invoke(app, ["embed", "--models", "clap,glap"])
    assert third.exit_code == 0
    assert "2 processed" in third.output


def test_embed_force_limit_and_source(loader: Loader, tmp_path: Path) -> None:
    _local_catalog(tmp_path, 3)
    with open_catalog(get_settings()) as repo:
        add_jamendo(repo, 99)
    limited = runner.invoke(app, ["embed", "--models", "clap", "--source", "local", "--limit", "2"])
    assert limited.exit_code == 0, limited.output
    assert "2 seen" in limited.output and "2 processed" in limited.output
    assert _stats()["embeddings_by_model"] == {"clap@195c3a3": 2}
    forced = runner.invoke(app, ["embed", "--models", "clap", "--source", "local", "--force"])
    assert "3 processed" in forced.output  # all local tracks again


def test_embed_refreshes_jamendo_urls_through_the_client(
    monkeypatch: pytest.MonkeyPatch, loader: Loader
) -> None:
    with open_catalog(get_settings()) as repo:
        for n in range(1, 4):
            add_jamendo(repo, n)
    client = FakeJamendo()
    monkeypatch.setattr(cli, "_jamendo_client", lambda settings, use_cache: client)
    result = runner.invoke(app, ["embed", "--models", "clap"])
    assert result.exit_code == 0, result.output
    assert client.get_calls == [["1", "2", "3"]]
    assert "3 processed" in result.output


def test_embed_does_not_need_jamendo_credentials_for_local_only_work(
    monkeypatch: pytest.MonkeyPatch, loader: Loader, tmp_path: Path
) -> None:
    def no_client(settings: object, use_cache: bool) -> None:
        raise AssertionError("no Jamendo client is needed")

    monkeypatch.setattr(cli, "_jamendo_client", no_client)
    _local_catalog(tmp_path, 1)
    assert runner.invoke(app, ["embed", "--models", "clap"]).exit_code == 0


def test_embed_reports_missing_jamendo_credentials(
    monkeypatch: pytest.MonkeyPatch, loader: Loader
) -> None:
    with open_catalog(get_settings()) as repo:
        add_jamendo(repo, 1)

    def no_credentials(settings: object, use_cache: bool) -> None:
        raise SecretError("secret 'jamendo_client_id' is not set")

    monkeypatch.setattr(cli, "_jamendo_client", no_credentials)
    result = runner.invoke(app, ["embed", "--models", "clap"])
    assert result.exit_code == 1
    assert "jamendo_client_id" in result.output and "--source local" in result.output
    assert loader.calls == []  # no model was loaded for nothing


def test_embed_prints_failures_and_still_exits_zero(loader: Loader, tmp_path: Path) -> None:
    _local_catalog(tmp_path, 2)
    with open_catalog(get_settings()) as repo:
        add_local(repo, "gone.wav", tmp_path / "gone.wav")
    result = runner.invoke(app, ["embed", "--models", "clap"])
    assert result.exit_code == 0, result.output
    assert "2 processed, 0 skipped, 1 failed" in result.output
    assert "failed [embed:clap] gone.wav" in result.output
    assert _stats()["ingest_failures_by_stage"] == {"embed:clap": 1}


def test_embed_reports_model_load_errors_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _local_catalog(tmp_path, 1)
    loader = Loader(errors={"glap": ModelLoadError("could not download mispeech/GLAP@79b1301")})
    monkeypatch.setattr(cli, "_load_embedder", loader)
    result = runner.invoke(app, ["embed", "--models", "clap,glap"])
    assert result.exit_code == 1
    assert "error: could not download mispeech/GLAP@79b1301" in result.output
    assert "Traceback" not in result.output
    assert loader.loaded[0].closed  # the model loaded before the failure is released


def test_embed_explains_what_to_do_when_the_models_do_not_fit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _local_catalog(tmp_path, 1)
    message = "not enough GPU memory to load 'glap'. Pass fewer models with --models"
    monkeypatch.setattr(
        cli, "_load_embedder", Loader(errors={"glap": EmbedderMemoryError(message)})
    )
    result = runner.invoke(app, ["embed", "--models", "clap,glap"])
    assert result.exit_code == 1
    assert "Pass fewer models with --models" in result.output


def test_embed_wraps_unexpected_load_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _local_catalog(tmp_path, 1)
    monkeypatch.setattr(
        cli, "_load_embedder", Loader(errors={"clap": RuntimeError("secret detail")})
    )
    result = runner.invoke(app, ["embed", "--models", "clap"])
    assert result.exit_code == 1
    assert "error: could not load model 'clap' (RuntimeError)" in result.output
    assert "secret detail" not in result.output


def test_embed_on_an_empty_catalog(loader: Loader) -> None:
    result = runner.invoke(app, ["embed", "--models", "clap"])
    assert result.exit_code == 0
    assert "Nothing to embed" in result.output
    assert loader.calls == []


# -- ingest --embed ------------------------------------------------------------------------------


def test_ingest_local_embed_adds_embedding_stages(
    loader: Loader, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "analyze_audio", _fake_features)
    write_wav(tmp_path / "lib" / "a.wav", freq=300.0)
    write_wav(tmp_path / "lib" / "b.wav", freq=700.0)
    result = runner.invoke(app, ["ingest", "local", str(tmp_path / "lib"), "--embed", "clap,glap"])
    assert result.exit_code == 0, result.output
    assert "2 processed" in result.output
    assert "120 BPM C major" in result.output  # analysis still runs
    stats = _stats()
    assert stats["features"]["tracks_with_features"] == 2
    assert stats["embeddings_by_model"] == {"clap@195c3a3": 2, "glap@79b1301": 2}
    assert all(e.closed for e in loader.loaded)


def test_ingest_local_without_embed_never_touches_the_loader(
    no_torch: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "analyze_audio", _fake_features)
    write_wav(tmp_path / "lib" / "a.wav")
    result = runner.invoke(app, ["ingest", "local", str(tmp_path / "lib")])
    assert result.exit_code == 0, result.output
    assert _stats()["embeddings_by_model"] == {}


def test_ingest_local_embed_reports_a_load_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(pipeline, "analyze_audio", _fake_features)
    monkeypatch.setattr(
        cli,
        "_load_embedder",
        Loader(errors={"clap": ModelLoadError("could not load model 'clap'")}),
    )
    write_wav(tmp_path / "lib" / "a.wav")
    result = runner.invoke(app, ["ingest", "local", str(tmp_path / "lib"), "--embed", "clap"])
    assert result.exit_code == 1
    assert "error: could not load model 'clap'" in result.output


def test_ingest_jamendo_embed_adds_embedding_stages(
    loader: Loader, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "analyze_audio", _fake_features)

    class Client(FakeJamendo):
        def search_tracks(self, **kwargs: object):  # noqa: ANN202
            return iter(
                [
                    SourceTrack(
                        source="jamendo",
                        source_id=str(n),
                        title=f"Track {n}",
                        artist="A",
                        stream_url=f"https://audio.example/{n}",
                        license_url="https://creativecommons.org/licenses/by/4.0/",
                    )
                    for n in (1, 2)
                ]
            )

        def usage(self) -> dict:
            return {"month": "2026-10", "requests": 1}

    client = Client()
    monkeypatch.setattr(cli, "_jamendo_client", lambda settings, use_cache: client)
    result = runner.invoke(app, ["ingest", "jamendo", "--limit", "2", "--embed", "glap"])
    assert result.exit_code == 0, result.output
    assert [key for key, _ in loader.calls] == ["glap"]
    assert _stats()["embeddings_by_model"] == {"glap@79b1301": 2}


# -- mcrar models benchmark ----------------------------------------------------------------------


def test_models_benchmark_prints_one_row_per_model(
    loader: Loader, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = runner.invoke(app, ["models", "benchmark", "--models", "clap,glap", "--seconds", "4"])
    assert result.exit_code == 0, result.output
    header, *rows = [line for line in result.output.splitlines() if "@" in line or "load s" in line]
    assert header.split() == [
        "model", "load", "s", "device", "dtype", "peak", "MB", "weights", "MB", "audio", "s/s",
        "text/s", "dim",
    ]  # fmt: skip
    assert [r.split()[0] for r in rows] == ["clap@195c3a3", "glap@79b1301"]
    assert rows[0].split()[2:4] == ["cpu", "fp32"]
    assert rows[0].split()[4] == "n/a"  # no CUDA stats for a CPU fake
    assert rows[0].split()[-1] == "8" and rows[1].split()[-1] == "9"  # dims of the two fakes
    assert float(rows[0].split()[-3]) > 0  # audio throughput
    assert float(rows[0].split()[-2]) > 0  # text throughput
    assert all(e.closed for e in loader.loaded)


def test_models_benchmark_keeps_going_after_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    loader = Loader(
        errors={"clap": ModelLoadError("could not download laion/larger_clap_music_and_speech")}
    )
    monkeypatch.setattr(cli, "_load_embedder", loader)
    result = runner.invoke(app, ["models", "benchmark", "--models", "clap,glap", "--seconds", "2"])
    assert result.exit_code == 1
    assert "failed: could not download laion/larger_clap_music_and_speech" in result.output
    assert "glap@79b1301" in result.output  # the second model was still measured
    assert "1 model(s) failed" in result.output


def test_models_benchmark_refuses_non_commercial_models(no_torch: None) -> None:
    result = runner.invoke(app, ["models", "benchmark", "--models", "muq-mulan"])
    assert result.exit_code == 1
    assert "MCRAR_COMMERCIAL_MODE=false" in result.output
