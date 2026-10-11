"""MCRAR: ML music recommender for listeners and indie game devs."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("mcrar")
except PackageNotFoundError:  # not installed (e.g. running from a raw source tree)
    __version__ = "0+unknown"

__all__ = ["__version__"]
