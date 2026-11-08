"""Checks a release tag against the integration's version, and writes the release's notes.

Used by both release workflows (.gitea/workflows/release.yml and .github/workflows/release.yml):
    python3 scripts/release_notes.py <tag> <owner/repo on GitHub> <notes file>
(the tag is v<version>, whether the release was started from the Run workflow button or by pushing a tag).
The notes always point at the public copy on GitHub, also in a release made on Gitea.

1. The tag must name the version everywhere the project carries it (VERSION_FILES below; a leading "v" and letter
   case are ignored, so v1.2.0-Beta matches 1.2.0-beta), and CHANGELOG.md must have a section for it. A mismatch
   fails the release, so a zip is never published under the wrong version.
2. The notes are short install steps (the Marketplace, or the zip by hand, with the zip's own download address),
   then that version's section of CHANGELOG.md. Links in the changelog are relative to the repository; they're
   made absolute (at the tag) so they work on the release page.

Prints, for the workflow: "prerelease=true" or "prerelease=false" (versions with a suffix, like 1.3.0-beta, are
published as pre-releases), and "title=..." (v1.3.0-beta -> "V1.3.0 Beta", v1.2.0 -> "V1.2.0").
Exits non-zero, with the reason, when the release must not go ahead.
"""

import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "cwfis"
NAME = "CWFIS"  # the name the Marketplace lists it under
ZIP = f"{DOMAIN}.zip"  # the same name in every release, so .../releases/latest/download/<ZIP> always works
# Every other place that carries the version, as (file, pattern whose first group is the version).
VERSION_FILES = []
EXTRA_ASSETS = []  # files published next to the zip, as (file name, what it is for)


def project_versions():
    """Every version the project carries, as {where: version}; they must all agree."""
    manifest = ROOT / "custom_components" / DOMAIN / "manifest.json"
    versions = {str(manifest.relative_to(ROOT)): json.loads(manifest.read_text())["version"]}
    for path, pattern in VERSION_FILES:
        found = re.findall(pattern, (ROOT / path).read_text(), re.M)
        if not found:
            versions[path] = None
        for index, version in enumerate(found):
            label = path if len(found) == 1 else f"{path} (#{index + 1})"
            versions[label] = version
    return versions


def changelog_section(version):
    """CHANGELOG.md's section for `version` (the text under "## <version> (date)"), or None.

    The version has to match the heading's whole version: 1.2.0 doesn't take 1.2.0-beta's section.
    """
    text = (ROOT / "CHANGELOG.md").read_text()
    heading = re.compile(rf"^## {re.escape(version)}(?=\s|$).*$", re.M | re.I)
    start = heading.search(text)
    if not start:
        return None
    following = re.compile(r"^## ", re.M).search(text, start.end())
    end = following.start() if following else len(text)
    return text[start.end() : end].strip()


def absolute_links(text, repo, tag):
    """Relative links (README.md#install, docs/Installation.md...) as links to the repository at the tag."""

    def fix(match):
        target = match[2]
        if re.match(r"^[a-z]+:", target) or target.startswith("#"):
            return match[0]  # already absolute, or a link within the page
        path, _, anchor = target.partition("#")
        if path in ("", "README.md"):
            url = f"https://github.com/{repo}/tree/{tag}"
        else:
            url = f"https://github.com/{repo}/blob/{tag}/{path}"
        if anchor:
            url += "#" + anchor
        return f"[{match[1]}]({url})"

    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", fix, text)


def release_title(version):
    """The release's name: 1.3.0-beta -> "V1.3.0 Beta", 1.2.0 -> "V1.2.0"."""
    number, _, suffix = version.partition("-")
    if suffix:
        return f"V{number} {suffix.capitalize()}"
    return f"V{number}"


def install_steps(repo, tag):
    """How to install this release: the Marketplace first, the zip by hand as the alternative."""
    download = f"https://github.com/{repo}/releases/download/{tag}"
    steps = (
        "## Install\n\n"
        f"- **From the Marketplace** (Home Assistant 2026.11 and newer): **Settings → Marketplace**, search for "
        f"**{NAME}** and install it. If it's already installed, the Marketplace offers this release as an update.\n"
        f"- **By hand:** download **{ZIP}** below ({download}/{ZIP}), unzip it into `/config/custom_components/` "
        f"(you get `/config/custom_components/{DOMAIN}/`), and restart Home Assistant.\n"
    )
    for name, description in EXTRA_ASSETS:
        steps += f"- **{name}** ({download}/{name}): {description}\n"
    return steps + "\n[Installation](docs/Installation.md) has the details.\n\n"


def main():
    """Check the tag, write the notes file, and tell the workflow the release's title and pre-release flag."""
    tag, repo, notes_file = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    version = tag[1:] if tag[:1] in ("v", "V") else tag
    versions = project_versions()
    if len(set(versions.values())) != 1:
        listed = ", ".join(f"{where} says {found}" for where, found in versions.items())
        sys.exit(f"The versions disagree ({listed}): make them match first")
    project = next(iter(versions.values()))
    if version.lower() != project.lower():
        sys.exit(
            f"{version} isn't the integration's version ({project}): release {project}, or change the version first"
        )
    section = changelog_section(project)
    if not section:
        sys.exit(f"CHANGELOG.md has no section for {project}: add one first")

    notes = install_steps(repo, tag) + "## What's in it\n\n" + section + "\n"
    notes_file.write_text(absolute_links(notes, repo, tag))
    print(f"prerelease={'true' if '-' in project else 'false'}")
    print(f"title={release_title(project)}")


if __name__ == "__main__":
    main()
