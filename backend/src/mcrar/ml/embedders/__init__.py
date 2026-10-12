"""Text-audio embedders behind one interface (CLAP, GLAP, MuQ-MuLan).

Importing this package does not import torch: the model code is loaded by ``load_embedder``.
"""

from mcrar.ml.embedders.base import Embedder, embed_track, l2_normalize, track_windows
from mcrar.ml.embedders.loader import load_embedder

__all__ = ["Embedder", "embed_track", "l2_normalize", "load_embedder", "track_windows"]
