"""The Windows portable launcher (packaging/windows/MCRAR.cmd) and its readme.

cmd.exe is picky, so these tests pin the properties that matter: plain ASCII, CRLF endings, every
path derived from the launcher's own folder, no delayed expansion, nothing written outside the
folder, and the exact Python command line.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LAUNCHER = REPO / "packaging" / "windows" / "MCRAR.cmd"
README = REPO / "packaging" / "windows" / "README.txt"
DEV_ENV = REPO / "scripts" / "dev-env.ps1"

# The variables from scripts/dev-env.ps1 that matter at run time (model and library caches),
# plus the two Hugging Face hub settings the app folder needs. The uv, npm and node variables of
# the dev toolchain are not part of the app.
RUNTIME_CACHE_VARS = {
    "HF_HOME": r"\.cache\huggingface",
    "TORCH_HOME": r"\.cache\torch",
    "PYTORCH_KERNEL_CACHE_PATH": r"\.cache\torch\kernels",
    "TORCHINDUCTOR_CACHE_DIR": r"\.cache\torchinductor",
    "NUMBA_CACHE_DIR": r"\.cache\numba",
    "MPLCONFIGDIR": r"\.cache\matplotlib",
    "XDG_CACHE_HOME": r"\.cache",
    "HF_HUB_CACHE": r"\.cache\huggingface\hub",
}
DEV_ONLY_CACHE_VARS = {"UV_CACHE_DIR", "npm_config_cache"}


def launcher_bytes() -> bytes:
    return LAUNCHER.read_bytes()


def launcher_text() -> str:
    return launcher_bytes().decode("ascii")


def launcher_sets() -> dict[str, str]:
    found: dict[str, str] = {}
    for line in launcher_text().splitlines():
        match = re.fullmatch(r'set "([A-Za-z0-9_]+)=(.*)"', line.strip())
        if match:
            found[match.group(1)] = match.group(2)
    return found


def test_launcher_is_ascii_with_crlf_endings() -> None:
    raw = launcher_bytes()
    raw.decode("ascii")  # raises on any non-ASCII byte
    assert raw.count(b"\n") > 10
    assert raw.count(b"\r\n") == raw.count(b"\n"), "every line ending must be CRLF"
    assert b"\r" not in raw.replace(b"\r\n", b"")


def test_launcher_starts_quietly_with_a_local_scope() -> None:
    lines = [line.strip().lower() for line in launcher_text().splitlines()]
    assert lines[0] == "@echo off"
    assert "setlocal" in lines  # plain setlocal: delayed expansion would break paths with "!"


def test_launcher_derives_the_app_folder_from_its_own_location() -> None:
    sets = launcher_sets()
    assert sets["APP"] == "%~dp0"
    assert sets["MCRAR_HOME"] == "%APP%"
    assert 'if "%APP:~-1%"=="\\" set "APP=%APP:~0,-1%"' in launcher_text()


def test_launcher_sets_every_runtime_cache_variable_inside_the_app_folder() -> None:
    sets = launcher_sets()
    for name, suffix in RUNTIME_CACHE_VARS.items():
        assert sets.get(name) == "%APP%" + suffix, f"{name} must be set to %APP%{suffix}"
    assert sets["PYTHONNOUSERSITE"] == "1"
    assert sets["HF_HUB_DISABLE_SYMLINKS_WARNING"] == "1"


def test_launcher_cache_variables_match_the_dev_environment() -> None:
    text = DEV_ENV.read_text(encoding="utf-8")
    dev_cache_vars = {
        name
        for name, value in re.findall(r"^\$env:([A-Za-z0-9_]+)\s*=\s*(.+)$", text, re.MULTILINE)
        if ".cache" in value
    } - DEV_ONLY_CACHE_VARS
    # A cache variable added to dev-env.ps1 must be added to the launcher too (or listed above).
    assert dev_cache_vars == set(RUNTIME_CACHE_VARS) - {"HF_HUB_CACHE"}


def test_launcher_runs_the_bundled_python_isolated() -> None:
    assert '"%APP%\\python\\python.exe" -I -m mcrar serve --open --warm %*' in launcher_text(), (
        "the launcher must run the bundled python with -I and pass the user's options on"
    )


def test_launcher_keeps_the_error_visible_and_never_touches_system_state() -> None:
    text = launcher_text().lower()
    assert "pause" in text
    for forbidden in ("setx", "reg add", "reg.exe", "enabledelayedexpansion", "!errorlevel!"):
        assert forbidden not in text
    assert not re.search(r"^\s*set \w+=", launcher_text(), re.MULTILINE), "quote every set"


def test_every_path_in_the_launcher_is_quoted() -> None:
    for line in launcher_text().splitlines():
        if "%APP%" in line and not line.lstrip().startswith("rem"):
            for token in re.findall(r"\S*%APP%\S*", line):
                assert token.startswith('"') or token.startswith("set"), line
            assert line.count('"') % 2 == 0, f"unbalanced quotes: {line}"


def test_readme_is_plain_text_and_points_to_the_notice() -> None:
    raw = README.read_bytes()
    raw.decode("ascii")
    assert b"\r\n" in raw
    text = raw.decode("ascii")
    assert "NOTICE.md" in text
    assert "MCRAR.cmd" in text
    assert "non-commercial" in text
    assert len(text.splitlines()) <= 70
