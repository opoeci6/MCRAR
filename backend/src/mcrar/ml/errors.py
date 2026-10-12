"""Errors of the ML layer. Messages are meant to be shown to the user as they are."""

from __future__ import annotations


class ModelError(RuntimeError):
    """Base class for model registry, download and loading errors."""


class CommercialModeError(ModelError):
    """A non-commercial model was requested while ``commercial_mode`` is on."""


class MLDependencyError(ModelError):
    """The optional ``ml`` extra (torch, transformers, ...) is not installed."""


class ModelLoadError(ModelError):
    """A model could not be downloaded or loaded."""


class EmbedderMemoryError(ModelError):
    """The GPU ran out of memory while loading or running a model."""
