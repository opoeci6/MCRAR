"""Download progress of ``ensure_downloaded``: the size of the cache's blobs folder against the
sizes the hub reports, with a fake hub (no network)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mcrar.config import get_settings
from mcrar.ml import ModelLoadError, get_spec
from mcrar.ml import registry as reg

file_download = pytest.importorskip("huggingface_hub.file_download")


class FakeHub:
    """Stands in for ``huggingface_hub``: a cache folder, hub-side file sizes and a download
    that the test drives with ``on_download(pin_repo, blobs_folder)``."""

    def __init__(self, cache: Path, sizes: dict[str, dict[str, int]]) -> None:
        self.constants = SimpleNamespace(HF_HUB_CACHE=str(cache))
        self.file_download = file_download
        self.cache = cache
        self.sizes = sizes  # repo -> file -> bytes
        self.cached: set[tuple[str, str]] = set()  # (repo, file) already in the cache
        self.size_error: Exception | None = None
        self.on_download: Any = lambda repo, blobs: None
        self.asked: list[tuple[str, list[str]]] = []
        self.downloads: list[str] = []
        self.workers: list[int] = []

    def blobs(self, repo: str) -> Path:
        name = file_download.repo_folder_name(repo_id=repo, repo_type="model")
        folder = self.cache / name / "blobs"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def try_to_load_from_cache(self, repo: str, name: str, revision: str | None = None) -> Any:
        return (
            f"{self.cache}/{repo}/snapshots/{revision}/{name}"
            if (repo, name) in self.cached
            else None
        )

    def HfApi(self) -> Any:  # noqa: N802 - the name of the real class
        return SimpleNamespace(get_paths_info=self.get_paths_info)

    def get_paths_info(self, repo: str, paths: list[str], *, revision: str | None = None) -> list:
        self.asked.append((repo, list(paths)))
        if self.size_error is not None:
            raise self.size_error
        return [SimpleNamespace(path=p, size=self.sizes[repo][p]) for p in paths]

    def snapshot_download(
        self, repo: str, *, revision: str, allow_patterns: list[str], max_workers: int = 8
    ) -> str:
        self.downloads.append(repo)
        self.workers.append(max_workers)
        self.on_download(repo, self.blobs(repo))
        return str(self.cache / repo / "snapshots" / revision)


def clap_sizes() -> dict[str, dict[str, int]]:
    spec = get_spec("clap")
    files = {name: 10 for name in spec.weights.files}
    files["pytorch_model.bin"] = 1000
    return {spec.repo: files}


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeHub:
    fake = FakeHub(tmp_path / "hf-cache", clap_sizes())
    monkeypatch.setattr(reg, "_hub", lambda: fake)
    return fake


def test_progress_follows_the_incomplete_file_and_ends_with_the_download(hub: FakeHub) -> None:
    spec = get_spec("clap")
    seen: list[Any] = []

    def download(repo: str, blobs: Path) -> None:
        seen.append(reg.download_progress("clap"))  # nothing written yet
        partial = blobs / "etag1.incomplete"
        for size in (300, 700):
            partial.write_bytes(b"x" * size)
            seen.append(reg.download_progress("clap"))
        partial.rename(blobs / "etag1")  # the hub renames a finished file
        seen.append(reg.download_progress("clap"))
        (blobs / "etag2").write_bytes(b"y" * 70)  # the small files, 7 x 10 bytes
        seen.append(reg.download_progress("clap"))

    hub.on_download = download
    folders = reg.ensure_downloaded(spec, get_settings())
    assert hub.asked == [(spec.repo, list(spec.weights.files))]
    assert [s["done_bytes"] for s in seen] == [0, 300, 700, 700, 770]
    assert {s["total_bytes"] for s in seen} == {1070}
    assert list(folders) == [spec.repo]
    assert reg.download_progress("clap") is None


def test_the_bytes_that_were_in_the_cache_before_are_not_counted(hub: FakeHub) -> None:
    spec = get_spec("clap")
    (hub.blobs(spec.repo) / "older").write_bytes(b"z" * 5000)  # another revision's blob
    hub.cached = {(spec.repo, "config.json"), (spec.repo, "vocab.json")}
    seen: list[Any] = []

    def download(repo: str, blobs: Path) -> None:
        seen.append(reg.download_progress("clap"))
        (blobs / "new.incomplete").write_bytes(b"x" * 100)
        seen.append(reg.download_progress("clap"))
        (blobs / "new.incomplete").write_bytes(b"x" * 5000)  # more than the hub said: clamped
        seen.append(reg.download_progress("clap"))

    hub.on_download = download
    reg.ensure_downloaded(spec, get_settings())
    asked = hub.asked[0][1]
    assert "config.json" not in asked and "vocab.json" not in asked and len(asked) == 6
    assert seen == [
        {"done_bytes": 0, "total_bytes": 1050},
        {"done_bytes": 100, "total_bytes": 1050},
        {"done_bytes": 1050, "total_bytes": 1050},
    ]


def test_a_resumed_partial_file_counts_as_done(hub: FakeHub) -> None:
    spec = get_spec("clap")
    (hub.blobs(spec.repo) / "etag1.incomplete").write_bytes(b"x" * 400)
    seen: list[Any] = []
    hub.on_download = lambda repo, blobs: seen.append(reg.download_progress("clap"))
    reg.ensure_downloaded(spec, get_settings())
    assert seen == [{"done_bytes": 400, "total_bytes": 1070}]


def test_the_total_is_unknown_when_the_hub_cannot_say_but_the_download_goes_on(
    hub: FakeHub,
) -> None:
    spec = get_spec("clap")
    hub.size_error = ConnectionError("offline")
    seen: list[Any] = []

    def download(repo: str, blobs: Path) -> None:
        (blobs / "etag1.incomplete").write_bytes(b"x" * 250)
        seen.append(reg.download_progress("clap"))

    hub.on_download = download
    reg.ensure_downloaded(spec, get_settings())
    assert seen == [{"done_bytes": 250, "total_bytes": None}]
    assert reg.download_progress("clap") is None


def test_the_entry_goes_when_the_download_fails(hub: FakeHub) -> None:
    spec = get_spec("clap")
    seen: list[Any] = []

    def download(repo: str, blobs: Path) -> None:
        seen.append(reg.download_progress("clap"))
        raise OSError("disk full")

    hub.on_download = download
    with pytest.raises(ModelLoadError, match=r"could not download laion/larger_clap.*OSError"):
        reg.ensure_downloaded(spec, get_settings())
    assert seen and seen[0] is not None
    assert reg.download_progress("clap") is None


def test_a_model_that_is_cached_registers_nothing(hub: FakeHub) -> None:
    spec = get_spec("clap")
    hub.cached = {(spec.repo, name) for name in spec.weights.files}
    hub.on_download = lambda repo, blobs: pytest.fail("must not download")
    reg.ensure_downloaded(spec, get_settings())
    assert hub.asked == [] and hub.downloads == []
    assert reg.download_progress("clap") is None


def test_files_are_fetched_one_at_a_time(hub: FakeHub) -> None:
    # Parallel workers race the hub's symlink check: WinError 1314 without symlink rights.
    reg.ensure_downloaded(get_spec("muq-mulan"), get_settings())
    assert len(hub.workers) == 3 and set(hub.workers) == {1}


def test_every_repository_of_a_model_counts(hub: FakeHub) -> None:
    spec = get_spec("muq-mulan")
    hub.sizes = {pin.repo: {name: 100 for name in pin.files} for pin in spec.pins}
    seen: list[Any] = []

    def download(repo: str, blobs: Path) -> None:
        (blobs / "etag.incomplete").write_bytes(b"x" * 60)
        seen.append(reg.download_progress("muq-mulan"))
        (blobs / "etag.incomplete").rename(blobs / "etag")

    hub.on_download = download
    reg.ensure_downloaded(spec, get_settings())
    total = sum(100 * len(pin.files) for pin in spec.pins)
    assert [s["total_bytes"] for s in seen] == [total] * 3  # known before the first download
    # 60 in the first repository; then its finished 60 plus 60 in the second, and so on
    assert [s["done_bytes"] for s in seen] == [60, 120, 180]
    assert hub.downloads == [pin.repo for pin in spec.pins]


def test_progress_of_a_missing_blobs_folder_is_zero_and_never_raises(tmp_path: Path) -> None:
    assert reg._blobs_size(tmp_path / "nope" / "blobs") == (0, 0)
    (tmp_path / "blobs").mkdir()
    (tmp_path / "blobs" / "a").write_bytes(b"1234")
    (tmp_path / "blobs" / "b.incomplete").write_bytes(b"12")
    assert reg._blobs_size(tmp_path / "blobs") == (4, 2)


def test_unknown_keys_have_no_progress() -> None:
    assert reg.download_progress("clap") is None
    assert reg.download_progress("nope") is None
