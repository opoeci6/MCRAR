"""Placeholder router, filled by a later M5 slice: POST ingest with SSE progress.

It exists now so that ``mcrar.api.app`` registers every router once and later slices only add
endpoints here.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()
