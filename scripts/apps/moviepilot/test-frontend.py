"""Check that repaired inline declarations execute, beyond a syntax check."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load_module("builder", ROOT / "build-fpk.py")
frontend = load_module("frontend", Path(__file__).with_name("patch-frontend.py"))


class FrontendTests(unittest.TestCase):
    def test_swallowed_declaration_executes_and_is_idempotent(self):
        source = (
            "const themePreference = 'dark';\n"
            "const getLocalStorageValue = () => '#123456';\n"
            "// damaged comment      const storedLoaderColor = themePreference === 'auto' ? null : getLocalStorageValue('background');\n"
            "console.log(storedLoaderColor);\n"
        ).encode()
        # This regression is syntactically valid even before the repair.
        for mode in ("builder", "standalone"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                if mode == "builder":
                    repaired = builder.patch_frontend_index(source)
                    self.assertEqual(builder.patch_frontend_index(repaired), repaired)
                else:
                    target = Path(directory) / "index.html"
                    target.write_bytes(source)
                    self.assertTrue(frontend.patch_index(target))
                    repaired = target.read_bytes()
                    self.assertFalse(frontend.patch_index(target))
                    self.assertEqual(target.read_bytes(), repaired)
                result = subprocess.run(
                    ["node", "-e", repaired.decode()], capture_output=True, check=True,
                )
                self.assertEqual(result.stdout.strip(), b"#123456")


if __name__ == "__main__":
    unittest.main()
