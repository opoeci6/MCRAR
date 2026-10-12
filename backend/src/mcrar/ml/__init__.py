"""Machine-learning models. Importing this package never imports torch; model code is lazy."""

from mcrar.ml.errors import (
    CommercialModeError,
    EmbedderMemoryError,
    MLDependencyError,
    ModelError,
    ModelLoadError,
)
from mcrar.ml.registry import MODELS, ModelSpec, RepoPin, get_spec, parse_model_keys

__all__ = [
    "MODELS",
    "CommercialModeError",
    "EmbedderMemoryError",
    "MLDependencyError",
    "ModelError",
    "ModelLoadError",
    "ModelSpec",
    "RepoPin",
    "get_spec",
    "parse_model_keys",
]
