"""Shared helpers for the HTTP API tests (not a test module; unique basename on purpose).

``make_client`` builds the app over a tmp catalog filled with the synthetic tracks of
``recommend_support``, with every outside dependency faked: the embedding model, Jamendo and
"torch is installed". Nothing here imports torch.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

for _folder in ("recommend", "ml"):  # tests/ has no __init__.py: import the sibling helpers
    _path = str(Path(__file__).resolve().parents[1] / _folder)
    if _path not in sys.path:
        sys.path.insert(0, _path)

from recommend_support import QUERY_TEXTS, MapEmbedder, build_catalog  # noqa: E402
from tagging_support import register as register_tagging  # noqa: E402,F401

from mcrar.api.app import create_app  # noqa: E402
from mcrar.api.state import ApiDeps  # noqa: E402
from mcrar.catalog import CatalogRepository, open_path  # noqa: E402
from mcrar.config import Settings, get_settings  # noqa: E402
from mcrar.sources import SourceTrack  # noqa: E402

TEST_HOST = "testserver"


class FakeStreamJamendo:
    """Stands in for ``JamendoClient`` in the stream route: counts lookups, can fail."""

    def __init__(self, urls: dict[str, str | None] | None = None, error: Exception | None = None):
        self.urls = urls if urls is not None else {}
        self.error = error
        self.lookups: list[list[str]] = []
        self.closed = 0

    def get_tracks(self, ids: Sequence[str | int], **kwargs: Any) -> list[SourceTrack]:
        self.lookups.append([str(i) for i in ids])
        if self.error is not None:
            raise self.error
        return [
            SourceTrack(
                source="jamendo",
                source_id=str(i),
                title="t",
                artist="a",
                stream_url=self.urls.get(str(i)),
            )
            for i in ids
            if str(i) in self.urls
        ]

    def close(self) -> None:
        self.closed += 1


class LoaderSpy:
    """The embedder loader: records the keys it was asked for and hands out one embedder."""

    def __init__(self, embedder: MapEmbedder) -> None:
        self.embedder = embedder
        self.keys: list[str] = []

    def __call__(self, key: str, settings: Settings) -> MapEmbedder:
        self.keys.append(key)
        return self.embedder


class ApiClient(TestClient):
    """A ``TestClient`` that also carries the fakes and the catalog it was built over."""

    repo: CatalogRepository
    ids: dict[str, int]
    settings: Settings
    embedder: MapEmbedder
    loader: LoaderSpy
    jamendo: FakeStreamJamendo | Exception | None

    def __exit__(self, *args: Any) -> None:
        try:
            super().__exit__(*args)
        finally:
            self.repo.close()


def make_client(
    tmp_path: Path,
    *,
    embedder: MapEmbedder | None = None,
    jamendo: FakeStreamJamendo | Exception | None = None,
    torch: bool = True,
    settings_overrides: dict[str, Any] | None = None,
    warm: bool | None = None,
) -> ApiClient:
    """Use as ``with make_client(tmp_path) as client:`` so the app's lifespan runs.

    ``jamendo`` is the fake client; an exception instance makes the factory raise it (the way a
    missing client id does). ``torch=False`` makes the pool report that the ml extra is missing.
    """
    options: dict[str, Any] = {"data_dir": tmp_path / "api-data", "search": {"max_per_artist": 50}}
    options.update(settings_overrides or {})
    settings = get_settings(**options)
    repo = open_path(settings.data_dir / "catalog.db")
    ids = build_catalog(repo)
    embedder = embedder or MapEmbedder(QUERY_TEXTS)
    loader = LoaderSpy(embedder)

    def jamendo_factory(_settings: Settings) -> Any:
        if isinstance(jamendo, Exception):
            raise jamendo
        return jamendo

    deps = ApiDeps(
        embedder_loader=loader,
        jamendo_factory=jamendo_factory,
        torch_available=lambda: torch,
        repo=repo,
        extra_hosts=(TEST_HOST,),
    )
    client = ApiClient(create_app(settings, deps=deps, warm=warm))
    client.repo, client.ids, client.settings = repo, ids, settings
    client.embedder, client.loader, client.jamendo = embedder, loader, jamendo
    return client
