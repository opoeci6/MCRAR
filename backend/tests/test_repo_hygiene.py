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
    "models/heads/x.pt",
    "backend/.venv/x",
    "frontend/node_modules/x",
]

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or not (REPO / ".git").exists(),
    reason="needs git and a git checkout",
)


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize("path", MUST_BE_IGNORED)
def test_path_is_git_ignored(path: str) -> None:
    # --no-index: judge the ignore rules even if a matching file were already tracked.
    result = _git("check-ignore", "-q", "--no-index", path)
    assert result.returncode == 0, f"{path} is not git-ignored"


def test_no_secret_files_are_tracked() -> None:
    tracked = _git("ls-files").stdout.splitlines()
    leaked = [p for p in tracked if p.startswith(".secrets/") or p == "config/settings.toml"]
    assert leaked == []
