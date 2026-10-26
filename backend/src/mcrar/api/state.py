"""``AppState``: what the server owns for its whole lifetime, and ``ApiDeps``, the test seams.

One state is built when the app starts (the lifespan in :mod:`mcrar.api.app`) and closed when it
stops. It holds the catalog repository, the :class:`~mcrar.api.models.ModelPool`, the
:class:`~mcrar.recommend.SearchService` that uses the pool, a factory for Jamendo clients and the
cache of fresh Jamendo stream URLs, the :class:`~mcrar.api.references.ReferenceStore` of uploaded
reference songs and the :class:`~mcrar.api.jobs.JobManager` that runs ingest jobs. Routes get it
through :func:`get_state`.

``reload_settings`` swaps the settings at run time (the settings page): it tells the pool and
rebuilds the search service when the default embedder, the search settings or the LLM settings
changed, because those decide which models and stored tags may be used, how results rank and
whether the LLM parses queries. The :class:`~mcrar.llm.client.LLMClient` reads the API key from
the secret store on every call, so a key saved on the settings page needs no reload.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, Request

from mcrar.api.jobs import JobManager
from mcrar.api.models import ModelPool, ModelUnavailableError, torch_installed
from mcrar.api.references import ReferenceStore
from mcrar.catalog import CatalogRepository, open_catalog
from mcrar.llm.client import LLMClient, ProviderFactory
from mcrar.recommend import SearchService, StoredTagScorer
from mcrar.recommend.llm_parse import LLMParser
from mcrar.recommend.tags import allowed_tag_versions
from mcrar.secrets import SecretError, SecretStore

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
    llm_provider_factory: ProviderFactory | None = None  # (preset, model, base_url, key)
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
        self.references = ReferenceStore()
        self.torch_available: Callable[[], bool] = deps.torch_available or torch_installed
        self.jobs = JobManager()
        self._lock = threading.Lock()
        self._llm_factory = deps.llm_provider_factory
        try:
            self.llm = self._build_llm(settings)
            self.stored_tags, self.search = self._build_search(settings)
        except BaseException:
            self.pool.close()
            if self._owns_repo:
                self.repo.close()
            raise

    # -- search service ----------------------------------------------------------------------

    def _build_llm(self, settings: Settings) -> LLMClient:
        try:
            secrets: SecretStore | None = SecretStore(settings)
        except SecretError:  # e.g. the keyring backend without its package: no key can be read
            secrets = None
        return LLMClient(settings, secrets, provider_factory=self._llm_factory)

    def _build_search(self, settings: Settings) -> tuple[StoredTagScorer, SearchService]:
        stored = StoredTagScorer(self.repo, allowed_tag_versions(settings))
        parser = LLMParser(self.llm, settings.llm.parse_timeout_s) if settings.llm.enabled else None
        service = SearchService(
            self.repo,
            settings,
            embedder_loader=self.pool.loader(settings.default_embedder),
            stored_tags=stored,
            parser=parser,
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
            if (new_settings.default_embedder, new_settings.search, new_settings.llm) != (
                old.default_embedder,
                old.search,
                old.llm,
            ):
                old_search = self.search
                self.llm = self._build_llm(new_settings)
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
        self.jobs.close()  # a running job uses the pool and the repo: stop it first
        with self._lock:
            self.search.close()
            self.pool.close()
            self.stream_urls.clear()
            self.references.clear()
            if self._owns_repo:
                self.repo.close()


def get_state(request: Request) -> AppState:
    """FastAPI dependency: the state the lifespan stored on the app."""
    return request.app.state.mcrar


StateDep = Annotated[AppState, Depends(get_state)]
