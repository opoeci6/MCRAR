"""``ModelPool``: the text-audio embedders the server keeps loaded.

Design
- A model is loaded at most once per key. Concurrent first requests for the same key wait for the
  one load (a lock per key), while a load of one key does not block the use of another.
- Every pool member is wrapped in :class:`LockedEmbedder`: ``embed_text`` and ``embed_audio`` run
  under one lock per model, because the torch models are not safe to call from several request
  threads at once. Other attributes are forwarded. ``close()`` on the wrapper does nothing: the
  pool owns the model, so a ``SearchService`` that is discarded does not unload it.
- Loading needs the ``ml`` extra. Without torch (or when a load fails) the pool raises
  :class:`ModelUnavailableError`, which the routes report as HTTP 503; filter-only requests never
  touch the pool.
- The licence mode is kept current with :meth:`ModelPool.update_settings`: models that are not
  commercially usable are unloaded when ``commercial_mode`` turns on, and ``load_embedder``
  refuses them while it is on.

Importing this module never imports torch; the default loader imports ``load_embedder`` lazily.
"""

from __future__ import annotations

import importlib.util
import logging
import threading
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

import numpy as np

from mcrar.ml import ModelError

if TYPE_CHECKING:
    from mcrar.config import Settings

log = logging.getLogger(__name__)

EmbedderFactory = Callable[[str, "Settings"], Any]
NO_TORCH_MESSAGE = "text search needs the ml extra (torch is not installed)"


class ModelUnavailableError(RuntimeError):
    """A model cannot be used right now (no ml extra, refused by the licence mode, load failed).

    The message is fit to show to the user as it is.
    """


def torch_installed() -> bool:
    """Whether the ``ml`` extra is installed (does not import torch)."""
    return importlib.util.find_spec("torch") is not None


def default_factory(key: str, settings: Settings) -> Any:
    from mcrar.ml.embedders import load_embedder

    return load_embedder(key, settings=settings)


class LockedEmbedder:
    """Serialises the model calls of one embedder and forwards everything else to it."""

    def __init__(self, embedder: Any) -> None:
        self._embedder = embedder
        self._lock = threading.Lock()

    def embed_text(self, texts: Sequence[str]) -> np.ndarray:
        with self._lock:
            return self._embedder.embed_text(texts)

    def embed_audio(self, clips: Sequence[np.ndarray]) -> np.ndarray:
        with self._lock:
            return self._embedder.embed_audio(clips)

    def close(self) -> None:
        """No-op: the pool closes the model (see the module docstring)."""

    def unload(self) -> None:
        with self._lock:
            close = getattr(self._embedder, "close", None)
            if close is not None:
                close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._embedder, name)


class ModelPool:
    def __init__(
        self,
        settings: Settings,
        *,
        factory: EmbedderFactory | None = None,
        torch_available: Callable[[], bool] | None = None,
    ) -> None:
        self._settings = settings
        self._factory = factory or default_factory
        self._torch_available = torch_available or torch_installed
        self._lock = threading.Lock()
        self._load_locks: dict[str, threading.Lock] = {}
        self._models: dict[str, LockedEmbedder] = {}
        self._closed = False

    # -- use -------------------------------------------------------------------------------

    def get(self, key: str) -> LockedEmbedder:
        """The embedder ``key``, loading it on first use (raises :class:`ModelUnavailableError`)."""
        with self._lock:
            if self._closed:
                raise ModelUnavailableError("the server is shutting down")
            model = self._models.get(key)
            if model is not None:
                return model
            load_lock = self._load_locks.setdefault(key, threading.Lock())
        with load_lock:
            with self._lock:
                model = self._models.get(key)
                settings = self._settings
            if model is not None:  # another request loaded it while this one waited
                return model
            return self._load(key, settings)

    def _load(self, key: str, settings: Settings) -> LockedEmbedder:
        if not self._torch_available():
            raise ModelUnavailableError(NO_TORCH_MESSAGE)
        try:
            embedder = self._factory(key, settings)
        except ModelError as exc:
            raise ModelUnavailableError(str(exc)) from None
        except Exception as exc:  # a broken install or file: never leak details to the client
            log.warning("could not load model %s (%s)", key, type(exc).__name__)
            raise ModelUnavailableError(
                f"could not load model '{key}' ({type(exc).__name__})"
            ) from None
        model = LockedEmbedder(embedder)
        with self._lock:
            # The pool closed, or the licence mode turned commercial, while the model loaded.
            refused = self._settings.commercial_mode and not getattr(model, "commercial_ok", True)
            keep = not (self._closed or refused)
            if keep:
                self._models[key] = model
        if not keep:
            model.unload()
            raise ModelUnavailableError(f"model '{key}' was unloaded while it was loading")
        return model

    def loader(self, key: str) -> Callable[[], LockedEmbedder]:
        """A zero-argument loader for ``SearchService(embedder_loader=...)``."""
        return lambda: self.get(key)

    def loaded_keys(self) -> list[str]:
        with self._lock:
            return sorted(self._models)

    # -- settings and lifecycle --------------------------------------------------------------

    def update_settings(self, settings: Settings) -> None:
        """Use new settings for later loads; unload models the new licence mode does not allow."""
        with self._lock:
            self._settings = settings
            drop = (
                [k for k, m in self._models.items() if not getattr(m, "commercial_ok", True)]
                if settings.commercial_mode
                else []
            )
            dropped = [self._models.pop(k) for k in drop]
        for model in dropped:
            model.unload()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            models = list(self._models.values())
            self._models.clear()
        for model in models:
            try:
                model.unload()
            except Exception as exc:  # closing must not stop the other models from closing
                log.warning("could not close a model (%s)", type(exc).__name__)
