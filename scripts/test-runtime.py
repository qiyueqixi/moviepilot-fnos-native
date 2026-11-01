"""Exercise native runtime replacement on Linux without starting MoviePilot."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

HELPER = Path(__file__).resolve().parents[1] / 'fnos/cmd/runtime'


@unittest.skipIf(os.name == 'nt', 'Runtime installation runs on Linux; exercised by CI')
class RuntimeTests(unittest.TestCase):
    def setup_runtime(self, base, corrupt=False):
        root = Path(base)
        app, var = root / 'app', root / 'var'
        (app / 'runtime').mkdir(parents=True)
        (var / 'venv/bin').mkdir(parents=True)
        (var / 'venv/pyvenv.cfg').write_text('old')
        (var / 'venv/bin/python').write_text('#!/bin/sh\nexit 0\n')
        (var / 'venv/bin/python').chmod(0o755)
        archive = app / 'runtime/venv.tgz'
        if corrupt:
            archive.write_bytes(b'corrupt archive')
        else:
            with tarfile.open(archive, 'w:gz') as target:
                for name, data, mode in [('venv/pyvenv.cfg', b'new', 0o644), ('venv/bin/python', b'#!/bin/sh\nexit 0\n', 0o755)]:
                    member = tarfile.TarInfo(name)
                    member.size, member.mode = len(data), mode
                    target.addfile(member, io.BytesIO(data))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        (app / 'runtime/expected.json').write_text(json.dumps({'sha256': digest}))
        env = dict(os.environ, TRIM_APPDEST=str(app), TRIM_PKGVAR=str(var))
        return app, var, archive, digest, env

    def run_helper(self, command, env):
        return subprocess.run(['bash', '-c', 'source "$1"; ' + command, '--', str(HELPER)], env=env, capture_output=True, text=True)

    def test_upgrade_replaces_stale_dependencies_and_second_start_keeps_current_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            app, var, archive, digest, env = self.setup_runtime(temp)
            self.assertNotEqual(self.run_helper('runtime_is_current', env).returncode, 0)
            result = self.run_helper('runtime_install_archive "$TRIM_APPDEST/runtime/venv.tgz"', env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((var / 'venv/pyvenv.cfg').read_text(), 'new')
            self.assertEqual((var / '.runtime.sha256').read_text().strip(), digest)
            (var / 'venv/plugin-installed').write_text('keep')
            self.assertEqual(self.run_helper('runtime_is_current', env).returncode, 0)
            self.assertEqual(self.run_helper('runtime_install_archive "$TRIM_APPDEST/runtime/venv.tgz"', env).returncode, 0)
            self.assertTrue((var / 'venv/plugin-installed').exists())

    def test_wrong_archive_preserves_installed_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            app, var, archive, digest, env = self.setup_runtime(temp)
            archive.write_bytes(b'wrong release')
            result = self.run_helper('runtime_install_archive "$TRIM_APPDEST/runtime/venv.tgz"', env)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((var / 'venv/pyvenv.cfg').read_text(), 'old')
            self.assertFalse((var / '.runtime.sha256').exists())

    def test_extraction_failure_preserves_installed_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            app, var, archive, digest, env = self.setup_runtime(temp, corrupt=True)
            self.assertNotEqual(self.run_helper('runtime_install_archive "$TRIM_APPDEST/runtime/venv.tgz"', env).returncode, 0)
            self.assertEqual((var / 'venv/pyvenv.cfg').read_text(), 'old')


if __name__ == '__main__':
    unittest.main()
