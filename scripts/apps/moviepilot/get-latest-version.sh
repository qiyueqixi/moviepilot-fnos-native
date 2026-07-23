#!/bin/bash
set -euo pipefail
version="${1:-}"
if [ -z "$version" ]; then
  version=$(curl -fsSL https://api.github.com/repos/jxxghp/MoviePilot/releases/latest | jq -r .tag_name)
fi
version="${version#v}"
[ -n "$version" ] && [ "$version" != null ] || { echo "Unable to resolve MoviePilot version" >&2; exit 1; }
echo "VERSION=$version"
[ -z "${GITHUB_OUTPUT:-}" ] || echo "version=$version" >> "$GITHUB_OUTPUT"
