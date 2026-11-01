#!/bin/bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
version="$(python3 - "$root" "${1:-}" <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'scripts'))
from upstream import download, select_release, version_tuple
config = json.loads((Path(sys.argv[1]) / 'upstream.json').read_text())
version = sys.argv[2].removeprefix('v')
if not version:
    releases = json.loads(download(f"https://api.github.com/repos/{config['repository']}/releases?per_page=100"))
    version = select_release(releases, config['supported_major'])['tag_name'].removeprefix('v')
if version_tuple(version)[0] != config['supported_major']:
    raise SystemExit('This major version requires a separate native migration')
print(version)
PY
)"
[ -n "$version" ] && [ "$version" != null ] || { echo "Unable to resolve MoviePilot version" >&2; exit 1; }
echo "VERSION=$version"
[ -z "${GITHUB_OUTPUT:-}" ] || echo "version=$version" >> "$GITHUB_OUTPUT"
