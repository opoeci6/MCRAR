"""``ReferenceStore``: the embeddings of uploaded reference songs, kept in memory.

``POST /api/reference`` embeds an upload once and hands back an ``upload_id``; searches then name
that id instead of sending the audio again. Only the vector, the model id it came from, the base
file name and the duration are kept (never the audio). The store holds the last ``max_entries``
songs (least recently used goes first) and is lost on restart, so a client must be ready to
upload again when an id is unknown.
"""

from __future__ import annotations

import secrets
import threading
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np

REFERENCE_STORE_MAX = 32


@dataclass(frozen=True)
class StoredReference:
    vector: np.ndarray
    model_id: str  # the embedding model the vector belongs to
    filename: str
    duration_s: float


class ReferenceStore:
    """Thread-safe LRU of uploaded references, keyed by an unguessable id."""

    def __init__(self, max_entries: int = REFERENCE_STORE_MAX) -> None:
        self._max = max_entries
        self._lock = threading.Lock()
        self._items: OrderedDict[str, StoredReference] = OrderedDict()

    def put(self, reference: StoredReference) -> str:
        """Store ``reference`` and return its id, dropping the least recently used one if full."""
        upload_id = secrets.token_urlsafe(12)
        with self._lock:
            self._items[upload_id] = reference
            while len(self._items) > self._max:
                self._items.popitem(last=False)
        return upload_id

    def get(self, upload_id: str) -> StoredReference | None:
        """The stored reference (it becomes the most recently used), or None."""
        with self._lock:
            reference = self._items.get(upload_id)
            if reference is not None:
                self._items.move_to_end(upload_id)
            return reference

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
