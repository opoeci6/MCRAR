"""Ingest: map source tracks to catalog rows and run per-track stages (analysis, ...)."""

from mcrar.ingest.mapping import to_track_record
from mcrar.ingest.pipeline import (
    AnalysisStage,
    IngestEvent,
    IngestFailure,
    IngestReport,
    JamendoQuery,
    Stage,
    ingest_jamendo,
    ingest_local,
)

__all__ = [
    "AnalysisStage",
    "IngestEvent",
    "IngestFailure",
    "IngestReport",
    "JamendoQuery",
    "Stage",
    "ingest_jamendo",
    "ingest_local",
    "to_track_record",
]
