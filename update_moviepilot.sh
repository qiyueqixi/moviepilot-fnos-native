#!/bin/bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$root"
command -v gh >/dev/null || { echo 'Install GitHub CLI and run gh auth login first.' >&2; exit 1; }
args=()
if [ -n "${MOVIEPILOT_VERSION:-}" ] && [ "$MOVIEPILOT_VERSION" != latest ]; then
    args+=(--field "version=$MOVIEPILOT_VERSION")
fi
args+=(--field "force=${FORCE_BUILD:-false}")
gh workflow run upstream-fpk.yml "${args[@]}"
echo 'FPK build requested. Check GitHub Actions; successful builds are attached to a Release draft.'
