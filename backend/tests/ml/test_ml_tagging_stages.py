"""Stored embeddings are sufficient for catalog tagging, including Jamendo rows."""

from __future__ import annotations

import pytest
from ml_support import FakeJamendo, add_jamendo
from tagging_support import fixture_tagger, synthetic

from mcrar.config import Settings
from mcrar.ingest import needs_audio, reprocess_catalog
from mcrar.ml.tagging import TaggingStage, tagging_stages


def test_fresh_workspace_ingest_has_no_tagging_stages(tmp_path) -> None:
    settings = Settings(home=tmp_path)
    assert tagging_stages(settings) == []
    settings.models_dir.mkdir(parents=True)
    (settings.models_dir / "registry.json").write_text('{"schema": 999}')
    with pytest.raises(ValueError, match="registry requires"):
        tagging_stages(settings)


@pytest.mark.parametrize("method", ["head", "zeroshot"])
def test_stage_version_method_and_reprocess_without_audio(repo, method: str) -> None:
    tid = add_jamendo(repo, 1)
    x, _ = synthetic(3)
    repo.set_embedding(tid, "clap@195c3a3", x[0])
    t = fixture_tagger(method=method)
    stage = TaggingStage(t)
    assert needs_audio(stage) is False and stage.name == "tag:genre"
    assert not stage.is_current(repo, tid)
    client = FakeJamendo()
    report = reprocess_catalog(repo, stages=[stage], client=client)
    assert (report.processed, report.failed) == (1, 0)
    assert not client.fetched and not client.get_calls
    assert stage.is_current(repo, tid)
    assert all(
        row.method == method and row.model_version == t.entry_id for row in repo.get_tag_probs(tid)
    )
    stage.version = "changed"
    assert not stage.is_current(repo, tid)


def test_stage_missing_embedding_is_a_clear_failure(repo) -> None:
    tid = add_jamendo(repo, 1)
    stage = TaggingStage(fixture_tagger())
    with pytest.raises(ValueError, match="no clap@195c3a3 embedding"):
        stage.run(repo, tid)
    report = reprocess_catalog(repo, stages=[stage])
    assert report.failed == 1 and "no clap@195c3a3" in report.failures[0].message
