"""The model registry: what each embedding model is, which exact revision we run, its licence.

Everything here is plain data plus light helpers; it never imports torch (``huggingface_hub`` is
imported lazily and only for the download helpers). Every Hugging Face repository is pinned to a
commit hash, including the repositories that MuQ-MuLan pulls in by name (its audio backbone and
text tower), so a model never changes under our feet and remote code or pickle files only ever
come from a revision we looked at.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from mcrar.ml.errors import MLDependencyError, ModelError, ModelLoadError

if TYPE_CHECKING:
    from mcrar.config import Settings


@dataclass(frozen=True)
class RepoPin:
    """One Hugging Face repository at one commit, and the files of it we use."""

    repo: str
    revision: str  # full 40-character commit hash
    files: tuple[str, ...]


@dataclass(frozen=True)
class ModelSpec:
    """A text-audio embedding model.

    ``window_s`` is the audio length the model natively takes; ``sample_rate`` the rate it
    expects; ``dim`` the size of the shared text/audio space. ``commercial_ok`` describes the
    licence of the *weights*. ``weights`` is the main repository; ``extra`` lists repositories
    the model package loads by name, which we also pin and load from local snapshots.
    """

    key: str
    title: str
    weights: RepoPin
    license: str
    commercial_ok: bool
    sample_rate: int
    window_s: float
    dim: int
    extra: tuple[RepoPin, ...] = ()

    @property
    def repo(self) -> str:
        return self.weights.repo

    @property
    def revision(self) -> str:
        return self.weights.revision

    @property
    def model_id(self) -> str:
        """The key used in the ``embeddings`` table: ``<key>@<first 7 chars of the revision>``."""
        return f"{self.key}@{self.revision[:7]}"

    @property
    def pins(self) -> tuple[RepoPin, ...]:
        return (self.weights, *self.extra)


MODELS: dict[str, ModelSpec] = {
    spec.key: spec
    for spec in (
        ModelSpec(
            key="clap",
            title="LAION CLAP larger_clap_music_and_speech",
            weights=RepoPin(
                "laion/larger_clap_music_and_speech",
                "195c3a3e68faebb3e2088b9a79e79b43ddbda76b",
                (
                    "config.json",
                    "preprocessor_config.json",
                    "pytorch_model.bin",
                    "merges.txt",
                    "special_tokens_map.json",
                    "tokenizer.json",
                    "tokenizer_config.json",
                    "vocab.json",
                ),
            ),
            license="Apache-2.0",
            commercial_ok=True,
            sample_rate=48_000,
            window_s=10.0,
            dim=512,
        ),
        ModelSpec(
            key="glap",
            title="GLAP (Xiaomi, mispeech/GLAP)",
            weights=RepoPin(
                "mispeech/GLAP",
                "79b13014511e2d5628cb57c4712a90edd19cebbd",
                (
                    "__init__.py",
                    "config.json",
                    "configuration_glap.py",
                    "modeling_glap.py",
                    "model.safetensors",
                    "sentencepiece.source.256000.model",
                ),
            ),
            license="Apache-2.0",
            commercial_ok=True,
            sample_rate=16_000,
            window_s=10.0,
            dim=1024,
        ),
        ModelSpec(
            key="muq-mulan",
            title="MuQ-MuLan-large (Tencent)",
            weights=RepoPin(
                "OpenMuQ/MuQ-MuLan-large",
                "2e01c796b71dca71b45251384c04cd7b237c9020",
                ("config.json", "pytorch_model.bin"),
            ),
            license="CC-BY-NC-4.0",
            commercial_ok=False,
            sample_rate=24_000,
            window_s=10.0,
            dim=512,
            extra=(
                RepoPin(
                    "OpenMuQ/MuQ-large-msd-iter",
                    "0562a57814f6f8bbd9fdea0a25921a2fce1a841a",
                    ("config.json", "model.safetensors"),
                ),
                RepoPin(
                    "FacebookAI/xlm-roberta-base",
                    "e73636d4f797dec63c3081bb6ed5c7b0bb3f2089",
                    (
                        "config.json",
                        "model.safetensors",
                        "sentencepiece.bpe.model",
                        "tokenizer.json",
                        "tokenizer_config.json",
                    ),
                ),
            ),
        ),
    )
}


def get_spec(key: str) -> ModelSpec:
    try:
        return MODELS[key]
    except KeyError:
        raise ModelError(f"unknown model '{key}'; choose from: {', '.join(MODELS)}") from None


def parse_model_keys(value: str | Iterable[str]) -> list[str]:
    """``"clap, glap"`` (or an iterable) to validated, de-duplicated keys in the given order."""
    parts = value.split(",") if isinstance(value, str) else list(value)
    keys = list(dict.fromkeys(p.strip() for p in parts if p.strip()))
    if not keys:
        raise ModelError(f"no models given; choose from: {', '.join(MODELS)}")
    for key in keys:
        get_spec(key)
    return keys


# -- Hugging Face cache ------------------------------------------------------------------


def configure_hf_cache(settings: Settings) -> None:
    """Keep model weights under ``<cache_dir>/huggingface`` unless ``HF_HOME`` is already set.

    The dev environment sets ``HF_HOME`` to the same place. This must run before
    ``huggingface_hub`` or ``transformers`` is first imported, because they read it on import.
    """
    os.environ.setdefault("HF_HOME", str(settings.cache_dir / "huggingface"))


def _hub():  # noqa: ANN202 - lazy import of an optional dependency
    try:
        import huggingface_hub
    except ImportError:
        raise MLDependencyError(
            "the ML dependencies are not installed; run: uv sync --extra ml"
        ) from None
    return huggingface_hub


def cached_snapshot(pin: RepoPin, settings: Settings) -> Path | None:
    """The local snapshot folder of ``pin`` if every file is already downloaded, else None."""
    configure_hf_cache(settings)
    hub = _hub()
    folder: Path | None = None
    for name in pin.files:
        found = hub.try_to_load_from_cache(pin.repo, name, revision=pin.revision)
        if not isinstance(found, str):
            return None
        folder = Path(found).parent
    return folder


def is_downloaded(spec: ModelSpec, settings: Settings) -> bool | None:
    """Whether all of the model's files are in the local cache; None if huggingface_hub is
    not installed."""
    try:
        return all(cached_snapshot(pin, settings) is not None for pin in spec.pins)
    except MLDependencyError:
        return None


# -- download progress -------------------------------------------------------------------
#
# The hub reports no progress without a progress bar, so the size of the repository's ``blobs``
# folder is the measure: the hub writes ``<etag>.incomplete`` and renames it when it is done.


@dataclass
class _PinProgress:
    """What is needed to tell how far the download of one repository has got."""

    blobs: Path
    baseline: int  # bytes of the complete blobs there before this download began
    total: int | None  # bytes still to fetch when it began; None when the hub did not say


_downloads: dict[str, list[_PinProgress]] = {}  # model key -> its repositories being fetched
_downloads_lock = threading.Lock()


def _blobs_size(blobs: Path) -> tuple[int, int]:
    """Bytes of the complete and of the ``.incomplete`` files in ``blobs``; (0, 0) when the
    folder is missing, and it never raises. ``os.stat`` per file, because on Windows a directory
    listing can lag behind a file that is being written."""
    complete = incomplete = 0
    try:
        with os.scandir(blobs) as entries:
            for entry in entries:
                try:
                    size = os.stat(entry.path).st_size
                except OSError:  # renamed or removed between the listing and the stat
                    continue
                if entry.name.endswith(".incomplete"):
                    incomplete += size
                else:
                    complete += size
    except OSError:
        return 0, 0
    return complete, incomplete


def download_progress(key: str) -> dict[str, int | None] | None:
    """``{"done_bytes", "total_bytes"}`` of the model ``key`` while :func:`ensure_downloaded` is
    fetching it, else None. ``total_bytes`` is None while it is not known (the sizes are still
    being asked for, or the hub did not say). Walks the blobs folders when called, so call it
    only when the numbers are shown."""
    with _downloads_lock:
        pins = _downloads.get(key)
        if pins is None:
            return None
        pins = list(pins)
    done = 0
    total: int | None = 0 if pins else None
    for pin in pins:
        complete, incomplete = _blobs_size(pin.blobs)
        # a partial file the hub resumes counts as done, so the bar does not stall short of full
        fetched = max(complete - pin.baseline, 0) + incomplete
        if pin.total is None or total is None:
            total = None
            done += fetched
        else:
            total += pin.total
            done += min(fetched, pin.total)
    return {"done_bytes": done, "total_bytes": total}


def _start_progress(hub, pin: RepoPin) -> _PinProgress:  # noqa: ANN001
    """The progress record of ``pin``: the files missing locally are asked of the hub (any
    failure leaves the total unknown; the download itself reports its own errors)."""
    folder = hub.file_download.repo_folder_name(repo_id=pin.repo, repo_type="model")
    blobs = Path(hub.constants.HF_HUB_CACHE) / folder / "blobs"
    try:
        missing = [
            name
            for name in pin.files
            if not isinstance(
                hub.try_to_load_from_cache(pin.repo, name, revision=pin.revision), str
            )
        ]
        infos = hub.HfApi().get_paths_info(pin.repo, missing, revision=pin.revision)
        sizes = {info.path: info.size for info in infos}
        total: int | None = sum(int(sizes[name]) for name in missing)
    except Exception:  # offline, auth, an unexpected answer: show no total, download anyway
        total = None
    return _PinProgress(blobs, _blobs_size(blobs)[0], total)


def ensure_downloaded(spec: ModelSpec, settings: Settings) -> dict[str, Path]:
    """Download (if needed) every pinned repository of ``spec``; returns ``{repo: folder}``.

    Only the files listed in the registry are fetched, always at the pinned commit. While files
    are being fetched, :func:`download_progress` answers for ``spec.key``.
    """
    configure_hf_cache(settings)
    hub = _hub()
    folders: dict[str, Path] = {}
    missing: list[RepoPin] = []
    for pin in spec.pins:
        folder = cached_snapshot(pin, settings)
        if folder is None:
            missing.append(pin)
        else:
            folders[pin.repo] = folder
    if not missing:
        return folders
    progress: list[_PinProgress] = []
    with _downloads_lock:
        _downloads[spec.key] = progress
    try:
        records = [_start_progress(hub, pin) for pin in missing]
        with _downloads_lock:
            progress.extend(records)
        for pin in missing:
            try:
                # One file at a time: the hub marks a folder as symlink-capable before it tests
                # it, so on Windows without symlink rights a parallel worker can try a real
                # symlink meanwhile and fail with WinError 1314. The time is in one big file.
                folders[pin.repo] = Path(
                    hub.snapshot_download(
                        pin.repo,
                        revision=pin.revision,
                        allow_patterns=list(pin.files),
                        max_workers=1,
                    )
                )
            except Exception as exc:  # network, auth, disk: all become a readable message
                raise ModelLoadError(
                    f"could not download {pin.repo}@{pin.revision[:7]} ({type(exc).__name__}): "
                    f"{str(exc)[:200]}"
                ) from None
    finally:
        with _downloads_lock:
            if _downloads.get(spec.key) is progress:
                del _downloads[spec.key]
    return {pin.repo: folders[pin.repo] for pin in spec.pins}
