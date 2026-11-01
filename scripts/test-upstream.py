import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('upstream', Path(__file__).with_name('upstream.py'))
upstream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upstream)


class UpdateTests(unittest.TestCase):
    def test_selects_highest_supported_stable_version(self):
        releases = [dict(tag_name=t, prerelease=p, draft=d) for t, p, d in [
            ('v2.9.9', False, False), ('v3.2.3', False, False), ('v2.15.6', False, False),
            ('v2.16.0', True, False), ('v2.17.0', False, True), ('v2.18.0-rc1', False, False)]]
        config = {'supported_major': 2, 'native_revision': 39, 'python': '3.11'}
        plan = upstream.resolve(config, None, releases)
        self.assertEqual(plan['version'], '2.15.6')
        self.assertEqual(plan['latest_upstream'], 'v3.2.3')
        self.assertEqual(plan['release_tag'], 'v2.15.6-fnos.39')
        with self.assertRaises(ValueError):
            upstream.resolve(config, 'v3.2.3', releases)

    def test_frontend_version_is_read_from_backend_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / 'version.py').write_text("APP_VERSION='v2.15.6'\nFRONTEND_VERSION='v2.15.5'\n")
            self.assertEqual(upstream.source_versions(directory), ('2.15.6', '2.15.5'))

    def test_incomplete_release_is_retried(self):
        assets = [{'name': f'moviepilot_2.15.6-39_{arch}{suffix}.fpk', 'state': 'uploaded'}
                  for arch in ['x86', 'arm'] for suffix in ['', '_installer']]
        self.assertFalse(upstream.release_assets_valid({'assets': assets}, '2.15.6', 39))
        assets.append({'name': 'SHA256SUMS.txt', 'state': 'uploaded'})
        assets.extend({'name': f'moviepilot-runtime-{arch}-python311.tgz', 'state': 'uploaded'} for arch in ['x86', 'arm'])
        self.assertTrue(upstream.release_assets_valid({'assets': assets}, '2.15.6', 39))
        assets[0]['state'] = 'starter'
        self.assertFalse(upstream.release_assets_valid({'assets': assets}, '2.15.6', 39))

    def test_bootstrap_checksum_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'bootstrap.fpk'
            path.write_bytes(b'changed download')
            checksums = Path(temp) / 'SHA256SUMS.txt'
            checksums.write_text('0' * 64 + '  bootstrap.fpk\n')
            with self.assertRaises(ValueError):
                upstream.verify_checksum(path, checksums)

    def test_source_archive_cannot_escape_destination(self):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w:gz') as archive:
            member = tarfile.TarInfo('root/../../outside')
            member.size = 1
            archive.addfile(member, io.BytesIO(b'x'))
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ValueError):
            upstream.safe_unpack_source(data.getvalue(), Path(temp))


if __name__ == '__main__':
    unittest.main()
