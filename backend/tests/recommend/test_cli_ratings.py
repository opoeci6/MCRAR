"""`mcrar ratings import` and `mcrar ratings eval` through the CLI runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from recommend_support import QUERY_TEXTS, MapEmbedder, build_catalog
from typer.testing import CliRunner

from mcrar import cli
from mcrar.catalog import open_catalog
from mcrar.cli import app
from mcrar.config import get_settings
from mcrar.recommend import SearchFilters
from mcrar.recommend.ratings import filters_to_json, query_key

runner = CliRunner()

TEXT_1 = "tense stealth level"
TEXT_2 = "epic battle"
INSTRUMENTAL = SearchFilters(max_risk="green", vocal="instrumental")


class Loader:
    """Replaces ``cli._load_embedder`` and counts how often a model is loaded."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.loaded: list[MapEmbedder] = []

    def __call__(self, key: str, settings: object, **kwargs: object) -> MapEmbedder:
        self.calls.append(key)
        embedder = MapEmbedder(QUERY_TEXTS, key=key)
        self.loaded.append(embedder)
        return embedder


@pytest.fixture
def loader(monkeypatch: pytest.MonkeyPatch) -> Loader:
    """A fake model loader that also stands in for torch being installed (CI has no ml extra)."""
    fake = Loader()
    monkeypatch.setattr(cli, "_load_embedder", fake)
    monkeypatch.setattr(cli, "_torch_available", lambda: True)
    return fake


@pytest.fixture
def ids() -> dict[str, int]:
    with open_catalog(get_settings()) as repo:
        return build_catalog(repo)


def top_ids(*args: str) -> list[int]:
    """The track ids `mcrar search` puts first for these arguments (limit 2)."""
    result = runner.invoke(app, ["search", *args, "--limit", "2", "--json"])
    assert result.exit_code == 0, result.output
    return [item["track_id"] for item in json.loads(result.stdout)["items"]]


def rate(key: str, text: str | None, filters: SearchFilters, scores: dict[int, int]) -> None:
    with open_catalog(get_settings()) as repo:
        for track_id, score in scores.items():
            repo.set_rating(
                key, track_id, score, query_text=text, filters_json=filters_to_json(filters)
            )


def stored() -> list[tuple[str, int, int]]:
    with open_catalog(get_settings()) as repo:
        return [(r.query_key, r.track_id, r.rating) for r in repo.iter_ratings()]


# -- import --------------------------------------------------------------------------------------


def write_files(tmp_path: Path, ids: dict[str, int]) -> tuple[Path, Path]:
    queries = tmp_path / "candidates.json"
    queries.write_text(
        json.dumps(
            {
                "queries": [
                    {"id": "q01", "text": "Tense  Stealth level", "items": []},
                    {"id": "q02", "text": TEXT_2, "items": []},
                    {"id": "q03", "text": "never rated", "items": []},
                ]
            }
        ),
        encoding="utf-8",
    )
    entries = [
        {"query_id": "q01", "track_id": ids["Shadow Walk"], "score": 2},
        {"query_id": "q01", "track_id": ids["Quiet Vents"], "score": 1},
        {"query_id": "q02", "track_id": ids["Epic Quest"], "score": 0},
        {"query_id": "q02", "track_id": 99999, "score": 2},  # not in this catalog
    ]
    ratings = tmp_path / "user_ratings.json"
    ratings.write_text(json.dumps({"ratings": entries}), encoding="utf-8")
    return ratings, queries


def test_import_stores_ratings_under_the_query_text_and_skips_unknown_tracks(
    tmp_path: Path, ids: dict[str, int]
) -> None:
    ratings, queries = write_files(tmp_path, ids)
    result = runner.invoke(app, ["ratings", "import", str(ratings), "--queries", str(queries)])
    assert result.exit_code == 0, result.output
    assert "Stored 3 rating(s) for 2 query text(s)." in result.stdout
    assert "Skipped 1 rating(s) of tracks that are not in the catalog." in result.stdout
    key_1, key_2 = f"text:{TEXT_1}", f"text:{TEXT_2}"
    assert sorted(stored()) == sorted(
        [
            (key_1, ids["Shadow Walk"], 2),
            (key_1, ids["Quiet Vents"], 1),
            (key_2, ids["Epic Quest"], 0),
        ]
    )
    with open_catalog(get_settings()) as repo:
        assert {(k, t) for k, t, _, _ in repo.rating_queries()} == {
            (key_1, "Tense Stealth level"),
            (key_2, TEXT_2),
        }


def test_import_twice_changes_nothing(tmp_path: Path, ids: dict[str, int]) -> None:
    ratings, queries = write_files(tmp_path, ids)
    args = ["ratings", "import", str(ratings), "--queries", str(queries)]
    assert runner.invoke(app, args).exit_code == 0
    before = stored()
    again = runner.invoke(app, args)
    assert again.exit_code == 0 and "Stored 3 rating(s)" in again.stdout
    assert stored() == before


def test_import_merges_unless_replace_is_given(tmp_path: Path, ids: dict[str, int]) -> None:
    ratings, queries = write_files(tmp_path, ids)
    other = (f"text:{TEXT_1}", ids["Night Heist"], 2)  # rated earlier, not in the file
    rate(other[0], TEXT_1, SearchFilters(), {other[1]: other[2]})
    args = ["ratings", "import", str(ratings), "--queries", str(queries)]
    assert runner.invoke(app, args).exit_code == 0
    assert other in stored()
    result = runner.invoke(app, [*args, "--replace"])
    assert result.exit_code == 0, result.output
    assert "Removed 4 earlier rating(s)" in result.stdout  # the file's 3 + the extra one
    assert other not in stored() and len(stored()) == 3


@pytest.mark.parametrize(
    ("ratings_body", "message"),
    [
        ({"ratings": [{"query_id": "q09", "track_id": 1, "score": 1}]}, "no query q09"),
        ({"ratings": [{"query_id": "q01", "track_id": 1, "score": 5}]}, "score must be 0, 1 or 2"),
        ({"nope": []}, "ratings file must look like"),
    ],
)
def test_import_reports_bad_files_without_a_traceback(
    tmp_path: Path, ids: dict[str, int], ratings_body: dict, message: str
) -> None:
    _, queries = write_files(tmp_path, ids)
    ratings = tmp_path / "bad.json"
    ratings.write_text(json.dumps(ratings_body), encoding="utf-8")
    result = runner.invoke(app, ["ratings", "import", str(ratings), "--queries", str(queries)])
    assert result.exit_code == 1 and "error: " in result.stderr and message in result.stderr
    assert "Traceback" not in result.output and stored() == []


def test_import_of_a_missing_file_is_an_error(tmp_path: Path, ids: dict[str, int]) -> None:
    _, queries = write_files(tmp_path, ids)
    result = runner.invoke(
        app, ["ratings", "import", str(tmp_path / "gone.json"), "--queries", str(queries)]
    )
    assert result.exit_code == 1 and "file not found" in result.stderr


# -- eval ----------------------------------------------------------------------------------------


def three_queries(loader: Loader, ids: dict[str, int]) -> dict[str, list[int]]:
    """Rate the current top-2 of three queries: [2, 1], [0, unrated] and [2, 2]."""
    a, b = top_ids(TEXT_1)
    c, d = top_ids(TEXT_2)
    e, f = top_ids("--max-risk", "green", "--instrumental")
    rate(query_key(TEXT_1, SearchFilters()), TEXT_1, SearchFilters(), {a: 2, b: 1})
    rate(query_key(TEXT_2, SearchFilters()), TEXT_2, SearchFilters(), {c: 0})
    rate(query_key(None, INSTRUMENTAL), None, INSTRUMENTAL, {e: 2, f: 2})
    loader.calls.clear()
    return {"stealth": [a, b], "epic": [c, d], "instrumental": [e, f]}


def test_eval_pools_the_rated_hits_and_counts_the_unrated(
    loader: Loader, ids: dict[str, int]
) -> None:
    three_queries(loader, ids)
    result = runner.invoke(app, ["ratings", "eval", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)  # nothing but JSON on stdout
    assert data["k"] == 2
    # pooled: (2 + 1 + 0 + 2 + 2) / 5; a mean of the per-query means would be 7/6
    assert data["overall"] == {"mean": pytest.approx(1.4), "rated": 5, "unrated": 1}
    by_key = {q["query_key"]: q for q in data["queries"]}
    stealth = by_key[query_key(TEXT_1, SearchFilters())]
    assert (stealth["mean"], stealth["rated"], stealth["unrated"]) == (1.5, 2, 0)
    assert stealth["query_text"] == TEXT_1 and stealth["filters"] == {}
    epic = by_key[query_key(TEXT_2, SearchFilters())]
    assert (epic["mean"], epic["rated"], epic["unrated"]) == (0.0, 1, 1)
    assert [h["rating"] for h in epic["hits"]] == [0, None]
    instrumental = by_key[query_key(None, INSTRUMENTAL)]
    assert instrumental["filters"] == {"max_risk": "green", "vocal": "instrumental"}
    assert instrumental["query_text"] is None and instrumental["mean"] == 2.0
    assert loader.calls == ["clap"]  # one model load for all the queries
    assert all(e.closed for e in loader.loaded)
    assert "Loading clap" in result.stderr


def test_eval_k_limits_the_hits_looked_at(loader: Loader, ids: dict[str, int]) -> None:
    hits = three_queries(loader, ids)
    result = runner.invoke(app, ["ratings", "eval", "--k", "1", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert all(len(q["hits"]) == 1 for q in data["queries"])
    assert data["overall"] == {"mean": pytest.approx(4 / 3), "rated": 3, "unrated": 0}
    assert hits["stealth"][0] in [h["track_id"] for q in data["queries"] for h in q["hits"]]


def test_eval_prints_a_table(loader: Loader, ids: dict[str, int]) -> None:
    three_queries(loader, ids)
    result = runner.invoke(app, ["ratings", "eval"])
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0].split() == ["Query", "Top-2", "mean", "Rated", "Unrated"]
    epic = next(line for line in lines if line.startswith(TEXT_2))
    assert epic.split()[-3:] == ["0.00", "1", "1"]
    assert lines[-1].startswith("Overall") and lines[-1].split()[-3:] == ["1.40", "5", "1"]


def test_eval_without_ratings_is_an_error(loader: Loader, ids: dict[str, int]) -> None:
    result = runner.invoke(app, ["ratings", "eval"])
    assert result.exit_code == 1 and "there are no ratings yet" in result.stderr
    assert loader.calls == []


def test_eval_of_text_queries_needs_torch(
    loader: Loader, ids: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    three_queries(loader, ids)
    monkeypatch.setattr(cli, "_torch_available", lambda: False)
    result = runner.invoke(app, ["ratings", "eval"])
    assert result.exit_code == 1 and "error: text queries need the ml extra" in result.stderr
    assert "Traceback" not in result.output and loader.calls == []


def test_eval_of_filter_only_queries_never_loads_the_model(
    loader: Loader, ids: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    top = top_ids("--max-risk", "green", "--instrumental")
    rate(query_key(None, INSTRUMENTAL), None, INSTRUMENTAL, {top[0]: 1})
    loader.calls.clear()
    monkeypatch.setattr(cli, "_torch_available", lambda: False)
    result = runner.invoke(app, ["ratings", "eval", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["overall"] == {"mean": 1.0, "rated": 1, "unrated": 1}
    assert loader.calls == []


def test_ratings_commands_are_listed() -> None:
    result = runner.invoke(app, ["ratings", "--help"])
    assert result.exit_code == 0 and "import" in result.stdout and "eval" in result.stdout
