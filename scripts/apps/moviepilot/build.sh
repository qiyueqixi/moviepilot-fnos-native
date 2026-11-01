#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
VERSION="${VERSION:-latest}"
if [ "$VERSION" = latest ]; then
  VERSION="$("$SCRIPT_DIR/get-latest-version.sh" | sed -n 's/^VERSION=//p')"
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/source" "$work/app" "$work/fnos"
if [ -n "${MOVIEPILOT_SOURCE_DIR:-}" ]; then
  cp -a "$MOVIEPILOT_SOURCE_DIR/." "$work/source/"
else
  curl -fsSL --retry 3 "https://github.com/jxxghp/MoviePilot/archive/refs/tags/v${VERSION}.tar.gz" -o "$work/moviepilot.tgz"
  tar xzf "$work/moviepilot.tgz" --strip-components=1 -C "$work/source"
fi
frontend_version="$(python3 - "$work/source" "$VERSION" "$ROOT" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[3]) / 'scripts'))
from upstream import source_versions
backend, frontend = source_versions(Path(sys.argv[1]))
if backend != sys.argv[2]:
    raise SystemExit(f'Source version mismatch: {backend} != {sys.argv[2]}')
print(frontend)
PY
)"
python3 "$SCRIPT_DIR/patch-native.py" "$work/source"
cp -a "$work/source/." "$work/app/"
rm -rf "$work/app/docker"
mkdir -p "$work/app/public"
frontend_url="$(curl -fsSL --retry 3 "https://api.github.com/repos/jxxghp/MoviePilot-Frontend/releases/tags/v${frontend_version}" | jq -r '.assets[] | select(.name == "dist.zip") | .browser_download_url')"
[ -n "$frontend_url" ] && [ "$frontend_url" != null ] || { echo "Missing frontend release v${frontend_version}" >&2; exit 1; }
curl -fsSL "$frontend_url" -o "$work/frontend.zip"
python3 - "$work/frontend.zip" "$work/app/public" <<'PY'
import sys
import zipfile
from pathlib import Path

archive, target = sys.argv[1:]
with zipfile.ZipFile(archive) as zf:
    zf.extractall(Path(target).parent)
source = Path(target).parent / "dist"
Path(target).mkdir(parents=True, exist_ok=True)
for item in source.iterdir():
    item.rename(Path(target) / item.name)
source.rmdir()
PY
python3 "$SCRIPT_DIR/patch-frontend.py" "$work/app/public/index.html"
cp "$ROOT/fnos/resources/service.js" "$work/app/public/service.js"
cp "$ROOT/fnos/package.json" "$work/app/public/package.json"
cp "$ROOT/fnos/resources/no-auth.js" "$work/app/public/no-auth.js"
cp -a "$ROOT/fnos/ui" "$work/app/ui"
python3 - "$work/app/public/index.html" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = text.replace("</head>", '<script src="/no-auth.js"></script></head>', 1)
path.write_text(text, encoding="utf-8")
PY
npm install --prefix "$work/app/public" --omit=dev --no-fund --no-audit
node_url="https://nodejs.org/dist/v20.12.1/node-v20.12.1-linux-x64.tar.xz"
curl -fsSL "$node_url" -o "$work/node.tar.xz"
mkdir -p "$work/app/public/node"
tar xJf "$work/node.tar.xz" --strip-components=1 -C "$work/app/public/node"
printf '%s\n' "$VERSION" > "$work/app/VERSION"
tar czf "$ROOT/app.tgz" -C "$work/app" .
echo "Built native app.tgz for MoviePilot ${VERSION}"
