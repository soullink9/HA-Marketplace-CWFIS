"""Checks the release's zip the way Home Assistant and the Marketplace will read it, so a zip that wouldn't install
never gets published.

Used by build_package.py (so every build checks its zip):  python3 scripts/check_package.py dist/cwfis.zip

Installing by hand means unzipping into /config/custom_components/, and Home Assistant then loads
custom_components/<domain>/ by the domain in its manifest.json. So this checks:

1. it's a zip that opens, and every file in it is intact;
2. everything is inside one folder named after the domain (cwfis/), with no absolute paths or "..", so
   nothing lands outside it when unzipped;
3. the folder holds __init__.py and a manifest.json whose domain is the folder's name, with the keys Home
   Assistant and the Marketplace need, and the icon the Marketplace shows (brand/icon.png);
4. the version inside matches the repository's manifest.json, so the zip is the build it claims to be;
5. it holds exactly the integration's files: none missing, and no leftovers such as __pycache__.

Exits non-zero, with every problem found, when the zip isn't fit to publish.
"""

import json
from pathlib import Path, PurePosixPath
import sys
from zipfile import BadZipFile, ZipFile

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "cwfis"
REQUIRED_FILES = ("__init__.py", "manifest.json", "brand/icon.png")
# What Home Assistant needs to load a custom integration, and the Marketplace to list it.
REQUIRED_KEYS = ("domain", "name", "version", "documentation", "issue_tracker", "codeowners")


def repository_files():
    """The integration's files in the repository, as they'd be named in the zip (no caches)."""
    source = ROOT / "custom_components" / DOMAIN
    names = set()
    for path in source.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            names.add(path.relative_to(source.parent).as_posix())
    return names


def problems_in(zip_path):
    """Everything about the zip that would stop it installing, or make it a different build (empty: it's fine)."""
    try:
        archive = ZipFile(zip_path)
    except (OSError, BadZipFile) as error:
        return [f"not a zip that opens: {error}"]
    with archive:
        broken = archive.testzip()
        if broken:
            return [f"damaged file in the zip: {broken}"]
        names = [name for name in archive.namelist() if not name.endswith("/")]
        problems = []
        for name in names:
            parts = PurePosixPath(name).parts
            if name.startswith("/") or ".." in parts:
                problems.append(f"unsafe path: {name}")
            elif parts[0] != DOMAIN or len(parts) < 2:
                problems.append(f"outside the {DOMAIN}/ folder: {name}")
        for required in REQUIRED_FILES:
            if f"{DOMAIN}/{required}" not in names:
                problems.append(f"missing {DOMAIN}/{required}")
        if f"{DOMAIN}/manifest.json" in names:
            problems += manifest_problems(archive.read(f"{DOMAIN}/manifest.json"))
        expected = repository_files()
        for missing in sorted(expected - set(names)):
            problems.append(f"missing {missing} (it's in the repository)")
        for extra in sorted(set(names) - expected):
            if PurePosixPath(extra).parts[0] == DOMAIN:
                problems.append(f"not one of the integration's files: {extra}")
        return problems


def manifest_problems(raw):
    """What's wrong with the manifest.json inside the zip."""
    try:
        manifest = json.loads(raw)
    except ValueError as error:
        return [f"manifest.json isn't valid JSON: {error}"]
    problems = [f"manifest.json has no {key}" for key in REQUIRED_KEYS if not manifest.get(key)]
    if manifest.get("domain") and manifest["domain"] != DOMAIN:
        problems.append(f"manifest.json says domain {manifest['domain']}, but the folder is {DOMAIN}")
    repository = json.loads((ROOT / "custom_components" / DOMAIN / "manifest.json").read_text())["version"]
    if manifest.get("version") and manifest["version"] != repository:
        problems.append(f"zip is version {manifest['version']}, the repository is {repository}: rebuild it")
    return problems


def main():
    """Check the zip named on the command line and report."""
    zip_path = sys.argv[1] if len(sys.argv) > 1 else f"dist/{DOMAIN}.zip"
    problems = problems_in(zip_path)
    if problems:
        sys.exit(f"{zip_path} won't install:\n  " + "\n  ".join(problems))
    print(f"{zip_path}: installs as custom_components/{DOMAIN}/")


if __name__ == "__main__":
    main()
