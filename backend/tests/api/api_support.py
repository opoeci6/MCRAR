"""Shared helpers for the HTTP API tests (not a test module; unique basename on purpose).

``make_client`` builds the app over a tmp catalog filled with the synthetic tracks of
``recommend_support``, with every outside dependency faked: the embedding model, Jamendo and
"torch is installed". Nothing here imports torch.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

for _folder in ("recommend", "ml"):  # tests/ has no __init__.py: import the sibling helpers
    _path = str(Path(__file__).resolve().parents[1] / _folder)
    if _path not in sys.path:
        sys.path.insert(0, _path)

from recommend_support import (  # noqa: E402
    QUERY_TEXTS,
    FakeJamendoClient,
    MapEmbedder,
    build_catalog,
)
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


# -- ingest jobs ---------------------------------------------------------------------------------


class IngestJamendo(FakeJamendoClient):
    """A Jamendo client for the ingest routes: ``count`` new tracks (source ids from 9001, which
    the synthetic catalog does not use), synthetic audio, nothing else."""

    FIRST_ID = 9001

    def __init__(self, count: int = 3) -> None:
        super().__init__(count)
        self.queries: list[dict[str, Any]] = []

    def search_tracks(self, **kwargs: Any) -> Iterator[SourceTrack]:
        self.queries.append(kwargs)
        return iter(
            SourceTrack(
                source="jamendo",
                source_id=str(self.FIRST_ID + n),
                title=f"New Track {n + 1}",
                artist=f"New Artist {n + 1}",
                stream_url=f"https://audio.example/{self.FIRST_ID + n}",
                license_url="https://creativecommons.org/licenses/by/4.0/",
            )
            for n in range(min(self.count, kwargs.get("limit", self.count)))
        )


def wait_done(client: ApiClient, job_id: str, timeout_s: float = 30.0) -> dict[str, Any]:
    """Block until the job ended (no polling sleeps: it waits on the job's condition) and return
    its detail as the API shows it."""
    job = client.app.state.mcrar.jobs.get(job_id)
    deadline = time.monotonic() + timeout_s
    seen = 0
    while True:
        events, ended = job.wait_for_events(seen, 0.5)
        seen += len(events)
        if ended:
            return client.get(f"/api/jobs/{job_id}").json()["job"]
        if time.monotonic() > deadline:
            raise AssertionError(f"job {job_id} did not end within {timeout_s} s")


def parse_sse(text: str) -> list[dict[str, Any]]:
    """The events of an SSE body as ``{"id", "event", "data"}`` dicts (comments are skipped)."""
    events = []
    for block in text.split("\n\n"):
        lines = [line for line in block.split("\n") if line and not line.startswith(":")]
        if not lines:
            continue
        fields = dict(line.split(": ", 1) for line in lines)
        events.append(
            {"id": int(fields["id"]), "event": fields["event"], "data": json.loads(fields["data"])}
        )
    return events
