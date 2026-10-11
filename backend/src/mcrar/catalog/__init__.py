"""SQLite catalog: tracks, features, tag probabilities, embeddings, ingest log, shortlists.

All SQL lives in :mod:`mcrar.catalog.repository`; vector search sits behind
:class:`VectorIndex` so Postgres + pgvector can replace both later.
"""

from mcrar.catalog.db import MIGRATIONS, connect, migrate, open_catalog, open_path, schema_version
from mcrar.catalog.repository import (
    CatalogRepository,
    IngestEntry,
    Project,
    StoredTrack,
    TagProb,
    TrackRecord,
)
from mcrar.catalog.vector_index import NumpyVectorIndex, VectorIndex

__all__ = [
    "MIGRATIONS",
    "CatalogRepository",
    "IngestEntry",
    "NumpyVectorIndex",
    "Project",
    "StoredTrack",
    "TagProb",
    "TrackRecord",
    "VectorIndex",
    "connect",
    "migrate",
    "open_catalog",
    "open_path",
    "schema_version",
]
