#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
WORK_DIR="${WORK_DIR:-$(mktemp -d)}"
APP_VERSION="${MOVIEPILOT_VERSION:-latest}"

if [ "$APP_VERSION" = latest ]; then
  APP_VERSION="$(curl -fsSL https://api.github.com/repos/jxxghp/MoviePilot/releases/latest | jq -r .tag_name | sed 's/^v//')"
fi
export VERSION="$APP_VERSION"
bash "$SCRIPT_DIR/scripts/apps/moviepilot/build.sh"
mkdir -p "$WORK_DIR"
cp "$REPO_ROOT/app.tgz" "$WORK_DIR/app.tgz"
