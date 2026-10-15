"""Which stages an ingest run uses, shared by the CLI and the HTTP API.

Design
- The caller loads (and later frees) the embedding models; :func:`build_stages` only turns the
  loaded embedders into the stage list: analysis, one embedding stage per model, then the tagging
  stages. Tagging reads the CLAP vector, so its stages are added only when ``clap`` is among the
  embedders.
- No embedders means "analysis only": the result is ``None``, which the pipeline reads as its
  default stage list.
- The tagging module is imported lazily and a missing one (``ImportError``) means no tagging
  stages, so importing this module stays cheap and works without the ``ml`` extra.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from mcrar.ingest.pipeline import AnalysisStage, EmbeddingStage, Stage

if TYPE_CHECKING:
    from mcrar.config import Settings
    from mcrar.ml.embedders.base import Embedder

TAGGING_EMBEDDER = "clap"


def tagging_stages_for(settings: Settings) -> list[Stage]:
    """The tagging stages of the installed heads (none when the tagging module is missing)."""
    try:
        from mcrar.ml.tagging import tagging_stages
    except ImportError:
        return []
    return list(tagging_stages(settings))


def build_stages(settings: Settings, embedders: Sequence[Embedder]) -> list[Stage] | None:
    """Analysis, an embedding stage per loaded embedder, then tagging; None without embedders."""
    if not embedders:
        return None
    stages: list[Stage] = [AnalysisStage(), *(EmbeddingStage(e) for e in embedders)]
    if any(e.key == TAGGING_EMBEDDER for e in embedders):
        stages += tagging_stages_for(settings)
    return stages
