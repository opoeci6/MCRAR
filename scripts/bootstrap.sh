#!/usr/bin/env bash
# Thin Git Bash wrapper around scripts/bootstrap.ps1 (Windows only for now).
set -e
case "$(uname -s)" in
    MINGW* | MSYS* | CYGWIN*) ;;
    *)
        echo "bootstrap: this platform is not supported yet (Windows only for now)." >&2
        exit 1
        ;;
esac
_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$_here/bootstrap.ps1")" "$@"
