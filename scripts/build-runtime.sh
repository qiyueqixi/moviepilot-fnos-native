#!/bin/bash
# Run in the target architecture's Debian Bookworm / Python 3.11 build container.
set -euo pipefail
source_dir="${1:?source directory required}"
platform="${2:?x86 or arm required}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
expected_machine=x86_64
runtime_name=venv-runtime.tgz
[ "$platform" = x86 ] || { [ "$platform" = arm ] || exit 1; expected_machine=aarch64; runtime_name=venv-runtime-arm.tgz; }
[ "$(uname -m)" = "$expected_machine" ] || { echo 'Runtime CPU architecture mismatch' >&2; exit 1; }
python3 -c 'import sys; assert sys.version_info[:2] == (3, 11), "This native series requires Python 3.11"'
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
python3 -m venv "$work/venv"
"$work/venv/bin/python" -m pip install --upgrade pip
"$work/venv/bin/python" -m pip install -r "$source_dir/requirements.txt"
"$work/venv/bin/python" -m pip check
# Compile under the actual target Python, before any package is published.
"$work/venv/bin/python" -m compileall -q "$source_dir/app"
"$work/venv/bin/python" -m pip freeze > "$work/venv/native-requirements.txt"
python3 - "$work/venv" "$source_dir" "$platform" <<'PY'
import hashlib, json, platform, sys
from pathlib import Path
venv, source = map(Path, sys.argv[1:3])
files = sorted(source.glob('requirements*'))
digest = hashlib.sha256()
for path in files:
    if path.is_file():
        digest.update(path.name.encode()); digest.update(path.read_bytes())
metadata = {'python': platform.python_version(), 'architecture': sys.argv[3],
            'requirements_sha256': digest.hexdigest()}
(venv / 'native-runtime.json').write_text(json.dumps(metadata, indent=2) + '\n')
# pip-generated entry points otherwise retain the temporary build directory.
launcher = '#!/bin/sh\n\'\'\'exec\' "$(dirname "$0")/python" "$0" "$@"\n\' \'\'\'\n'
for path in (venv / 'bin').iterdir():
    if path.is_file() and not path.is_symlink():
        data = path.read_bytes()
        first, separator, rest = data.partition(b'\n')
        if first.startswith(b'#!') and str(venv).encode() in first:
            path.write_bytes(launcher.encode() + rest)
# fnOS supplies /usr/bin/python3. Do not ship the build container's interpreter.
for name in ['python', 'python3', 'python3.11']:
    path = venv / 'bin' / name
    path.unlink(missing_ok=True)
    path.symlink_to('/usr/bin/python3' if name == 'python3' else 'python3')
(venv / 'pyvenv.cfg').write_text('home = /usr/bin\ninclude-system-site-packages = false\nversion = 3.11\nexecutable = /usr/bin/python3\n')
PY
mkdir -p "$root/fnos/runtime"
tar --owner=0 --group=0 -czf "$root/fnos/runtime/$runtime_name" -C "$work" venv
echo "Built $runtime_name"
