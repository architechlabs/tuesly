"""Package Tuesly directly from its standalone source tree."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]


def main():
    component = ROOT / "custom_components" / "tuesly"
    manifest = json.loads((component / "manifest.json").read_text(encoding="utf-8"))
    project = json.loads((ROOT / "project.json").read_text(encoding="utf-8"))
    if manifest["domain"] != "tuesly" or manifest["version"] != project["version"]:
        raise SystemExit("Project metadata and integration manifest do not match")
    for required in ("LICENSE", "THIRD_PARTY_NOTICES.md", "README.md"):
        (component / required).write_text((ROOT / required).read_text(encoding="utf-8"), encoding="utf-8")
    docs = component / 'docs'
    docs.mkdir(exist_ok=True)
    for name in ('SITE_INSTALLATION.md','OFFLINE_VALIDATION_0.2.7.md'):
        (docs/name).write_bytes((ROOT/'docs'/name).read_bytes())
    destination = ROOT / "dist" / f"tuesly-{manifest['version']}.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        for path in sorted(component.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                archive.write(path, path.relative_to(ROOT).as_posix())
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    (destination.with_suffix(".zip.sha256")).write_text(f"{digest}  {destination.name}\n", encoding="utf-8")
    print(destination)
    print("SHA256:", digest)


if __name__ == "__main__":
    main()
