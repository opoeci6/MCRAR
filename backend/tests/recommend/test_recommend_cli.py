"""`mcrar search`, and what `mcrar ingest` embeds by default, through the CLI runner."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
from recommend_support import (
    MODEL_ID,
    QUERY_TEXTS,
    FakeJamendoClient,
    MapEmbedder,
    build_catalog,
    fake_features,
    write_wav,
)
from typer.testing import CliRunner

from mcrar import cli
from mcrar.catalog import open_catalog
from mcrar.cli import app
from mcrar.config import get_settings
from mcrar.ingest import pipeline
from mcrar.ml import ModelLoadError

runner = CliRunner()


class Loader:
    """Replaces ``cli._load_embedder``: hands out fake embedders and records the requests."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[str] = []
        self.loaded: list[MapEmbedder] = []
        self.error = error

    def __call__(self, key: str, settings: object, **kwargs: object) -> MapEmbedder:
        self.calls.append(key)
        if self.error is not None:
            raise self.error
        embedder = MapEmbedder(QUERY_TEXTS, key=key)
        self.loaded.append(embedder)
        return embedder


@pytest.fixture
def loader(monkeypatch: pytest.MonkeyPatch) -> Loader:
    fake = Loader()
    monkeypatch.setattr(cli, "_load_embedder", fake)
    return fake


@pytest.fixture
def catalog() -> dict[str, int]:
    """The synthetic catalog in the (temporary) catalog the CLI opens."""
    with open_catalog(get_settings()) as repo:
        return build_catalog(repo)


def stats() -> dict:
    result = runner.invoke(app, ["catalog", "stats", "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


# -- search --------------------------------------------------------------------------------------


def test_search_prints_a_table_explanations_and_notes(
    loader: Loader, catalog: dict[str, int]
) -> None:
    result = runner.invoke(
        app, ["search", "tense stealth level, no vocals", "--max-risk", "amber", "--limit", "3"]
    )
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    header = lines[0].split()
    assert header[:2] == ["#", "Title"] and header[-1] == "URL"
    rows = [line for line in lines if line[:1].isdigit() and " — " in line]
    assert len(rows) == 3
    assert rows[0].split("  ")[0].strip() == "1"
    assert "Shadow Walk — Ada" in rows[0] and "[green] CC BY 3.0" in rows[0]
    assert "https://example.test/1" in rows[0] and "C minor" in rows[0] and "0.30" in rows[0]
    assert "Quiet Vents — Ada" in rows[1]
    assert '1. Close match for "tense stealth level" · instrumental · CC BY 3.0 (green)' in (
        result.stdout
    )
    assert "Understood: instrumental only" in result.stdout
    assert "1 matching track(s) have no clap@195c3a3 embedding" in result.stdout
    assert "mcrar embed" in result.stdout
    assert "3 shown of" in result.stdout
    assert "Loading clap ..." in result.stderr and "Loading" not in result.stdout
    assert loader.calls == ["clap"]
    assert all(e.closed for e in loader.loaded)


def test_search_no_explain_drops_the_explanation_lines(
    loader: Loader, catalog: dict[str, int]
) -> None:
    result = runner.invoke(app, ["search", "epic battle", "--limit", "2", "--no-explain"])
    assert result.exit_code == 0, result.output
    assert "Epic Quest — Gus" in result.stdout
    assert "match for" not in result.stdout


def test_search_json_is_pure_json_on_stdout(loader: Loader, catalog: dict[str, int]) -> None:
    result = runner.invoke(
        app,
        ["search", "epic battle", "--max-risk", "green", "--limit", "2", "--offset", "1", "--json"],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)  # nothing but JSON on stdout
    assert [i["title"] for i in data["items"]][0] != "Epic Quest"  # offset 1 skipped the best
    assert len(data["items"]) == 2
    assert data["model_id"] == MODEL_ID and data["unembedded_count"] == 1
    item = data["items"][0]
    assert {"breakdown", "explanation", "top_tags", "score", "risk", "download_url"} <= set(item)
    assert item["risk"] == "green"
    assert data["parsed"]["filters"]["max_risk"] == "green"
    assert data["parsed"]["semantic_text"] == "epic battle"
    assert data["total_candidates"] > 2


def test_search_with_filters_only_never_loads_the_model(
    monkeypatch: pytest.MonkeyPatch, catalog: dict[str, int]
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("a filter-only search must not load a model")

    monkeypatch.setattr(cli, "_load_embedder", boom)
    result = runner.invoke(app, ["search", "", "--bpm", "120-130", "--vocal", "--limit", "5"])
    assert result.exit_code == 0, result.output
    for title in ("Sunny Day", "Happy Feet", "Red Alert"):
        assert title in result.stdout
    assert "Matches your filters" in result.stdout


def test_search_with_no_text_argument_at_all(
    monkeypatch: pytest.MonkeyPatch, catalog: dict[str, int]
) -> None:
    monkeypatch.setattr(cli, "_load_embedder", lambda *a, **k: pytest.fail("no model"))
    result = runner.invoke(app, ["search", "--instrumental", "--duration", "0-100"])
    assert result.exit_code == 0, result.output
    assert "Chip Hero" in result.stdout


def test_search_shows_what_was_relaxed(loader: Loader, catalog: dict[str, int]) -> None:
    result = runner.invoke(app, ["search", "", "--bpm", "300-310", "--instrumental"])
    assert result.exit_code == 0, result.output
    assert "Relaxed the BPM range (300-310) to a target of ~305 BPM" in result.stdout
    assert loader.calls == []  # still no text, so no model


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["--bpm", "90"], {"bpm_min": 80.0, "bpm_max": 100.0}),
        (["--bpm", "80-100"], {"bpm_min": 80.0, "bpm_max": 100.0}),
        (["--bpm", "100-"], {"bpm_min": 100.0, "bpm_max": None}),
        (["--duration", "0-30"], {"duration_min_s": None, "duration_max_s": 30.0}),
        (["--duration", "30"], {"duration_min_s": None, "duration_max_s": 30.0}),
        (["--duration", "60-120"], {"duration_min_s": 60.0, "duration_max_s": 120.0}),
        (["--source", "local"], {"sources": ["local"]}),
        (["--instrumental"], {"vocal": "instrumental"}),
        (["--vocal"], {"vocal": "vocal"}),
        (["--max-risk", "red"], {"max_risk": "red"}),
        (["--genre", "Jazz,hip hop"], {"genres": ["jazz", "hip-hop"]}),
        (["--mood", "spooky"], {"moods": ["dark"]}),
    ],
)
def test_search_options_become_filters(
    loader: Loader, catalog: dict[str, int], args: list[str], expected: dict
) -> None:
    result = runner.invoke(app, ["search", "epic battle", "--json", "--limit", "1", *args])
    assert result.exit_code == 0, result.output
    filters = json.loads(result.stdout)["parsed"]["filters"]
    for key, value in expected.items():
        assert filters[key] == value


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--genre", "polka"], "error: unknown genre label 'polka'; choose from: blues"),
        (["--mood", "jazz"], "error: unknown moodtheme label 'jazz'"),
        (["--bpm", "fast"], "error: --bpm must look like 80-100 or 90"),
        (["--bpm", "120-80"], "error: --bpm: the first number must not exceed the second"),
        (["--duration", "x-3"], "error: --duration must look like"),
        (["--instrumental", "--vocal"], "error: --vocal and --instrumental are mutually exclusive"),
        (["--max-risk", "purple"], "error: --max-risk must be one of: green, amber, red"),
        (["--source", "spotify"], "error: --source must be one of: jamendo, local"),
        ([], "error: give a search text or at least one filter"),
    ],
)
def test_search_rejects_bad_arguments(
    loader: Loader, catalog: dict[str, int], args: list[str], message: str
) -> None:
    result = runner.invoke(app, ["search", *args])
    assert result.exit_code == 2
    assert message in result.stderr
    assert "Traceback" not in result.output
    assert loader.calls == []


def test_search_on_a_missing_catalog_does_not_create_one(loader: Loader) -> None:
    result = runner.invoke(app, ["search", "epic battle"])
    assert result.exit_code == 1
    assert "error: the catalog is empty" in result.stderr
    assert not (get_settings().data_dir / "catalog.db").exists()


def test_search_reports_a_model_that_cannot_load(
    monkeypatch: pytest.MonkeyPatch, catalog: dict[str, int]
) -> None:
    monkeypatch.setattr(
        cli, "_load_embedder", Loader(ModelLoadError("could not load model 'clap'"))
    )
    result = runner.invoke(app, ["search", "epic battle"])
    assert result.exit_code == 1
    assert "error: could not load model 'clap'" in result.stderr
    assert "Traceback" not in result.output


def test_search_with_no_matches_says_why(loader: Loader, catalog: dict[str, int]) -> None:
    result = runner.invoke(
        app, ["search", "epic battle", "--max-risk", "green", "--source", "local", "--vocal"]
    )
    assert result.exit_code == 0, result.output
    assert "Relaxed the vocal filter (vocal only)" in result.stdout  # Chip Hero is instrumental
    assert "Chip Hero" in result.stdout
    empty = runner.invoke(
        app, ["search", "", "--max-risk", "green", "--source", "local", "--bpm", "1-2"]
    )
    assert "Relaxed the BPM range" in empty.stdout


def test_search_instrumental_keeps_local_tracks_with_no_vocal_flag(
    monkeypatch: pytest.MonkeyPatch, catalog: dict[str, int]
) -> None:
    monkeypatch.setattr(cli, "_load_embedder", lambda *a, **k: pytest.fail("no model"))
    result = runner.invoke(app, ["search", "", "--instrumental", "--source", "local"])
    assert result.exit_code == 0, result.output
    assert "Local Ambient" in result.stdout and "Chip Hero" in result.stdout
    assert "vocals unknown" in result.stdout  # said in the explanation of the flagless track
    data = json.loads(runner.invoke(app, ["search", "", "--vocal", "--json"]).stdout)
    assert "Local Ambient" in {i["title"] for i in data["items"]}  # unknown passes either way


def test_search_without_preferences_lists_safer_licences_first(
    monkeypatch: pytest.MonkeyPatch, catalog: dict[str, int]
) -> None:
    monkeypatch.setattr(cli, "_load_embedder", lambda *a, **k: pytest.fail("no model"))
    args = ["search", "", "--vocal", "--json", "--limit", "50"]
    risks = [i["risk"] for i in json.loads(runner.invoke(app, args).stdout)["items"]]
    order = ["green", "amber", "red", "unknown"]
    assert risks == sorted(risks, key=order.index)
    assert risks[0] == "green" and "red" in risks


def test_search_help_lists_the_options() -> None:
    result = runner.invoke(app, ["search", "--help"])
    assert result.exit_code == 0
    options = "--genre --mood --bpm --instrumental --vocal --max-risk --duration --source".split()
    options += "--limit --offset --json --no-explain".split()
    for option in options:
        assert option in result.output


# -- ingest embeds by default ----------------------------------------------------------------------


@pytest.fixture
def library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(pipeline, "analyze_audio", fake_features)
    write_wav(tmp_path / "lib" / "a.wav", freq=300.0)
    write_wav(tmp_path / "lib" / "b.wav", freq=700.0)
    return tmp_path / "lib"


def test_ingest_local_embeds_with_the_default_embedder(loader: Loader, library: Path) -> None:
    result = runner.invoke(app, ["ingest", "local", str(library)])
    assert result.exit_code == 0, result.output
    assert loader.calls == ["clap"]  # Settings.default_embedder
    data = stats()
    assert data["features"]["tracks_with_features"] == 2
    assert data["embeddings_by_model"] == {MODEL_ID: 2}
    assert all(e.closed for e in loader.loaded)


def test_ingest_default_follows_the_default_embedder_setting(
    loader: Loader, library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCRAR_DEFAULT_EMBEDDER", "glap")
    assert runner.invoke(app, ["ingest", "local", str(library)]).exit_code == 0
    assert loader.calls == ["glap"]
    assert list(stats()["embeddings_by_model"]) == ["glap@79b1301"]


def test_ingest_embed_overrides_the_model_list(loader: Loader, library: Path) -> None:
    result = runner.invoke(app, ["ingest", "local", str(library), "--embed", "clap,glap"])
    assert result.exit_code == 0, result.output
    assert loader.calls == ["clap", "glap"]
    assert set(stats()["embeddings_by_model"]) == {"clap@195c3a3", "glap@79b1301"}


def test_ingest_no_embed_analyses_only(monkeypatch: pytest.MonkeyPatch, library: Path) -> None:
    monkeypatch.setattr(cli, "_load_embedder", lambda *a, **k: pytest.fail("no model"))
    result = runner.invoke(app, ["ingest", "local", str(library), "--no-embed"])
    assert result.exit_code == 0, result.output
    data = stats()
    assert data["features"]["tracks_with_features"] == 2 and data["embeddings_by_model"] == {}
    assert result.stderr == ""


def test_ingest_embed_and_no_embed_conflict(loader: Loader, library: Path) -> None:
    result = runner.invoke(app, ["ingest", "local", str(library), "--embed", "clap", "--no-embed"])
    assert result.exit_code == 2
    assert "error: --embed and --no-embed are mutually exclusive" in result.stderr
    assert stats()["tracks"] == 0


def test_ingest_without_the_ml_extra_warns_and_analyses_only(
    monkeypatch: pytest.MonkeyPatch, library: Path
) -> None:
    monkeypatch.setattr(cli, "_torch_available", lambda: False)
    monkeypatch.setattr(cli, "_load_embedder", lambda *a, **k: pytest.fail("no model"))
    result = runner.invoke(app, ["ingest", "local", str(library)])
    assert result.exit_code == 0, result.output
    warnings = [line for line in result.stderr.splitlines() if line.startswith("warning:")]
    assert len(warnings) == 1 and "torch is not installed" in warnings[0]
    assert "uv sync --extra ml" in warnings[0]
    assert "2 processed" in result.stdout
    data = stats()
    assert data["features"]["tracks_with_features"] == 2 and data["embeddings_by_model"] == {}


def test_an_explicit_embed_still_fails_without_the_ml_extra_loading(
    monkeypatch: pytest.MonkeyPatch, library: Path
) -> None:
    """`--embed` is an explicit request: a load failure is an error, not a warning."""
    monkeypatch.setattr(cli, "_torch_available", lambda: False)
    monkeypatch.setattr(
        cli, "_load_embedder", Loader(ModelLoadError("could not load model 'clap'"))
    )
    result = runner.invoke(app, ["ingest", "local", str(library), "--embed", "clap"])
    assert result.exit_code == 1
    assert "error: could not load model 'clap'" in result.stderr


def test_ingest_jamendo_embeds_by_default_too(
    loader: Loader, library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeJamendoClient()
    monkeypatch.setattr(cli, "_jamendo_client", lambda settings, use_cache: client)
    result = runner.invoke(app, ["ingest", "jamendo", "--limit", "2"])
    assert result.exit_code == 0, result.output
    assert loader.calls == ["clap"]
    assert stats()["embeddings_by_model"] == {MODEL_ID: 2}
    off = runner.invoke(app, ["ingest", "jamendo", "--limit", "2", "--no-embed", "--force"])
    assert off.exit_code == 0 and loader.calls == ["clap"]


# -- the M3b hook ----------------------------------------------------------------------------------


class FakeTaggingStage:
    """Stands in for M3b's TaggingStage: needs no audio and records what it saw."""

    needs_audio = False
    name = "tag:genre"
    version = "genre-fake@0000000"

    def __init__(self) -> None:
        self.seen: list[tuple[int, bool, object]] = []

    def is_current(self, repo: object, track_id: int) -> bool:
        return False

    def run(self, repo: object, track_id: int, audio: object) -> None:
        # By now the embedding stage has run for this track.
        self.seen.append((track_id, repo.get_embedding(track_id, MODEL_ID) is not None, audio))  # type: ignore[attr-defined]
        repo.set_tag_probs(track_id, "genre", "head", self.version, {"jazz": 0.75})  # type: ignore[attr-defined]


def fake_tagging_module(stage: FakeTaggingStage) -> types.ModuleType:
    module = types.ModuleType("mcrar.ml.tagging")
    module.tagging_stages = lambda settings: [stage]  # type: ignore[attr-defined]
    return module


def test_ingest_appends_the_tagging_stages_when_m3b_exists(
    monkeypatch: pytest.MonkeyPatch, loader: Loader, library: Path
) -> None:
    stage = FakeTaggingStage()
    monkeypatch.setitem(sys.modules, "mcrar.ml.tagging", fake_tagging_module(stage))
    result = runner.invoke(app, ["ingest", "local", str(library)])
    assert result.exit_code == 0, result.output
    assert len(stage.seen) == 2
    assert all(embedded and audio is None for _, embedded, audio in stage.seen)  # after embedding
    with open_catalog(get_settings()) as repo:
        track = next(repo.iter_tracks())
        assert [(t.head, t.label, t.model_version) for t in repo.get_tag_probs(track.id)] == [
            ("genre", "jazz", "genre-fake@0000000")
        ]


def test_ingest_without_m3b_adds_no_tagging_stages(
    monkeypatch: pytest.MonkeyPatch, loader: Loader, library: Path
) -> None:
    monkeypatch.setitem(sys.modules, "mcrar.ml.tagging", None)  # the import fails, as before M3b
    assert cli._tagging_stages(get_settings()) == []
    result = runner.invoke(app, ["ingest", "local", str(library)])
    assert result.exit_code == 0, result.output
    assert stats()["embeddings_by_model"] == {MODEL_ID: 2}


def test_tagging_stages_are_not_added_when_clap_is_not_embedded(
    monkeypatch: pytest.MonkeyPatch, loader: Loader, library: Path
) -> None:
    """The tagging heads read the CLAP embedding; without it they would only fail per track."""
    stage = FakeTaggingStage()
    monkeypatch.setitem(sys.modules, "mcrar.ml.tagging", fake_tagging_module(stage))
    result = runner.invoke(app, ["ingest", "local", str(library), "--embed", "glap"])
    assert result.exit_code == 0, result.output
    assert stage.seen == []


def test_no_embed_adds_no_tagging_stages(monkeypatch: pytest.MonkeyPatch, library: Path) -> None:
    stage = FakeTaggingStage()
    monkeypatch.setitem(sys.modules, "mcrar.ml.tagging", fake_tagging_module(stage))
    result = runner.invoke(app, ["ingest", "local", str(library), "--no-embed"])
    assert result.exit_code == 0, result.output
    assert stage.seen == []
