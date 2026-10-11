#!/usr/bin/env bash
# Run ONE command with the MCRAR project-local dev env loaded (for shells that keep no state).
# Usage: scripts/with-env.sh <cmd> [args...]
set -e
if [ "$#" -eq 0 ]; then
    echo "usage: scripts/with-env.sh <cmd> [args...]" >&2
    exit 2
fi
_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCRAR_QUIET=1 source "$_here/dev-env.sh"
exec "$@"
