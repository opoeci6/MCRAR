"""``build_stages``: the stage list shared by the CLI and the HTTP API."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

from mcrar import cli
from mcrar.config import get_settings
from mcrar.ingest import AnalysisStage, EmbeddingStage
from mcrar.ingest.stages import build_stages, tagging_stages_for


def embedder(key: str) -> SimpleNamespace:
    return SimpleNamespace(key=key, model_id=f"{key}-model")


class TaggingStage:
    name = "tag:genre"
    version = "v1"
    needs_audio = False


def fake_tagging_module(stage: TaggingStage) -> types.ModuleType:
    module = types.ModuleType("mcrar.ml.tagging")
    module.tagging_stages = lambda settings: [stage]  # type: ignore[attr-defined]
    return module


def test_no_embedders_means_the_pipeline_default() -> None:
    assert build_stages(get_settings(), []) is None


def test_analysis_then_one_embedding_stage_per_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "mcrar.ml.tagging", None)  # no tagging module
    stages = build_stages(get_settings(), [embedder("glap"), embedder("muq-mulan")])
    assert stages is not None
    assert [type(s) for s in stages] == [AnalysisStage, EmbeddingStage, EmbeddingStage]
    assert [s.name for s in stages] == ["analysis", "embed:glap", "embed:muq-mulan"]


def test_tagging_stages_follow_only_when_clap_is_embedded(monkeypatch: pytest.MonkeyPatch) -> None:
    tagging = TaggingStage()
    monkeypatch.setitem(sys.modules, "mcrar.ml.tagging", fake_tagging_module(tagging))
    with_clap = build_stages(get_settings(), [embedder("glap"), embedder("clap")])
    assert with_clap is not None and with_clap[-1] is tagging
    assert [s.name for s in with_clap[:-1]] == ["analysis", "embed:glap", "embed:clap"]
    without = build_stages(get_settings(), [embedder("glap")])
    assert without is not None and tagging not in without


def test_a_missing_tagging_module_adds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "mcrar.ml.tagging", None)
    assert tagging_stages_for(get_settings()) == []
    stages = build_stages(get_settings(), [embedder("clap")])
    assert stages is not None and [s.name for s in stages] == ["analysis", "embed:clap"]


def test_the_cli_seam_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    tagging = TaggingStage()
    monkeypatch.setitem(sys.modules, "mcrar.ml.tagging", fake_tagging_module(tagging))
    assert cli._tagging_stages(get_settings()) == [tagging]
