"""Calibrated tagging from stored CLAP vectors, with licence-aware model selection."""

from mcrar.config import Settings
from mcrar.ml.tagging.registry import load_taggers, select_entry
from mcrar.ml.tagging.runtime import Tagger, TaggingStage


def tagging_stages(settings: Settings) -> list[TaggingStage]:
    # Ingest may run in a fresh workspace before any tagging artifacts are installed.
    if not (settings.models_dir / "registry.json").is_file():
        return []
    return [TaggingStage(t) for t in load_taggers(settings)]


__all__ = ["Tagger", "TaggingStage", "load_taggers", "select_entry", "tagging_stages"]
