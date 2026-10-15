"""``AppState``: what the server owns for its whole lifetime, and ``ApiDeps``, the test seams.

One state is built when the app starts (the lifespan in :mod:`mcrar.api.app`) and closed when it
stops. It holds the catalog repository, the :class:`~mcrar.api.models.ModelPool`, the
:class:`~mcrar.recommend.SearchService` that uses the pool, a factory for Jamendo clients and the
cache of fresh Jamendo stream URLs. Routes get it through :func:`get_state`.

``reload_settings`` swaps the settings at run time (the settings page): it tells the pool and
rebuilds the search service when the licence mode, the default embedder or the search settings
changed, because those decide which models and stored tags may be used and how results rank.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, Request

from mcrar.api.models import ModelPool, ModelUnavailableError
from mcrar.catalog import CatalogRepository, open_catalog
from mcrar.recommend import SearchService, StoredTagScorer
from mcrar.recommend.tags import allowed_tag_versions

if TYPE_CHECKING:
    from mcrar.config import Settings

log = logging.getLogger(__name__)

STREAM_URL_TTL_S = 30 * 60  # Jamendo stream URLs expire; a fresh one is good for a while
STREAM_CACHE_MAX = 2048


@dataclass(frozen=True)
class ApiDeps:
    """Replacements for the parts of the server that need models, the network or a secret.

    Tests pass fakes; the real server passes nothing. ``extra_hosts`` are additional ``Host``
    header values the app accepts (the test client's ``testserver``); never set by the CLI.
    """

    embedder_loader: Callable[[str, Settings], Any] | None = None
    jamendo_factory: Callable[[Settings], Any] | None = None
    torch_available: Callable[[], bool] | None = None
    repo: CatalogRepository | None = None  # not closed by the app when given
    extra_hosts: tuple[str, ...] = ()


class StreamUrlCache:
    """Fresh stream URLs per track id, kept ``ttl_s`` seconds (thread-safe, size-bounded)."""

    def __init__(
        self,
        ttl_s: float = STREAM_URL_TTL_S,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_entries: int = STREAM_CACHE_MAX,
    ) -> None:
        self._ttl_s = ttl_s
        self._clock = clock
        self._max = max_entries
        self._lock = threading.Lock()
        self._items: dict[int, tuple[float, str]] = {}

    def get(self, track_id: int) -> str | None:
        with self._lock:
            hit = self._items.get(track_id)
            if hit is None:
                return None
            if self._clock() >= hit[0]:
                del self._items[track_id]
                return None
            return hit[1]

    def put(self, track_id: int, url: str) -> None:
        with self._lock:
            if len(self._items) >= self._max and track_id not in self._items:
                now = self._clock()
                self._items = {k: v for k, v in self._items.items() if v[0] > now}
                if len(self._items) >= self._max:  # still full: drop the oldest entry
                    del self._items[min(self._items, key=lambda k: self._items[k][0])]
            self._items[track_id] = (self._clock() + self._ttl_s, url)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


def default_jamendo_factory(settings: Settings) -> Any:
    from mcrar.sources import JamendoClient

    return JamendoClient.from_settings(settings)


class AppState:
    def __init__(self, settings: Settings, deps: ApiDeps | None = None) -> None:
        deps = deps or ApiDeps()
        self.settings = settings
        self._owns_repo = deps.repo is None
        self.repo: CatalogRepository = deps.repo or open_catalog(settings)
        self.pool = ModelPool(
            settings, factory=deps.embedder_loader, torch_available=deps.torch_available
        )
        self.jamendo_factory: Callable[[Settings], Any] = (
            deps.jamendo_factory or default_jamendo_factory
        )
        self.stream_urls = StreamUrlCache()
        self._lock = threading.Lock()
        try:
            self.stored_tags, self.search = self._build_search(settings)
        except BaseException:
            self.pool.close()
            if self._owns_repo:
                self.repo.close()
            raise

    # -- search service ----------------------------------------------------------------------

    def _build_search(self, settings: Settings) -> tuple[StoredTagScorer, SearchService]:
        stored = StoredTagScorer(self.repo, allowed_tag_versions(settings))
        service = SearchService(
            self.repo,
            settings,
            embedder_loader=self.pool.loader(settings.default_embedder),
            stored_tags=stored,
        )
        return stored, service

    @property
    def tag_versions(self) -> dict[str, str | None]:
        """Per label set, the tagging model version whose stored tags may be shown."""
        return dict(self.stored_tags.allowed_versions or {})

    def reload_settings(self, new_settings: Settings) -> None:
        """Use ``new_settings`` from now on (used by the settings routes)."""
        with self._lock:
            old = self.settings
            self.settings = new_settings
            self.pool.update_settings(new_settings)
            # The search service reads its pool size and weights from settings.search too.
            if (
                new_settings.commercial_mode,
                new_settings.default_embedder,
                new_settings.search,
            ) != (
                old.commercial_mode,
                old.default_embedder,
                old.search,
            ):
                old_search = self.search
                self.stored_tags, self.search = self._build_search(new_settings)
                old_search.close()

    # -- Jamendo -------------------------------------------------------------------------------

    def open_jamendo(self) -> Any:
        """A Jamendo client for one request; the caller closes it. Raises ``JamendoError`` when
        the client id secret is not set."""
        return self.jamendo_factory(self.settings)

    # -- models and lifecycle ---------------------------------------------------------------

    def warm(self) -> threading.Thread:
        """Load the default embedder in the background (``mcrar serve --warm``)."""

        def load() -> None:
            try:
                self.pool.get(self.settings.default_embedder)
            except ModelUnavailableError as exc:
                log.warning("warm-up skipped: %s", exc)

        thread = threading.Thread(target=load, name="mcrar-warm", daemon=True)
        thread.start()
        return thread

    def close(self) -> None:
        with self._lock:
            self.search.close()
            self.pool.close()
            self.stream_urls.clear()
            if self._owns_repo:
                self.repo.close()


def get_state(request: Request) -> AppState:
    """FastAPI dependency: the state the lifespan stored on the app."""
    return request.app.state.mcrar


StateDep = Annotated[AppState, Depends(get_state)]
