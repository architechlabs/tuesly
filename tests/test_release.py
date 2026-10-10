import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


class ReleaseTests(unittest.TestCase):
    def test_release_contains_only_new_integration_with_brands_and_notices(self):
        spec = importlib.util.spec_from_file_location("tuesly_package_release", ROOT / "tools" / "package_release.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with contextlib.redirect_stdout(io.StringIO()):
            module.main()
        version = json.loads((ROOT / "project.json").read_text(encoding="utf-8"))["version"]
        with ZipFile(ROOT / "dist" / f"tuesly-{version}.zip") as archive:
            paths = archive.namelist()
            self.assertTrue(all(path.startswith("custom_components/tuesly/") for path in paths))
            self.assertFalse(any("__pycache__" in path or path.endswith(".pyc") or "/.git/" in path
                                 or "secrets.yaml" in path for path in paths))
            manifest = json.loads(archive.read("custom_components/tuesly/manifest.json"))
            self.assertEqual(manifest["domain"], "tuesly")
            self.assertEqual(manifest["version"], version)
            self.assertEqual(len([path for path in paths if "/brand/" in path and path.endswith(".png")]), 8)
            self.assertIn("custom_components/tuesly/lib/tuesly_mesh/sig_mesh_device.py", paths)
            self.assertIn("custom_components/tuesly/LICENSE", paths)
            self.assertIn('custom_components/tuesly/docs/SITE_INSTALLATION.md',paths)
            self.assertIn('custom_components/tuesly/docs/OFFLINE_VALIDATION_0.2.7.md',paths)
            notice = archive.read("custom_components/tuesly/THIRD_PARTY_NOTICES.md").decode()
            self.assertIn("Copyright (c) 2024 11z4t", notice)


if __name__ == "__main__":
    unittest.main()
