"""Sharing the labelling work (M9): the pool pack and the labels file, between two catalogs whose
local track ids differ. Jamendo is a stub: no network, and the stub fails the test if any audio
is asked for."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from mcrar import cli
from mcrar.catalog import CatalogRepository, PoolEntry, TrackRecord, open_catalog, open_path
from mcrar.cli import app
from mcrar.config import get_settings
from mcrar.ml.tagging.scene_share import (
    export_labels,
    export_pack,
    import_labels,
    import_pack,
)
from mcrar.recommend.vocab import Vocabulary
from mcrar.sources import JamendoError, SourceTrack

runner = CliRunner()
CC_BY = "https://creativecommons.org/licenses/by/4.0/"
POOL = [  # source id, part, reason
    ("101", "A", "top:combat:zeroshot-catalog"),
    ("102", "B", "random"),
    ("103", "both", "top:boss:zeroshot-catalog-centered"),
    ("104", "A", "random"),
    ("105", "B", "random"),
]


class ByIdJamendo:
    """``get_tracks`` knows the ids it was given; fetching audio is a test failure."""

    def __init__(self, known: Sequence[str]) -> None:
        self.known = set(known)
        self.lookups: list[list[str]] = []
        self.closed = False

    def get_tracks(self, ids: Sequence[str | int], **kwargs: Any) -> list[SourceTrack]:
        self.lookups.append([str(i) for i in ids])
        return [
            SourceTrack(
                source="jamendo",
                source_id=str(i),
                title=f"Remote {i}",
                artist="Remote Artist",
                stream_url=f"https://audio.example/{i}?token=secret",
                license_url=CC_BY,
            )
            for i in ids
            if str(i) in self.known
        ]

    def fetch_audio(self, *args: object, **kwargs: object) -> bytes:
        raise AssertionError("labelling a track must not download audio")

    def close(self) -> None:
        self.closed = True


def make_owner(repo: CatalogRepository, *, extra_local: bool = False) -> dict[str, int]:
    """The owner's catalog: the pool tracks (ids 101..105) and optionally one local track."""
    ids = {
        sid: repo.upsert_track(
            TrackRecord(source="jamendo", source_id=sid, title=f"Song {sid}", artist="Ann")
        )
        for sid, _, _ in POOL
    }
    entries = [
        PoolEntry(ids[sid], n, reason, part) for n, (sid, part, reason) in enumerate(POOL, 1)
    ]
    if extra_local:
        ids["local"] = repo.upsert_track(
            TrackRecord(source="local", source_id="abc", title="Local one", local_path="/x/y.wav")
        )
        entries.append(PoolEntry(ids["local"], 6, "random", "B"))
    repo.replace_label_pool(entries)
    return ids


@pytest.fixture
def second(tmp_path: Path):  # noqa: ANN201
    with open_path(tmp_path / "second" / "catalog.db") as repo:
        yield repo


# -- the pack ----------------------------------------------------------------------------------


def test_the_pack_names_tracks_by_source_and_carries_no_ids_or_urls(
    repo: CatalogRepository,
) -> None:
    make_owner(repo)
    pack = export_pack(repo)
    assert (pack["schema"], pack["kind"]) == (1, "mcrar-scene-pack") and pack["created_at"]
    assert [t["source_id"] for t in pack["tracks"]] == ["101", "102", "103", "104", "105"]
    assert set(pack["tracks"][0]) == {
        "source",
        "source_id",
        "title",
        "artist",
        "position",
        "part",
        "reason",
    }
    assert pack["tracks"][2] == {
        "source": "jamendo",
        "source_id": "103",
        "title": "Song 103",
        "artist": "Ann",
        "position": 3,
        "part": "both",
        "reason": "top:boss:zeroshot-catalog-centered",
    }
    assert "http" not in json.dumps(pack)


def test_an_empty_pool_cannot_be_exported(repo: CatalogRepository) -> None:
    with pytest.raises(ValueError, match="No labelling pool yet: run mcrar scenes pool"):
        export_pack(repo)


def test_a_pack_maps_by_source_id_and_fetches_metadata_only(
    repo: CatalogRepository, second: CatalogRepository
) -> None:
    make_owner(repo, extra_local=True)
    pack = json.loads(json.dumps(export_pack(repo)))
    # the collaborator already has two of the tracks, under other local ids
    for sid in ("105", "103"):
        second.upsert_track(TrackRecord(source="jamendo", source_id=sid, title=f"Mine {sid}"))
    stub = ByIdJamendo(["101", "102", "104"])
    events: list[Any] = []
    result = import_pack(second, pack, open_client=lambda: stub, on_progress=events.append)

    assert stub.lookups == [["101", "102", "104"]]  # only the Jamendo tracks it lacked
    assert stub.closed
    assert (result.pool_size, result.present, result.fetched) == (5, 2, 3)
    assert [m["source"] for m in result.missing] == ["local"]
    assert "cannot be fetched" in result.missing[0]["reason"]
    pool = second.label_pool()
    assert [
        (second.get_track(e.track_id).source_id, e.position, e.part, e.reason) for e in pool
    ] == [
        ("101", 1, "A", "top:combat:zeroshot-catalog"),
        ("102", 2, "B", "random"),
        ("103", 3, "both", "top:boss:zeroshot-catalog-centered"),
        ("104", 4, "A", "random"),
        ("105", 5, "B", "random"),
    ]
    fetched = second.get_track_by_source("jamendo", "101")
    assert fetched is not None and fetched.title == "Remote 101" and fetched.license_code
    # metadata only: no embedding, no features, no ingest stage ran
    assert second.get_embedding(fetched.id, "clap@195c3a3") is None
    assert second.get_features(fetched.id) is None and second.ingest_entries("jamendo", "101") == []
    assert [e.kind for e in events if e.kind == "track_done"] == ["track_done"] * 3
    assert all("metadata only" in e.message for e in events if e.kind == "track_done")
    # the existing tracks were left alone
    assert second.get_track_by_source("jamendo", "105").title == "Mine 105"  # type: ignore[union-attr]


def test_a_track_jamendo_no_longer_has_is_reported(
    repo: CatalogRepository, second: CatalogRepository
) -> None:
    make_owner(repo)
    result = import_pack(second, export_pack(repo), open_client=lambda: ByIdJamendo(["101", "102"]))
    assert (result.pool_size, result.fetched) == (2, 2)
    assert sorted(m["source_id"] for m in result.missing) == ["103", "104", "105"]
    assert all("any more" in m["reason"] for m in result.missing)


def test_no_fetch_maps_what_exists_without_opening_a_client(
    repo: CatalogRepository, second: CatalogRepository
) -> None:
    make_owner(repo)
    second.upsert_track(TrackRecord(source="jamendo", source_id="104", title="Mine"))
    result = import_pack(second, export_pack(repo), open_client=None)
    assert (result.pool_size, result.fetched, result.present) == (1, 0, 1)
    assert all("fetching is off" in m["reason"] for m in result.missing)
    nothing = {
        "schema": 1,
        "kind": "mcrar-scene-pack",
        "tracks": [
            {"source": "jamendo", "source_id": "zzz", "position": 1, "part": "A", "reason": "r"}
        ],
    }
    with pytest.raises(ValueError, match="none of the pack's tracks"):
        import_pack(second, nothing, open_client=None, force=True)
    assert len(second.label_pool()) == 1  # the pool was not changed


def test_an_existing_pool_is_only_replaced_with_force_and_before_any_fetch(
    repo: CatalogRepository, second: CatalogRepository
) -> None:
    make_owner(repo)
    pack = export_pack(repo)
    mine = second.upsert_track(TrackRecord(source="jamendo", source_id="999", title="Other"))
    second.replace_label_pool([PoolEntry(mine, 1, "random", "A")])

    def explode() -> object:
        raise AssertionError("must not open a client")

    with pytest.raises(ValueError, match="already exists.*--force"):
        import_pack(second, pack, open_client=explode)
    assert [e.track_id for e in second.label_pool()] == [mine]
    stub = ByIdJamendo(["101", "102", "103", "104", "105"])
    result = import_pack(second, pack, open_client=lambda: stub, force=True)
    assert result.pool_size == 5 and mine not in [e.track_id for e in second.label_pool()]


def test_a_missing_key_stops_the_import_and_leaves_the_pool(
    repo: CatalogRepository, second: CatalogRepository
) -> None:
    make_owner(repo)

    def no_key() -> object:
        raise JamendoError("No Jamendo client id is configured")

    with pytest.raises(JamendoError, match="No Jamendo client id"):
        import_pack(second, export_pack(repo), open_client=no_key)
    assert second.label_pool() == []


@pytest.mark.parametrize(
    "bad",
    [
        [],
        {"kind": "other", "schema": 1, "tracks": []},
        {"kind": "mcrar-scene-pack", "schema": 2, "tracks": []},
        {"kind": "mcrar-scene-pack", "schema": 1, "tracks": []},
        {"kind": "mcrar-scene-pack", "schema": 1, "tracks": [{"source": "jamendo"}]},
        {
            "kind": "mcrar-scene-pack",
            "schema": 1,
            "tracks": [
                {"source": "jamendo", "source_id": "1", "position": 1, "part": "C", "reason": "r"}
            ],
        },
        {
            "kind": "mcrar-scene-pack",
            "schema": 1,
            "tracks": [
                {"source": "jamendo", "source_id": "1", "position": 1, "part": "A", "reason": "r"},
                {"source": "jamendo", "source_id": "2", "position": 1, "part": "B", "reason": "r"},
            ],
        },
    ],
)
def test_a_bad_pack_is_refused(second: CatalogRepository, bad: object) -> None:
    with pytest.raises(ValueError):
        import_pack(second, bad, open_client=None)
    assert second.label_pool() == []


# -- the labels --------------------------------------------------------------------------------


def label_file(rows: list[dict]) -> dict:
    return {"schema": 1, "kind": "mcrar-scene-labels", "labels": rows}


def test_labels_round_trip_by_source_id_and_the_labeller_stays(
    repo: CatalogRepository, second: CatalogRepository
) -> None:
    ids = make_owner(repo)
    repo.set_scene_label(ids["101"], "Ben", ["combat", "boss"], "high", "labelled")
    repo.set_scene_label(ids["102"], "Ben", [], None, "labelled")
    repo.set_scene_label(ids["103"], "Ben", [], None, "skipped")
    repo.set_scene_label(ids["101"], "Ann", ["horror"], "low", "labelled")
    data = export_labels(repo, "Ben")
    assert (data["schema"], data["kind"]) == (1, "mcrar-scene-labels")
    assert [(r["labeller"], r["source_id"]) for r in data["labels"]] == [
        ("Ben", "101"),
        ("Ben", "102"),
        ("Ben", "103"),
    ]
    assert set(data["labels"][0]) == {
        "labeller", "source", "source_id", "title", "artist",
        "scenes", "intensity", "status", "updated_at",
    }  # fmt: skip
    assert len(export_labels(repo)["labels"]) == 4  # every labeller by default

    # the collaborator's catalog holds the same tracks under other local ids
    for sid in ("103", "102", "101"):
        second.upsert_track(TrackRecord(source="jamendo", source_id=sid, title=sid))
    result = import_labels(second, json.loads(json.dumps(data)), Vocabulary.default())
    assert (result.stored, result.older, result.unknown, result.labellers) == (3, 0, [], ["Ben"])
    track = second.get_track_by_source("jamendo", "101")
    label = second.get_scene_label(track.id, "Ben")  # type: ignore[union-attr]
    assert label is not None and label.scenes == ("combat", "boss") and label.intensity == "high"
    assert label.updated_at == repo.get_scene_label(ids["101"], "Ben").updated_at  # type: ignore[union-attr]
    skipped = second.get_scene_label(second.get_track_by_source("jamendo", "103").id, "Ben")  # type: ignore[union-attr]
    assert skipped is not None and skipped.status == "skipped"


def test_the_newer_label_wins_and_as_renames_the_labeller(second: CatalogRepository) -> None:
    track = second.upsert_track(TrackRecord(source="jamendo", source_id="7", title="Seven"))
    mine = second.set_scene_label(track, "Ben", ["menu"], "mid", "labelled")  # made just now

    def row(scenes: list[str], stamp: str, **extra: object) -> dict:
        return {
            "labeller": "Ben", "source": "jamendo", "source_id": "7", "scenes": scenes,
            "intensity": None, "status": "labelled", "updated_at": stamp, **extra,
        }  # fmt: skip

    vocab = Vocabulary.default()
    older = import_labels(second, label_file([row(["town"], "2020-01-01T00:00:00Z")]), vocab)
    assert (older.stored, older.older) == (0, 1)
    assert second.get_scene_label(track, "Ben") == mine
    newer = import_labels(second, label_file([row(["town"], "2999-01-01T00:00:00+00:00")]), vocab)
    assert (newer.stored, newer.older) == (1, 0)
    won = second.get_scene_label(track, "Ben")
    assert won is not None and won.scenes == ("town",) and won.created_at == mine.created_at
    # --as stores the same labels under another name, next to the first
    renamed = import_labels(
        second, label_file([row(["puzzle"], "2020-01-01T00:00:00Z")]), vocab, as_labeller=" Cleo "
    )
    assert renamed.labellers == ["Cleo"] and renamed.stored == 1
    assert [x.labeller for x in second.iter_scene_labels()] == ["Ben", "Cleo"]


def test_unknown_tracks_are_reported_and_known_ones_still_stored(
    second: CatalogRepository,
) -> None:
    track = second.upsert_track(TrackRecord(source="jamendo", source_id="7", title="Seven"))
    rows = [
        {"labeller": "Ben", "source": "jamendo", "source_id": sid, "scenes": ["boss"],
         "intensity": "low", "status": "labelled", "updated_at": "2026-05-01T00:00:00Z"}
        for sid in ("7", "8", "9", "8")
    ]  # fmt: skip
    result = import_labels(second, label_file(rows), Vocabulary.default())
    assert result.stored == 1 and result.unknown == ["jamendo:8", "jamendo:9"]
    assert second.get_scene_label(track, "Ben") is not None


def test_an_unknown_scene_stores_nothing_and_is_named(second: CatalogRepository) -> None:
    second.upsert_track(TrackRecord(source="jamendo", source_id="7", title="Seven"))
    base = {"labeller": "Ben", "source": "jamendo", "source_id": "7", "intensity": None,
            "status": "labelled", "updated_at": "2026-05-01T00:00:00Z"}  # fmt: skip
    rows = [
        {**base, "scenes": ["boss"]},
        {**base, "scenes": ["karaoke", "boss", "disco"]},
    ]
    with pytest.raises(ValueError, match="'karaoke', 'disco'.*choose from: combat"):
        import_labels(second, label_file(rows), Vocabulary.default())
    assert second.iter_scene_labels() == []  # all or nothing
    for broken in (
        {**base, "scenes": [], "status": "maybe"},
        {**base, "scenes": [], "intensity": "loud"},
        {**base, "scenes": "boss"},
        {**base, "scenes": [], "updated_at": "yesterday"},
        {**base, "scenes": [], "labeller": ""},
    ):
        with pytest.raises(ValueError):
            import_labels(second, label_file([broken]), Vocabulary.default())
    with pytest.raises(ValueError, match="not a scene labels file"):
        import_labels(second, {"kind": "mcrar-scene-pack", "schema": 1}, Vocabulary.default())


# -- the CLI -----------------------------------------------------------------------------------


@pytest.fixture
def stub_client(monkeypatch: pytest.MonkeyPatch) -> ByIdJamendo:
    stub = ByIdJamendo(["101", "102", "103", "104", "105"])
    monkeypatch.setattr(cli, "_jamendo_client", lambda settings, use_cache: stub)
    return stub


def test_the_pack_commands_move_a_pool_between_catalogs(
    tmp_path: Path, stub_client: ByIdJamendo, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = get_settings()
    with open_catalog(owner) as repo:
        make_owner(repo)
    pack = tmp_path / "pack.json"
    done = runner.invoke(app, ["scenes", "export-pack", str(pack)])
    assert done.exit_code == 0 and "Wrote 5 tracks" in done.output
    assert json.loads(pack.read_text(encoding="utf-8"))["kind"] == "mcrar-scene-pack"

    monkeypatch.setenv("MCRAR_DATA_DIR", str(tmp_path / "collaborator-data"))  # their own catalog
    result = runner.invoke(app, ["scenes", "import-pack", str(pack)])
    assert result.exit_code == 0, result.output
    assert "Pool of 5 tracks: 0 were already here, 5 fetched." in result.output
    assert stub_client.lookups == [["101", "102", "103", "104", "105"]]
    refused = runner.invoke(app, ["scenes", "import-pack", str(pack)])
    assert refused.exit_code == 1 and "--force" in refused.output
    again = runner.invoke(app, ["scenes", "import-pack", str(pack), "--force", "--no-fetch"])
    assert again.exit_code == 0 and "5 were already here, 0 fetched" in again.output
    assert len(stub_client.lookups) == 1  # --no-fetch did not look anything up


def test_import_pack_without_a_jamendo_key_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with open_catalog(get_settings()) as repo:
        make_owner(repo)
    pack = tmp_path / "pack.json"
    assert runner.invoke(app, ["scenes", "export-pack", str(pack)]).exit_code == 0
    monkeypatch.setenv("MCRAR_DATA_DIR", str(tmp_path / "collaborator-data"))

    def no_key(settings: object, use_cache: bool) -> object:
        raise JamendoError(
            "No Jamendo client id is configured. mcrar secrets set jamendo_client_id"
        )

    monkeypatch.setattr(cli, "_jamendo_client", no_key)
    result = runner.invoke(app, ["scenes", "import-pack", str(pack)])
    assert result.exit_code == 1 and "No Jamendo client id" in result.output
    assert "Traceback" not in result.output
    with open_catalog(get_settings()) as theirs:
        assert theirs.label_pool() == []  # nothing was changed


def test_the_labels_commands_export_and_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with open_catalog(get_settings()) as repo:
        ids = make_owner(repo)
        repo.set_scene_label(ids["101"], "Ben", ["boss"], "high", "labelled")
        repo.set_scene_label(ids["102"], "Ann", ["town"], None, "labelled")
    out = tmp_path / "labels.json"
    done = runner.invoke(app, ["scenes", "export-labels", str(out), "--labeller", "Ben"])
    assert done.exit_code == 0 and "Wrote 1 labels" in done.output
    monkeypatch.setenv("MCRAR_DATA_DIR", str(tmp_path / "other-data"))
    with open_catalog(get_settings()) as other:
        make_owner(other)
    result = runner.invoke(app, ["scenes", "import-labels", str(out), "--as", "Ben2"])
    assert result.exit_code == 0, result.output
    assert "Stored 1 label(s) of Ben2" in result.output
    with open_catalog(get_settings()) as other:
        assert [x.labeller for x in other.iter_scene_labels()] == ["Ben2"]
    out.write_text(json.dumps(label_file([{"source": "jamendo", "source_id": "101",
        "scenes": ["karaoke"], "status": "labelled", "labeller": "x",
        "updated_at": "2026-01-01T00:00:00Z"}])), encoding="utf-8")  # fmt: skip
    bad = runner.invoke(app, ["scenes", "import-labels", str(out)])
    assert bad.exit_code == 1 and "'karaoke'" in bad.output and "Traceback" not in bad.output
    missing = runner.invoke(app, ["scenes", "import-labels", str(tmp_path / "nope.json")])
    assert missing.exit_code == 1 and "cannot read" in missing.output
