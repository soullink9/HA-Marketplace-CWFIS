"""Builds the release's zip of the integration, then checks it the way Home Assistant will read it.

Used by both release workflows and the test workflow:  python3 scripts/build_package.py
Writes dist/cwfis.zip, and exits non-zero if check_package.py finds a problem.

The zip holds one folder, cwfis/, so unzipping it into /config/custom_components/ gives Home Assistant
/config/custom_components/cwfis/. Only the integration's own files go in: Python's __pycache__ folders
(left behind by running the tests) are skipped. Files are added in a fixed order with a fixed date, so the same
code always gives the same zip, byte for byte.
"""

from pathlib import Path
import shutil
import sys
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_package  # noqa: E402  (scripts/ is put on the path just above)

DOMAIN = "cwfis"
SOURCE = ROOT / "custom_components" / DOMAIN
DIST = ROOT / "dist"
FIXED_DATE = (2020, 1, 1, 0, 0, 0)  # zip dates can't be earlier than 1980; any fixed date makes builds repeatable
EXTRA_COPIES = []  # other files published next to the zip, as (path in the repository, name in dist/)


def integration_files():
    """The integration's files, relative to custom_components/, in a fixed order (no caches)."""
    files = []
    for path in sorted(SOURCE.rglob("*")):
        if path.is_dir() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        files.append(path.relative_to(SOURCE.parent).as_posix())
    return files


def build():
    """Write dist/<domain>.zip (and copy any other release files next to it); return the zip's path."""
    DIST.mkdir(exist_ok=True)
    zip_path = DIST / f"{DOMAIN}.zip"
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
        for name in integration_files():
            info = ZipInfo(name, FIXED_DATE)
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16  # an ordinary readable file, whatever the checkout's permissions
            archive.writestr(info, (SOURCE.parent / name).read_bytes())
    for source, name in EXTRA_COPIES:
        shutil.copyfile(ROOT / source, DIST / name)
    return zip_path


def main():
    """Build, check, and report."""
    zip_path = build()
    problems = check_package.problems_in(zip_path)
    if problems:
        sys.exit(f"{zip_path.name} isn't fit to publish:\n  " + "\n  ".join(problems))
    print(f"{zip_path.relative_to(ROOT)}: built and checked")


if __name__ == "__main__":
    main()
