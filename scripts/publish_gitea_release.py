"""Publishes a release on Gitea: creates it (and its tag) or updates it, then uploads its files.

Used by .gitea/workflows/release.yml:
    python3 scripts/publish_gitea_release.py <tag> <commit> <title> <notes file> <prerelease true|false> <file>...
(the files are what build_package.py put in dist/: the integration's zip)

GitHub's workflow uses the `gh` tool for this; Gitea has no such tool on its runners, so this talks to Gitea's
API directly, with Python's standard library only (so it runs on any runner, with nothing to install).

It reads from the environment, as Gitea's runner sets it:
    GITHUB_SERVER_URL   the Gitea address (Gitea keeps GitHub's variable names, so workflows work on both)
    GITEA_INTERNAL_URL  optional: Gitea's address as the runner's jobs reach it, used instead when set (a runner
                        next to Gitea often can't reach its public address, ROOT_URL)
    GITHUB_REPOSITORY   owner/repo on Gitea
    RELEASE_TOKEN       a token that may create releases (the workflow passes the job's own token)

Safe to run again for the same tag: an existing release gets the new title, notes and files, so a release made by
hand on Gitea, or one whose upload failed halfway, ends up complete. Exits non-zero, with the reason, on any error.
"""

import json
import mimetypes
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid


class Gitea:
    """The few calls of Gitea's API a release needs."""

    def __init__(self, server, repository, token):
        """Talk to the repository `repository` on the Gitea at `server`, as the owner of `token`."""
        self.base = f"{server.rstrip('/')}/api/v1/repos/{repository}"
        self.token = token

    def call(self, method, path, body=None, content_type="application/json"):
        """One API call; returns the decoded JSON reply (None when there isn't one).
        Raises urllib.error.HTTPError with Gitea's message on a refusal."""
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=body, method=method)
        request.add_header("Authorization", f"token {self.token}")
        request.add_header("Accept", "application/json")
        if body is not None:
            request.add_header("Content-Type", content_type)
        with urllib.request.urlopen(request, timeout=120) as reply:
            data = reply.read()
        return json.loads(data) if data else None

    def release_for(self, tag):
        """The release for a tag, or None if there isn't one yet."""
        try:
            return self.call("GET", f"/releases/tags/{urllib.parse.quote(tag)}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def upload(self, release_id, file_path):
        """Attaches a file to a release (multipart form, field "attachment", as Gitea's API expects)."""
        boundary = uuid.uuid4().hex
        name = Path(file_path).name
        # application/zip for the zip; a guess from the extension for anything else (application/octet-stream if none)
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        body = (
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="attachment"; filename="{name}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode()
            + Path(file_path).read_bytes()
            + f"\r\n--{boundary}--\r\n".encode()
        )
        query = urllib.parse.urlencode({"name": name})
        return self.call(
            "POST", f"/releases/{release_id}/assets?{query}", body, f"multipart/form-data; boundary={boundary}"
        )


def publish(gitea, tag, commit, title, notes, prerelease, file_paths):
    """Create or update the release for `tag` (made on `commit` if the tag doesn't exist yet), and make each
    file its only file of that name. Returns the release."""
    fields = {"name": title, "body": notes, "prerelease": prerelease, "draft": False}
    release = gitea.release_for(tag)
    if release is None:
        release = gitea.call("POST", "/releases", {"tag_name": tag, "target_commitish": commit, **fields})
        print(f"Created release {title} ({tag})")
    else:
        release = gitea.call("PATCH", f"/releases/{release['id']}", fields)
        print(f"Updated release {title} ({tag})")
    for file_path in file_paths:
        name = Path(file_path).name
        for asset in release.get("assets") or []:
            if asset["name"] == name:  # replace, rather than end up with two files of the same name
                gitea.call("DELETE", f"/releases/{release['id']}/assets/{asset['id']}")
        gitea.upload(release["id"], file_path)
        print(f"Uploaded {name}")
    return release


def main():
    """Read the arguments and environment, and publish."""
    tag, commit, title, notes_file, prerelease = sys.argv[1:6]
    file_paths = sys.argv[6:]
    if not file_paths:
        sys.exit("Nothing to upload: name the release's files after the pre-release flag")
    missing = [v for v in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "RELEASE_TOKEN") if not os.environ.get(v)]
    if missing:
        sys.exit(f"Not set: {', '.join(missing)}")
    server = os.environ.get("GITEA_INTERNAL_URL") or os.environ["GITHUB_SERVER_URL"]
    gitea = Gitea(server, os.environ["GITHUB_REPOSITORY"], os.environ["RELEASE_TOKEN"])
    try:
        publish(gitea, tag, commit, title, Path(notes_file).read_text(), prerelease == "true", file_paths)
    except urllib.error.HTTPError as e:
        sys.exit(f"Gitea refused {e.url}: {e.code} {e.read().decode(errors='replace')}")
    except urllib.error.URLError as e:
        sys.exit(f"Can't reach Gitea at {server}: {e.reason}")


if __name__ == "__main__":
    main()
