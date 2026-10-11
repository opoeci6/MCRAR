# shellcheck shell=bash
# Loads the MCRAR project-local dev environment into the CURRENT shell (Git Bash).
# Usage:  source scripts/dev-env.sh        (set MCRAR_QUIET=1 to silence the summary)
# Sets only process-level environment variables and prepends .tools/* to PATH for this
# session. Never writes to the registry or any profile.
# Keep the variable list in sync with scripts/dev-env.ps1 (a backend test enforces it).

_mcrar_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# POSIX form for PATH; Windows form (D:/...) for values that native Windows programs read.
_mcrar_posix="$(cd "$_mcrar_dir/.." && pwd)"
_mcrar_win="$(cd "$_mcrar_dir/.." && pwd -W 2>/dev/null || pwd)"

export MCRAR_HOME="$_mcrar_win"

# uv: binary, managed Pythons, caches, tools. Nothing is registered system-wide.
export UV_INSTALL_DIR="$_mcrar_win/.tools/uv"
export UV_NO_MODIFY_PATH=1
export UV_PYTHON_INSTALL_DIR="$_mcrar_win/.tools/python"
export UV_PYTHON_PREFERENCE=only-managed
export UV_PYTHON_BIN_DIR="$_mcrar_win/.tools/python-bin"
export UV_PYTHON_INSTALL_REGISTRY=0
export UV_PYTHON_INSTALL_BIN=0
export UV_CACHE_DIR="$_mcrar_win/.cache/uv"
export UV_TOOL_DIR="$_mcrar_win/.tools/uv-tools"
export UV_TOOL_BIN_DIR="$_mcrar_win/.tools/tool-bin"

# npm: cache and (accidental) global prefix stay local.
export npm_config_cache="$_mcrar_win/.cache/npm"
export npm_config_prefix="$_mcrar_win/.tools/npm-global"
export npm_config_update_notifier=false

# ML and tooling caches.
export HF_HOME="$_mcrar_win/.cache/huggingface"
export TORCH_HOME="$_mcrar_win/.cache/torch"
export NUMBA_CACHE_DIR="$_mcrar_win/.cache/numba"
export MPLCONFIGDIR="$_mcrar_win/.cache/matplotlib"
export XDG_CACHE_HOME="$_mcrar_win/.cache"

# Never read the per-user site-packages.
export PYTHONNOUSERSITE=1

# Prepend project tools to PATH (POSIX form; session only). Drop earlier copies first.
_mcrar_new_path=""
_mcrar_old_ifs="$IFS"
IFS=":"
for _mcrar_p in $PATH; do
    case "$_mcrar_p" in
        "$_mcrar_posix/.tools/uv" | "$_mcrar_posix/.tools/node" | "$_mcrar_posix/.tools/python-bin") ;;
        *) _mcrar_new_path="${_mcrar_new_path:+$_mcrar_new_path:}$_mcrar_p" ;;
    esac
done
IFS="$_mcrar_old_ifs"
export PATH="$_mcrar_posix/.tools/uv:$_mcrar_posix/.tools/node:$_mcrar_posix/.tools/python-bin:$_mcrar_new_path"

if [ -z "${MCRAR_QUIET:-}" ]; then
    echo "MCRAR dev env loaded (session only): home=$_mcrar_win; uv, node and python are project-local (.tools/)."
fi

unset _mcrar_dir _mcrar_posix _mcrar_win _mcrar_new_path _mcrar_old_ifs _mcrar_p
