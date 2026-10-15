"""Ingest: map source tracks to catalog rows and run per-track stages (analysis, embeddings)."""

from mcrar.ingest.mapping import to_track_record
from mcrar.ingest.pipeline import (
    AnalysisStage,
    EmbeddingStage,
    IngestEvent,
    IngestFailure,
    IngestReport,
    JamendoQuery,
    Stage,
    ingest_jamendo,
    ingest_jamendo_queries,
    ingest_local,
    needs_audio,
    reprocess_catalog,
)

__all__ = [
    "AnalysisStage",
    "EmbeddingStage",
    "IngestEvent",
    "IngestFailure",
    "IngestReport",
    "JamendoQuery",
    "Stage",
    "ingest_jamendo",
    "ingest_jamendo_queries",
    "ingest_local",
    "needs_audio",
    "reprocess_catalog",
    "to_track_record",
]
