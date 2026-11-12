"""Works out which releases GitHub still needs, so it ends up with the same releases as Gitea.

Used by .github/workflows/release.yml, after any push from Gitea's mirror:
    gh release list --limit 1000 --json tagName,isDraft > releases.json
    python3 scripts/plan_github_releases.py releases.json "$GITHUB_OUTPUT"
Adds "releases=<JSON list>" to the step's outputs file, one entry per release to publish, oldest version first
(it writes the file itself, so what it prints, warnings included, still reaches the run's log):
    [{"tag": "v1.2.1", "latest": false}, {"tag": "v1.3.0", "latest": true}]

Why not just publish when a tag arrives: Gitea pushes to GitHub on a timer, so one push can bring several new
tags, and GitHub starts no workflow for any of them when more than three arrive at once. Looking at every tag
on every push catches those, and any release whose run failed or never started, the next time Gitea pushes.

A tag needs a release when it's a version tag (v1.2.3, or v1.3.0-beta) and GitHub has no published release for
it. A draft counts as missing: GitHub turns a release into a draft when its tag disappears (the mirror deletes
tags Gitea doesn't have), so a draft on a tag that's back is a release to publish again. Releases GitHub already
has are never touched.

Tags from before the release scripts existed (no scripts/release_notes.py in them) can't be built the same way,
so they're left out with a warning; publish those by hand if they need a release.

"Latest" goes to the newest version without a suffix, and only when it's one being published now. GitHub would
otherwise mark each new release as latest, so publishing an older version after a newer one would make it
"latest", and .../releases/latest/download/<file> would hand out the older files.
"""

import json
from pathlib import Path
import re
import subprocess
import sys

VERSION_TAG = re.compile(r"^[vV](\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")


def version_key(tag):
    """Sort key for a version tag: by number, a suffixed version (1.3.0-beta) before the plain one (1.3.0)."""
    major, minor, patch, suffix = VERSION_TAG.match(tag).groups()
    return (int(major), int(minor), int(patch), 0 if suffix else 1, suffix or "")


def is_stable(tag):
    """True for a version without a suffix: 1.2.0 is stable, 1.3.0-beta is a pre-release."""
    return VERSION_TAG.match(tag).group(4) is None


def plan(tags, releases, buildable=lambda tag: True):
    """The releases to publish, as [{"tag", "latest"}] oldest first, and the tags skipped (not buildable).

    tags: every tag in the repository. releases: GitHub's releases, as `gh release list --json tagName,isDraft`
    gives them. buildable(tag): whether the tag has the release scripts.
    """
    versions = sorted((tag for tag in tags if VERSION_TAG.match(tag)), key=version_key)
    published = {release["tagName"] for release in releases if not release.get("isDraft")}
    stable = [tag for tag in versions if is_stable(tag)]
    newest_stable = stable[-1] if stable else None

    to_publish, skipped = [], []
    for tag in versions:
        if tag in published:
            continue
        if not buildable(tag):
            skipped.append(tag)
            continue
        to_publish.append({"tag": tag, "latest": tag == newest_stable})
    return to_publish, skipped


def has_release_scripts(tag):
    """Whether the tag's commit has scripts/release_notes.py (tags from before it can't be built here)."""
    found = subprocess.run(["git", "cat-file", "-e", f"{tag}:scripts/release_notes.py"], capture_output=True)
    return found.returncode == 0


def main():
    """Read GitHub's releases from the file named, compare with the repository's tags, and write the plan."""
    releases_file, outputs_file = Path(sys.argv[1]), Path(sys.argv[2])
    releases = json.loads(releases_file.read_text() or "[]")
    tags = subprocess.run(["git", "tag", "--list"], capture_output=True, text=True, check=True).stdout.split()
    to_publish, skipped = plan(tags, releases, has_release_scripts)
    for tag in skipped:
        # A workflow annotation (it has to go to standard output), shown on the run's summary page.
        print(f"::warning::{tag} has no GitHub release, but it's older than the release scripts: publish it by hand")
    with outputs_file.open("a") as outputs:
        outputs.write(f"releases={json.dumps(to_publish)}\n")
    names = ", ".join(entry["tag"] for entry in to_publish) or "nothing: GitHub has every release"
    print(f"To publish: {names}")


if __name__ == "__main__":
    main()
