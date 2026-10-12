"""`mcrar bakeoff ...` through the CLI runner with fake embedders (no model, no GPU, no network)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from ml_bakeoff_support import ToneEmbedder, make_sdd
from ml_support import FakeEmbedder
from typer.testing import CliRunner

from mcrar import cli
from mcrar.catalog import TrackRecord, open_catalog
from mcrar.cli import app
from mcrar.config import get_settings
from mcrar.ml import MODELS

runner = CliRunner()
DIMS = {"clap": 8, "glap": 9, "muq-mulan": 10}
CLAP, GLAP, MUQ = (MODELS[k].model_id for k in ("clap", "glap", "muq-mulan"))


class Loader:
    """Replaces ``cli._load_embedder`` with fakes that carry the real models' ids."""

    def __init__(self, kind=ToneEmbedder, shifts: dict[str, int] | None = None) -> None:
        self.kind = kind
        self.shifts = shifts or {}
        self.calls: list[str] = []

    def __call__(self, key: str, settings: object, **kwargs: object):
        self.calls.append(key)
        extra = {"shift": self.shifts[key]} if key in self.shifts else {}
        return self.kind(key, dim=DIMS[key], revision=MODELS[key].revision, **extra)


@pytest.fixture
def home(isolated_env: Path) -> Path:
    return isolated_env


@pytest.fixture
def loader(monkeypatch: pytest.MonkeyPatch) -> Loader:
    fake = Loader()
    monkeypatch.setattr(cli, "_load_embedder", fake)
    return fake


@pytest.fixture
def no_torch(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("a real model must not be loaded")

    monkeypatch.setattr(cli, "_load_embedder", boom)


@pytest.fixture
def noncommercial(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCRAR_COMMERCIAL_MODE", "false")


def sdd_root(home: Path) -> Path:
    return home / "data" / "benchmarks" / "sdd"


def results(home: Path, prefix: str) -> list[Path]:
    folder = home / "data" / "benchmarks" / "results"
    return sorted(p for p in folder.glob(f"{prefix}_*.json") if ".private" not in p.name)


def run(*args: str, ok: bool = True):
    result = runner.invoke(app, ["bakeoff", *args])
    if ok:
        assert result.exit_code == 0, result.output
    return result


# -- help ----------------------------------------------------------


def test_help_lists_every_subcommand() -> None:
    result = runner.invoke(app, ["bakeoff", "--help"])
    assert result.exit_code == 0
    for name in ("sdd-embed", "sdd-eval", "tag-eval", "candidates", "score-ratings", "report"):
        assert name in result.output
    assert "bakeoff" in runner.invoke(app, ["--help"]).output
    for name in ("sdd-embed", "sdd-eval", "tag-eval", "candidates", "score-ratings", "report"):
        assert runner.invoke(app, ["bakeoff", name, "--help"]).exit_code == 0
    assert "--benchmark-json" in runner.invoke(app, ["models", "benchmark", "--help"]).output


# -- sdd-embed ----------------------------------------------------------


def test_sdd_embed_writes_one_npz_per_model(home: Path, loader: Loader) -> None:
    make_sdd(sdd_root(home))
    result = run("sdd-embed", "--models", "clap,glap")
    assert "SDD: 6 audio files found, 0 missing" in result.output
    assert loader.calls == ["clap", "glap"]
    for model_id, dim in ((CLAP, 8), (GLAP, 9)):
        with np.load(sdd_root(home) / "embeddings" / f"{model_id}.npz") as saved:
            assert saved["track_ids"].shape == (6,) and saved["matrix"].shape == (6, dim)


def test_sdd_embed_counts_decode_failures_and_missing_files(home: Path, loader: Loader) -> None:
    make_sdd(sdd_root(home), broken=[2], absent=[5])
    result = run("sdd-embed", "--models", "clap")
    assert "SDD: 5 audio files found, 1 missing" in result.output
    assert "failed: track 1002" in result.output
    assert "embedded 4 tracks, 1 decode failures, 1 missing files" in result.output
    with np.load(sdd_root(home) / "embeddings" / f"{CLAP}.npz") as saved:
        assert saved["track_ids"].tolist() == [1000, 1001, 1003, 1004]


def test_sdd_embed_is_resumable_and_force_redoes_it(home: Path, loader: Loader) -> None:
    make_sdd(sdd_root(home))
    run("sdd-embed", "--models", "clap")
    assert loader.calls == ["clap"]
    path = sdd_root(home) / "embeddings" / f"{CLAP}.npz"
    path.write_bytes(path.read_bytes())  # untouched content, new mtime to compare against
    before = path.stat().st_mtime_ns

    again = run("sdd-embed", "--models", "clap,glap")
    assert f"Skipping {CLAP}" in again.output
    assert loader.calls == ["clap", "glap"]  # clap was not even loaded again
    assert path.stat().st_mtime_ns == before

    forced = run("sdd-embed", "--models", "clap", "--force")
    assert "Skipping" not in forced.output
    assert loader.calls == ["clap", "glap", "clap"]
    assert path.stat().st_mtime_ns != before


def test_sdd_embed_all_done_loads_nothing(home: Path, loader: Loader) -> None:
    make_sdd(sdd_root(home))
    run("sdd-embed", "--models", "clap")
    loader.calls.clear()
    run("sdd-embed", "--models", "clap")
    assert loader.calls == []


def test_sdd_embed_respects_the_commercial_gate(home: Path, no_torch: None) -> None:
    make_sdd(sdd_root(home))
    result = run("sdd-embed", "--models", "muq-mulan", ok=False)
    assert result.exit_code == 1
    assert "MCRAR_COMMERCIAL_MODE=false" in result.output
    assert not (sdd_root(home) / "embeddings").exists()


def test_sdd_embed_allows_muq_when_commercial_mode_is_off(
    home: Path, loader: Loader, noncommercial: None
) -> None:
    make_sdd(sdd_root(home))
    run("sdd-embed", "--models", "muq-mulan")
    assert loader.calls == ["muq-mulan"]
    assert (sdd_root(home) / "embeddings" / f"{MUQ}.npz").is_file()


def test_sdd_embed_without_the_dataset_is_a_clean_error(home: Path, no_torch: None) -> None:
    result = run("sdd-embed", "--models", "clap", ok=False)
    assert result.exit_code == 1 and "error:" in result.output and "Traceback" not in result.output


def test_sdd_embed_accepts_a_custom_folder(home: Path, loader: Loader, tmp_path: Path) -> None:
    make_sdd(tmp_path / "elsewhere")
    run("sdd-embed", "--models", "clap", "--sdd-dir", str(tmp_path / "elsewhere"))
    assert (tmp_path / "elsewhere" / "embeddings" / f"{CLAP}.npz").is_file()


# -- sdd-eval ----------------------------------------------------------


def test_sdd_eval_end_to_end(
    home: Path, monkeypatch: pytest.MonkeyPatch, noncommercial: None
) -> None:
    monkeypatch.setattr(cli, "_load_embedder", Loader(shifts={"muq-mulan": 1}))
    make_sdd(sdd_root(home))
    run("sdd-embed", "--models", "clap,glap,muq-mulan")
    result = run("sdd-eval", "--models", "clap,glap,muq-mulan")
    assert "5 captions over 6 tracks" in result.output  # the validated subset only
    (path,) = results(home, "sdd")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["kind"] == "sdd" and data["subset"] == "validated"
    assert data["models"] == [CLAP, GLAP, MUQ]
    assert data["n_captions"] == 5 and data["n_tracks"] == 6
    assert data["n_resamples"] == 1000 and data["seed"] == 0
    assert data["models_info"][MUQ]["commercial_ok"] is False
    clap, muq = data["results"][CLAP]["t2a"], data["results"][MUQ]["t2a"]
    assert clap["R@1"] == 1.0 and clap["mrr"] == 1.0 and clap["R@10"] == 1.0
    assert muq["R@1"] == 0.0  # its text side is shifted by one slot: wrong track first
    assert data["results"][CLAP]["a2t"]["R@10"] == 1.0
    assert {(p["a"], p["b"], p["metric"]) for p in data["pairwise"]} >= {(CLAP, MUQ, "R@10")}
    assert "Saved" in result.output and CLAP in result.output


def test_sdd_eval_all_captions(home: Path, loader: Loader) -> None:
    make_sdd(sdd_root(home))
    run("sdd-embed", "--models", "clap")
    result = run("sdd-eval", "--models", "clap", "--all-captions")
    assert "12 captions over 6 tracks" in result.output
    data = json.loads(results(home, "sdd")[0].read_text(encoding="utf-8"))
    assert data["subset"] == "all" and data["n_captions"] == 12
    assert data["results"][CLAP]["t2a"]["R@1"] == 1.0


def test_sdd_eval_uses_only_tracks_every_model_embedded(home: Path, loader: Loader) -> None:
    make_sdd(sdd_root(home))
    run("sdd-embed", "--models", "clap")
    # glap's file lacks track 1003, as if that file had failed to decode
    from mcrar.ml.bakeoff import sdd

    ids, matrix = sdd.load_embeddings_file(sdd.embeddings_path(sdd_root(home), CLAP))
    keep = ids != 1003
    sdd.save_embeddings(sdd.embeddings_path(sdd_root(home), GLAP), ids[keep], np.zeros((5, 9)) + 1)
    result = run("sdd-eval", "--models", "clap,glap")
    assert "over 5 tracks" in result.output and "skipped" in result.output


def test_sdd_eval_needs_the_embeddings(home: Path, no_torch: None) -> None:
    make_sdd(sdd_root(home))
    result = run("sdd-eval", "--models", "clap", ok=False)
    assert result.exit_code == 1 and "sdd-embed" in result.output


def test_sdd_eval_refuses_muq_in_commercial_mode(home: Path, no_torch: None) -> None:
    make_sdd(sdd_root(home))
    result = run("sdd-eval", "--models", "clap,muq-mulan", ok=False)
    assert result.exit_code == 1 and "MCRAR_COMMERCIAL_MODE=false" in result.output


# -- catalog-based commands ----------------------------------------------------------


def unit(vec: np.ndarray) -> np.ndarray:
    return (vec / np.linalg.norm(vec)).astype(np.float32)


def genre_direction(key: str, genre: str) -> np.ndarray:
    return FakeEmbedder(key, dim=DIMS[key]).embed_text([f"{genre} music"])[0]


def seed_tag_catalog() -> dict[str, list[int]]:
    """20 rock, 20 jazz, 5 folk tracks, plus one rock track that only clap embedded."""
    ids: dict[str, list[int]] = {"rock": [], "jazz": [], "folk": [], "clap_only": []}
    layout = [("rock", 20), ("jazz", 20), ("folk", 5), ("clap_only", 1)]
    with open_catalog(get_settings()) as repo:
        n = 0
        for genre, count in layout:
            for _ in range(count):
                n += 1
                tag = "rock" if genre == "clap_only" else genre
                track_id = repo.upsert_track(
                    TrackRecord(
                        source="jamendo",
                        source_id=str(n),
                        title=f"T{n}",
                        source_url=f"https://example.test/{n}",
                        source_tags={"genres": [tag]},
                    )
                )
                ids[genre].append(track_id)
                for key in ("clap", "glap", "muq-mulan"):
                    if genre == "clap_only" and key != "clap":
                        continue
                    repo.set_embedding(track_id, MODELS[key].model_id, genre_direction(key, tag))
    return ids


def test_tag_eval_uses_the_common_track_set_and_the_min_tracks_filter(
    home: Path, loader: Loader
) -> None:
    seed_tag_catalog()
    both = run("tag-eval", "--models", "clap,glap")
    assert "Note:" in both.output and "noisy" in both.output
    (path,) = results(home, "tags")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["n_tracks"] == 45  # the clap-only track is left out for the comparison
    assert [t["tag"] for t in data["tags"]] == ["jazz", "rock"]  # folk has 5 tracks < 15
    assert data["min_tracks"] == 15 and "noisy" in data["note"]
    assert data["tags"][0]["query"] == "jazz music"
    for model_id in (CLAP, GLAP):
        assert data["results"][model_id]["macro_AP"] == 1.0
        assert data["results"][model_id]["macro_P@10"] == 1.0
        assert set(data["results"][model_id]["per_tag"]) == {"jazz", "rock"}
    assert loader.calls == ["clap", "glap"]


def test_tag_eval_with_one_model_sees_every_track_it_embedded(home: Path, loader: Loader) -> None:
    seed_tag_catalog()
    run("tag-eval", "--models", "clap", "--min-tracks", "3")
    data = json.loads(results(home, "tags")[0].read_text(encoding="utf-8"))
    assert data["n_tracks"] == 46
    assert [(t["tag"], t["n_relevant"]) for t in data["tags"]] == [
        ("folk", 5), ("jazz", 20), ("rock", 21)
    ]  # fmt: skip


def test_tag_eval_without_enough_tracks_is_a_clean_error(home: Path, loader: Loader) -> None:
    seed_tag_catalog()
    result = run("tag-eval", "--models", "clap", "--min-tracks", "30", ok=False)
    assert result.exit_code == 1 and "no genre tag has 30+" in result.output


def test_tag_eval_needs_embeddings(home: Path, no_torch: None) -> None:
    with open_catalog(get_settings()):
        pass
    result = run("tag-eval", "--models", "clap", ok=False)
    assert result.exit_code == 1 and "mcrar embed" in result.output


def seed_candidate_catalog(n: int = 12) -> None:
    rng = np.random.default_rng(0)
    with open_catalog(get_settings()) as repo:
        for i in range(1, n + 1):
            track_id = repo.upsert_track(
                TrackRecord(
                    source="jamendo",
                    source_id=str(i),
                    title=f"T{i}",
                    artist="Art",
                    source_url=None if i % 4 == 0 else f"https://example.test/{i}",
                    download_url="https://example.test/dl" if i % 2 else None,
                    risk="red" if i % 3 == 0 else "green",
                    source_tags={"genres": ["rock"], "vartags": ["x"]},
                    duration_s=100.0,
                )
            )
            repo.set_features(
                track_id,
                {
                    "bpm": 120.4,
                    "key": "C",
                    "mode": "major",
                    "energy": 0.456,
                    "analysis_version": "t",
                },
            )
            for key in ("clap", "glap"):
                repo.set_embedding(
                    track_id, MODELS[key].model_id, unit(rng.standard_normal(DIMS[key]))
                )


def test_candidates_writes_a_blind_public_file_and_a_private_sidecar(
    home: Path, loader: Loader, tmp_path: Path
) -> None:
    seed_candidate_catalog()
    queries = tmp_path / "queries.txt"
    queries.write_text("calm forest\n\nepic battle\n", encoding="utf-8")
    result = run(
        "candidates", "--models", "clap,glap", "--per-model", "2", "--queries", str(queries)
    )
    assert "2 queries" in result.output
    (path,) = results(home, "candidates")
    private_path = path.with_name(path.name.removesuffix(".json") + ".private.json")
    public = json.loads(path.read_text(encoding="utf-8"))
    private = json.loads(private_path.read_text(encoding="utf-8"))

    assert public["models"] == [CLAP, GLAP] and public["per_model"] == 2 and public["created_at"]
    assert [(q["id"], q["text"]) for q in public["queries"]] == [
        ("q01", "calm forest"),
        ("q02", "epic battle"),
    ]
    text = json.dumps(public["queries"])
    assert "clap" not in text and "glap" not in text and "rank" not in text
    for query in public["queries"]:
        items = query["items"]
        ids = [i["track_id"] for i in items]
        assert len(ids) == len(set(ids))  # deduplicated
        assert 2 <= len(ids) <= 4
        assert set(items[0]) == {
            "track_id", "title", "artist", "source_url", "risk", "license_code", "bpm", "key",
            "mode", "energy", "genres", "vartags", "duration_s",
        }  # fmt: skip
        assert all(i["source_url"] for i in items)
        assert items[0]["bpm"] == 120 and items[0]["energy"] == 0.46
        # the sidecar maps every pooled track back to its proposers, in the same order
        assert [str(i) for i in ids] == list(private[query["id"]])
        for proposers in private[query["id"]].values():
            assert {p["model"] for p in proposers} <= {CLAP, GLAP}
            assert all(1 <= p["rank"] <= 2 for p in proposers)
        for model_id in (CLAP, GLAP):
            ranks = sorted(
                p["rank"]
                for ps in private[query["id"]].values()
                for p in ps
                if p["model"] == model_id
            )
            assert ranks == [1, 2]


def test_candidates_leaves_out_tracks_without_a_source_url(home: Path, loader: Loader) -> None:
    seed_candidate_catalog()
    run("candidates", "--models", "clap,glap", "--per-model", "12")
    public = json.loads(results(home, "candidates")[0].read_text(encoding="utf-8"))
    with open_catalog(get_settings()) as repo:
        no_url = {t.id for t in repo.iter_tracks() if not t.source_url}
    assert no_url
    for query in public["queries"]:
        assert not no_url & {i["track_id"] for i in query["items"]}
        assert len(query["items"]) == 9  # every track with a URL, once


def test_candidates_is_deterministic(home: Path, loader: Loader) -> None:
    seed_candidate_catalog()
    run("candidates", "--models", "clap,glap")
    first = json.loads(results(home, "candidates")[-1].read_text(encoding="utf-8"))
    for path in results(home, "candidates"):
        path.unlink()
    run("candidates", "--models", "clap,glap")
    second = json.loads(results(home, "candidates")[-1].read_text(encoding="utf-8"))
    assert first["queries"] == second["queries"]
    assert len(first["queries"]) == 15


def test_score_ratings_after_candidates(home: Path, loader: Loader, tmp_path: Path) -> None:
    seed_candidate_catalog()
    run("candidates", "--models", "clap,glap", "--per-model", "2")
    (cand_path,) = results(home, "candidates")
    public = json.loads(cand_path.read_text(encoding="utf-8"))
    everything = [
        {"query_id": q["id"], "track_id": i["track_id"], "score": 1}
        for q in public["queries"]
        for i in q["items"]
    ]
    ratings = tmp_path / "ratings.json"
    ratings.write_text(json.dumps({"ratings": everything}), encoding="utf-8")
    result = run("score-ratings", str(ratings), "--candidates", str(cand_path))
    assert "100%" in result.output
    (out,) = results(home, "ratings")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["k"] == 2 and data["candidates_file"] == cand_path.name
    assert data["coverage"]["pool_fraction"] == 1.0
    for model_id in (CLAP, GLAP):
        assert data["results"][model_id]["mean_rating"] == 1.0
        assert data["results"][model_id]["coverage"] == 1.0
    assert data["models_info"][CLAP]["commercial_ok"] is True

    # half of the items unrated: they are left out and the coverage drops
    ratings.write_text(json.dumps({"ratings": everything[::2]}), encoding="utf-8")
    partial = run("score-ratings", str(ratings), "--candidates", str(cand_path), "--k", "1")
    assert "unknown items ignored" in partial.output
    latest = json.loads(results(home, "ratings")[-1].read_text(encoding="utf-8"))
    assert latest["k"] == 1 and latest["coverage"]["pool_fraction"] < 1.0


def test_score_ratings_errors_are_clean(home: Path, tmp_path: Path) -> None:
    ratings = tmp_path / "r.json"
    ratings.write_text("{}", encoding="utf-8")
    missing = run(
        "score-ratings", str(ratings), "--candidates", str(tmp_path / "nope.json"), ok=False
    )
    assert missing.exit_code == 1 and "file not found" in missing.output
    cand = tmp_path / "candidates_x.json"
    cand.write_text(json.dumps({"queries": [], "per_model": 3}), encoding="utf-8")
    (tmp_path / "candidates_x.private.json").write_text("{}", encoding="utf-8")
    bad = run("score-ratings", str(ratings), "--candidates", str(cand), ok=False)
    assert bad.exit_code == 1 and "ratings file must look like" in bad.output


# -- report and the whole chain ----------------------------------------------------------


def test_report_end_to_end_into_a_temp_path(
    home: Path, monkeypatch: pytest.MonkeyPatch, noncommercial: None, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "_load_embedder", Loader(shifts={"muq-mulan": 1}))
    make_sdd(sdd_root(home))
    run("sdd-embed", "--models", "clap,glap,muq-mulan")
    run("sdd-eval", "--models", "clap,glap,muq-mulan")
    target = tmp_path / "out" / "report.md"
    result = run("report", "--output", str(target))
    assert f"Wrote {target}" in result.output and "Used sdd:" in result.output
    text = target.read_text(encoding="utf-8")
    assert "## Recommendation" in text and "Song Describer" in text
    # clap and glap tie on the synthetic data; the first permissive model wins, MuQ is worse
    assert f"**Default model: `{CLAP}`**" in text
    assert "NON-COMMERCIAL" in text
    assert not (home / "docs").exists()  # nothing was written to the default location


def test_report_defaults_to_docs_in_the_repo_home(home: Path, loader: Loader) -> None:
    make_sdd(sdd_root(home))
    run("sdd-embed", "--models", "clap")
    run("sdd-eval", "--models", "clap")
    run("report")
    assert (home / "docs" / "embedder_bakeoff.md").is_file()


def test_report_without_results_is_a_clean_error(home: Path) -> None:
    result = run("report", ok=False)
    assert result.exit_code == 1 and "no results found" in result.output


# -- models benchmark --benchmark-json ----------------------------------------------------------


def test_models_benchmark_can_save_its_table(home: Path, loader: Loader) -> None:
    result = runner.invoke(
        app, ["models", "benchmark", "--models", "clap,glap", "--seconds", "2", "--benchmark-json"]
    )
    assert result.exit_code == 0, result.output
    (path,) = results(home, "benchmark")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["kind"] == "benchmark" and data["seconds"] == 2.0
    assert [r["model_id"] for r in data["rows"]] == [CLAP, GLAP]
    assert {"load_s", "audio_s_per_s", "texts_per_s", "peak_vram_mb", "dim"} <= set(data["rows"][0])
    assert "Saved" in result.output


def test_models_benchmark_does_not_write_unless_asked(home: Path, loader: Loader) -> None:
    result = runner.invoke(app, ["models", "benchmark", "--models", "clap", "--seconds", "2"])
    assert result.exit_code == 0, result.output
    assert not (home / "data" / "benchmarks" / "results").exists()
