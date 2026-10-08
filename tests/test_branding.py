"""Validate new namespaces, real HA brand assets and release boundaries."""
import ast
import json
from pathlib import Path
import unittest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "tuesly"


class BrandTests(unittest.TestCase):
    def test_manifest_is_tuesly_and_has_no_previous_owner_links(self):
        manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
        project = json.loads((ROOT / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["domain"], "tuesly")
        self.assertEqual(manifest["name"], "Tuesly")
        self.assertEqual(manifest["version"], project["version"])
        self.assertEqual(project["publisher"], "Architech Labs")
        self.assertNotIn("issue_tracker", manifest)
        self.assertNotIn("documentation", manifest)
        self.assertEqual(manifest["codeowners"], [])

    def test_all_local_imports_resolve_in_new_namespace(self):
        for path in COMPONENT.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module)
                elif isinstance(node, ast.Import):
                    names.extend(alias.name for alias in node.names)
                for name in names:
                    if name.startswith("custom_components.tuesly"):
                        relative = name.removeprefix("custom_components.tuesly").lstrip(".")
                        target = COMPONENT.joinpath(*relative.split(".")) if relative else COMPONENT
                    elif name.startswith("tuesly_mesh"):
                        relative = name.removeprefix("tuesly_mesh").lstrip(".")
                        target = COMPONENT / "lib" / "tuesly_mesh"
                        if relative:
                            target = target.joinpath(*relative.split("."))
                    else:
                        continue
                    self.assertTrue(target.with_suffix(".py").exists() or (target / "__init__.py").exists(),
                                    f"{path}: unresolved local import {name}")

    def test_no_legacy_names_in_runtime_source_or_ui_metadata(self):
        legacy = ["tuya_ble_mesh", "tuya-ble-mesh", "Tuya BLE Mesh", "github.com/11z4t", "@11z4t"]
        for path in COMPONENT.rglob("*"):
            if path.is_file() and path.suffix in (".py", ".json", ".yaml"):
                text = path.read_text(encoding="utf-8")
                for name in legacy:
                    self.assertNotIn(name, text, str(path))

    def test_json_and_english_setup_branding(self):
        for path in COMPONENT.rglob("*.json"):
            json.loads(path.read_text(encoding="utf-8"))
        strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
        english = json.loads((COMPONENT / "translations" / "en.json").read_text(encoding="utf-8"))
        self.assertEqual(strings, english)
        self.assertEqual(strings["title"], "Tuesly")
        self.assertIn("Architech Labs", strings["config"]["step"]["user"]["description"])
        self.assertIn("existing mesh keys", strings["config"]["step"]["sig_plug"]["description"])

    def test_local_brand_images_have_required_dimensions_and_transparency(self):
        for prefix in ("", "dark_"):
            for suffix, scale in (("", 1), ("@2x", 2)):
                for kind, dimensions in (("icon", (256*scale, 256*scale)), ("logo", (512*scale, 160*scale))):
                    path = COMPONENT / "brand" / f"{prefix}{kind}{suffix}.png"
                    with Image.open(path) as image:
                        self.assertEqual(image.size, dimensions)
                        self.assertEqual(image.mode, "RGBA")
                        self.assertEqual(image.getpixel((0, 0))[3], 0)
        self.assertNotEqual((COMPONENT / "brand" / "logo.png").read_bytes(),
                            (COMPONENT / "brand" / "dark_logo.png").read_bytes())

    def test_required_third_party_license_is_retained(self):
        notice = (COMPONENT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        self.assertIn("Copyright (c) 2024 11z4t", notice)
        self.assertIn("Permission is hereby granted, free of charge", notice)

    def test_own_contributions_do_not_receive_mit_grant(self):
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("All rights reserved", license_text)
        self.assertIn("does not revoke", license_text)
        self.assertNotIn("Permission is hereby granted, free of charge", license_text)

    def test_device_profiles_are_bundled_at_runtime_lookup_path(self):
        self.assertTrue((COMPONENT / "profiles" / "9952126_led_driver.yaml").exists())


if __name__ == "__main__":
    unittest.main()
