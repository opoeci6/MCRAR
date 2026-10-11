"""dev-env.ps1 and dev-env.sh must export the same set of environment variables."""

import re
from pathlib import Path

from mcrar.cli import PROJECT_LOCAL_PATH_VARS

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def ps1_vars() -> set[str]:
    text = (SCRIPTS / "dev-env.ps1").read_text(encoding="utf-8")
    return set(re.findall(r"^\$env:([A-Za-z0-9_]+)\s*=", text, flags=re.MULTILINE))


def sh_vars() -> set[str]:
    text = (SCRIPTS / "dev-env.sh").read_text(encoding="utf-8")
    return set(re.findall(r"^export ([A-Za-z0-9_]+)=", text, flags=re.MULTILINE))


def test_same_variable_names() -> None:
    assert ps1_vars(), "no variables parsed from dev-env.ps1"
    assert ps1_vars() == sh_vars()


def test_required_variables_present() -> None:
    required = {
        "MCRAR_HOME",
        "UV_INSTALL_DIR",
        "UV_NO_MODIFY_PATH",
        "UV_PYTHON_INSTALL_DIR",
        "UV_PYTHON_PREFERENCE",
        "UV_PYTHON_BIN_DIR",
        "UV_PYTHON_INSTALL_REGISTRY",
        "UV_CACHE_DIR",
        "UV_TOOL_DIR",
        "UV_TOOL_BIN_DIR",
        "npm_config_cache",
        "npm_config_prefix",
        "npm_config_update_notifier",
        "HF_HOME",
        "TORCH_HOME",
        "NUMBA_CACHE_DIR",
        "MPLCONFIGDIR",
        "XDG_CACHE_HOME",
        "PYTHONNOUSERSITE",
    }
    assert required <= ps1_vars()


def test_doctor_checks_only_variables_the_scripts_set() -> None:
    assert set(PROJECT_LOCAL_PATH_VARS) <= ps1_vars()
