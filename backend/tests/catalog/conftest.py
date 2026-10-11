from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mcrar.catalog import CatalogRepository, open_path


class FakeClock:
    """Deterministic clock; every call advances one second."""

    def __init__(self) -> None:
        self._now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        self._now += timedelta(seconds=1)
        return self._now


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[CatalogRepository]:
    repository = open_path(tmp_path / "data" / "catalog.db")
    repository._clock = FakeClock()
    yield repository
    repository.close()
