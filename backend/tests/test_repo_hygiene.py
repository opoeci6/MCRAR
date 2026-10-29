"""Secrets, local settings, tools, caches and data must never be committed to git."""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

MUST_BE_IGNORED = [
    ".secrets/secrets.toml",
    "config/settings.toml",
    ".tools/uv/uv.exe",
    ".cache/huggingface/x",
    "data/catalog.db",
    "models/checkpoints/x.pt",
    "models/scratch.bin",
    "backend/.venv/x",
    "frontend/node_modules/x",
    ".claude/CLAUDE.md",
]

# The trained tag heads and their registry are committed (M3b): small, licence recorded.
MUST_BE_TRACKABLE = ["models/heads/genre.npz", "models/registry.json"]

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or not (REPO / ".git").exists(),
    reason="needs git and a git checkout",
)


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False
    )


def _is_ignored(path: str) -> bool:
    # --no-index: judge the ignore rules even if a matching file were already tracked. -v shows
    # the deciding rule: some git versions report a matching negation ("!pattern") as a match.
    result = _git("check-ignore", "-v", "--no-index", path)
    if result.returncode != 0:
        return False
    rule = result.stdout.split("\t", 1)[0].split(":", 2)[-1]
    return not rule.startswith("!")


@pytest.mark.parametrize("path", MUST_BE_IGNORED)
def test_path_is_git_ignored(path: str) -> None:
    assert _is_ignored(path), f"{path} is not git-ignored"


@pytest.mark.parametrize("path", MUST_BE_TRACKABLE)
def test_path_is_not_git_ignored(path: str) -> None:
    assert not _is_ignored(path), f"{path} is git-ignored but should be committable"


def test_no_secret_files_are_tracked() -> None:
    tracked = _git("ls-files").stdout.splitlines()
    leaked = [p for p in tracked if p.startswith(".secrets/") or p == "config/settings.toml"]
    assert leaked == []
