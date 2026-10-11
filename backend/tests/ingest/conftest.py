from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from mcrar.catalog import CatalogRepository, open_path


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[CatalogRepository]:
    repository = open_path(tmp_path / "ingest-data" / "catalog.db")
    yield repository
    repository.close()
