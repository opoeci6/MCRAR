"""Health, the tag vocabulary and catalog statistics."""

from __future__ import annotations

import sys
from typing import Any

from fastapi import APIRouter

from mcrar import __version__
from mcrar.api.state import StateDep
from mcrar.recommend.vocab import LABEL_SETS

router = APIRouter()

_MB = 1024 * 1024


def _gpu() -> dict[str, int] | None:
    """CUDA memory in MB, only when torch is already imported (health never imports it)."""
    torch = sys.modules.get("torch")
    if torch is None:
        return None
    try:
        if not torch.cuda.is_available():
            return None
        return {
            "vram_allocated_mb": int(torch.cuda.memory_allocated() // _MB),
            "vram_reserved_mb": int(torch.cuda.memory_reserved() // _MB),
        }
    except Exception:  # a broken driver must not break the polled health check
        return None


@router.get("/api/health")
def health(state: StateDep) -> dict[str, Any]:
    """Status, catalog size, ``models_loaded`` (ready keys), ``models`` (``key``, ``state``
    loading/ready/error, ``device``, ``dtype``, ``error``; a loading model also has ``phase``
    downloading/loading and, while downloading, ``download`` with ``done_bytes`` and
    ``total_bytes``, which is ``null`` when unknown) and ``gpu`` (VRAM or ``None``)."""
    return {
        "status": "ok",
        "version": __version__,
        "catalog": {"tracks": state.repo.stats()["tracks"]},
        "models_loaded": state.pool.loaded_keys(),
        "models": state.pool.status(),
        "gpu": _gpu(),
    }


@router.get("/api/vocab")
def vocab(state: StateDep) -> dict[str, Any]:
    """The genre, mood/theme and scene labels a search can ask for, with names and synonyms."""
    vocabulary = state.search.vocab
    return {
        name: [
            {
                "id": label,
                "display": vocabulary.display_name(name, label),
                "synonyms": list(vocabulary.synonyms(name, label)),
            }
            for label in vocabulary.labels(name)
        ]
        for name in LABEL_SETS
        if name in vocabulary.label_set_names
    }


@router.get("/api/stats")
def stats(state: StateDep) -> dict[str, Any]:
    return state.repo.stats()
