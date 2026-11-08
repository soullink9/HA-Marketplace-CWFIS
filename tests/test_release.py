"""Release scripts: the version check and notes (scripts/release_notes.py), building and checking the zip
(scripts/build_package.py, scripts/check_package.py), and publishing on Gitea (scripts/publish_gitea_release.py)
against a fake Gitea server. These run in both release workflows, so a mistake here would stop or spoil a release.

Run:  python3 tests/test_release.py   (Python's standard library only; prints PASS/FAIL per check)
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile

sys.dont_write_bytecode = True  # keep __pycache__ out of the repository (and out of the zip built below)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_package  # noqa: E402,I001  (scripts/ is put on the path just above)
import check_package  # noqa: E402
import release_notes  # noqa: E402

DOMAIN = "cwfis"
REPO = "soullink9/HA-Marketplace-CWFIS"
ZIP = f"{DOMAIN}.zip"
FAILURES = []
TMP = Path(tempfile.mkdtemp())
VERSION = json.loads((ROOT / "custom_components" / DOMAIN / "manifest.json").read_text())["version"]


def check(ok, message):
    """Print one result and remember failures."""
    print(("PASS " if ok else "FAIL ") + message)
    if not ok:
        FAILURES.append(message)


# --- release_notes.py: the tag must match every version in the project, and the notes give the zip's address ---
def notes_script(tag, root=ROOT):
    """Run release_notes.py (from `root`, a copy of the repository when a test changes files) for a tag."""
    notes = TMP / "notes.md"
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "release_notes.py"), tag, REPO, str(notes)],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


def repository_copy():
    """The files release_notes.py reads, copied somewhere a test can change them."""
    copy = Path(tempfile.mkdtemp(dir=TMP))
    paths = ["scripts/release_notes.py", "CHANGELOG.md", f"custom_components/{DOMAIN}/manifest.json"]
    paths += [path for path, _ in release_notes.VERSION_FILES]
    for path in paths:
        (copy / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, copy / path)
    return copy


def test_notes():
    """The version check, the notes and the release's title."""
    code, out, err = notes_script(f"v{VERSION}")
    notes = (TMP / "notes.md").read_text() if code == 0 else ""
    check(
        code == 0 and f"title={release_notes.release_title(VERSION)}" in out and "prerelease=false" in out,
        f"the integration's own version: notes written, title and pre-release given to the workflow ({out.strip()!r} {err.strip()!r})",
    )
    zip_url = f"https://github.com/{REPO}/releases/download/v{VERSION}/{ZIP}"
    check(
        zip_url in notes and "Marketplace" in notes,
        "notes say how to install: the Marketplace, or the zip's own address",
    )
    check(
        "## What's in it" in notes and release_notes.changelog_section(VERSION) is not None,
        "…then that version's changelog",
    )
    check(
        not re.search(r"\]\((?!https?:|#)", notes),
        "every link in the notes is absolute, so it works on the release page",
    )
    check(notes_script(f"V{VERSION}")[0] == 0, "a capital V works too")

    code, _, err = notes_script("v9.9.9")
    check(code != 0 and "isn't the integration's version" in err, f"another version: refused ({err.strip()})")

    copy = repository_copy()
    manifest = copy / "custom_components" / DOMAIN / "manifest.json"
    data = json.loads(manifest.read_text())
    data["version"] = "9.9.9"
    manifest.write_text(json.dumps(data))
    code, _, err = notes_script("v9.9.9", copy)
    if release_notes.VERSION_FILES:
        check(code != 0 and "disagree" in err, f"one version changed and not the others: refused ({err.strip()[:90]})")
    else:
        check(
            code != 0 and "no section for 9.9.9" in err, f"a version with no changelog section: refused ({err.strip()})"
        )

    copy = repository_copy()
    changelog = copy / "CHANGELOG.md"
    changelog.write_text(changelog.read_text().replace(f"## {VERSION} ", f"## {VERSION}-beta ", 1))
    code, _, err = notes_script(f"v{VERSION}", copy)
    check(
        code != 0 and "no section" in err,
        f"only a {VERSION}-beta section: {VERSION} isn't taken for it ({err.strip()})",
    )

    check(
        release_notes.release_title("1.3.0-beta") == "V1.3.0 Beta" and release_notes.release_title("1.2.0") == "V1.2.0",
        "release titles: V1.3.0 Beta, V1.2.0",
    )


# --- build_package.py and check_package.py: what installs as custom_components/<domain>/ ---------------------
def make_zip(name, files):
    """A zip with the given {name: content}."""
    path = TMP / name
    with zipfile.ZipFile(path, "w") as archive:
        for member, data in files.items():
            archive.writestr(member, data)
    return path


def built_files():
    """The real build's files, as {name: bytes}, to make broken copies of."""
    with zipfile.ZipFile(ROOT / "dist" / ZIP) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_package():
    """The real build passes; every kind of broken zip is refused."""
    first = build_package.build()
    first_bytes = first.read_bytes()
    check(check_package.problems_in(first) == [], f"the real build: dist/{ZIP} passes the install check")
    check(build_package.build().read_bytes() == first_bytes, "building again gives the same zip, byte for byte")
    good = built_files()
    check(all(name.startswith(f"{DOMAIN}/") for name in good), f"everything is inside {DOMAIN}/")
    check(not any("__pycache__" in name for name in good), "no __pycache__ in the zip")

    flat = {name.split("/", 1)[1]: data for name, data in good.items()}
    check(check_package.problems_in(make_zip("flat.zip", flat)) != [], f"files not inside {DOMAIN}/: refused")
    (TMP / "page.zip").write_text("<html>release page</html>")
    check(check_package.problems_in(TMP / "page.zip") != [], "a web page saved as .zip: refused")
    old = dict(good)
    manifest = json.loads(old[f"{DOMAIN}/manifest.json"])
    manifest["version"] = "0.0.1"
    old[f"{DOMAIN}/manifest.json"] = json.dumps(manifest)
    problems = check_package.problems_in(make_zip("old.zip", old))
    check(any("rebuild" in problem for problem in problems), "a zip of another version: refused")
    leftovers = {**good, f"{DOMAIN}/__pycache__/const.cpython-314.pyc": b"\0"}
    check(check_package.problems_in(make_zip("cache.zip", leftovers)) != [], "a zip with __pycache__ in it: refused")
    missing = {name: data for name, data in good.items() if name != f"{DOMAIN}/brand/icon.png"}
    check(check_package.problems_in(make_zip("noicon.zip", missing)) != [], "a zip without the icon: refused")
    unsafe = {**good, f"{DOMAIN}/../evil.py": b""}
    check(check_package.problems_in(make_zip("unsafe.zip", unsafe)) != [], "a path climbing out with ..: refused")
    wrong_domain = dict(good)
    manifest = json.loads(good[f"{DOMAIN}/manifest.json"])
    manifest["domain"] = "something_else"
    wrong_domain[f"{DOMAIN}/manifest.json"] = json.dumps(manifest)
    check(
        check_package.problems_in(make_zip("domain.zip", wrong_domain)) != [], "a manifest for another domain: refused"
    )


# --- publish_gitea_release.py against a fake Gitea ------------------------------------------------------------
class FakeGitea(BaseHTTPRequestHandler):
    """Just enough of Gitea's release API: releases by tag, create, edit, delete and upload attachments."""

    releases = {}
    calls = []
    uploads = {}  # asset id -> (bytes, sent as "attachment", content type)
    next_id = 1

    def log_message(self, *args):
        """Keep the test's output to its results."""

    def reply(self, code, body=None):
        """Send a JSON reply."""
        data = json.dumps(body).encode() if body is not None else b""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_any(self):
        """Every method: check the token, then act like Gitea's release endpoints."""
        base = "/api/v1/repos/owner/repo"
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        FakeGitea.calls.append((self.command, self.path, self.headers.get("Authorization")))
        if self.headers.get("Authorization") != "token secret":
            return self.reply(401, {"message": "token is required"})
        if not path.startswith(base):
            return self.reply(404, {"message": "not found"})
        path = path[len(base) :]
        if self.command == "GET" and path.startswith("/releases/tags/"):
            tag = path.rsplit("/", 1)[1]
            found = [release for release in FakeGitea.releases.values() if release["tag_name"] == tag]
            if found:
                return self.reply(200, found[0])
            return self.reply(404, {"message": "release not found"})
        if self.command == "POST" and path == "/releases":
            release = {**json.loads(body), "id": FakeGitea.next_id, "assets": []}
            FakeGitea.releases[release["id"]] = release
            FakeGitea.next_id += 1
            return self.reply(201, release)
        match = re.fullmatch(r"/releases/(\d+)(/assets(?:/(\d+))?)?", path)
        if not match or int(match[1]) not in FakeGitea.releases:
            return self.reply(404, {"message": "not found"})
        release = FakeGitea.releases[int(match[1])]
        if self.command == "PATCH" and not match[2]:
            release.update(json.loads(body))
            return self.reply(200, release)
        if self.command == "DELETE" and match[3]:
            release["assets"] = [asset for asset in release["assets"] if asset["id"] != int(match[3])]
            return self.reply(204)
        if self.command == "POST" and match[2] and not match[3]:
            boundary = self.headers["Content-Type"].split("boundary=")[1].encode()
            part = body.split(b"--" + boundary)[1]
            head, content = part.split(b"\r\n\r\n", 1)
            name = self.path.split("name=")[1]
            asset = {"id": FakeGitea.next_id, "name": name}
            content_type = re.search(rb"Content-Type: ([^\r]+)", head)[1].decode()
            FakeGitea.uploads[asset["id"]] = (content[:-2], b'name="attachment"' in head, content_type)
            FakeGitea.next_id += 1
            release["assets"].append(asset)
            return self.reply(201, asset)
        return self.reply(405, {"message": "method not allowed"})

    do_GET = do_POST = do_PATCH = do_DELETE = handle_any


def test_publish():
    """Create, update, refuse: the Gitea side of a release."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeGitea)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    gitea_url = f"http://127.0.0.1:{server.server_port}"
    files = [ROOT / "dist" / ZIP] + [ROOT / "dist" / name for _, name in build_package.EXTRA_COPIES]
    env = {**os.environ, "GITHUB_SERVER_URL": gitea_url, "GITHUB_REPOSITORY": "owner/repo", "RELEASE_TOKEN": "secret"}
    notes_script(f"v{VERSION}")
    notes = (TMP / "notes.md").read_text()

    def run_publish(title, extra_env=None, upload=files):
        command = [sys.executable, str(ROOT / "scripts" / "publish_gitea_release.py"), "v1.9.0", "abc123", title]
        command += [str(TMP / "notes.md"), "false"] + [str(path) for path in upload]
        return subprocess.run(command, env={**env, **(extra_env or {})}, capture_output=True, text=True)

    result = run_publish("V1.9.0")
    release = next(iter(FakeGitea.releases.values()), {})
    check(
        result.returncode == 0
        and release.get("tag_name") == "v1.9.0"
        and release.get("target_commitish") == "abc123"
        and release.get("name") == "V1.9.0"
        and release.get("body") == notes
        and release.get("prerelease") is False,
        f"new release: created with its tag on the released commit, title and notes ({result.stdout.strip()!r} {result.stderr.strip()!r})",
    )
    uploaded = {asset["name"]: FakeGitea.uploads[asset["id"]] for asset in release.get("assets", [])}
    check(
        sorted(uploaded) == sorted(path.name for path in files)
        and all(uploaded[path.name][:2] == (path.read_bytes(), True) for path in files),
        f'…and its files uploaded byte for byte, as Gitea\'s "attachment" field ({", ".join(sorted(uploaded))})',
    )
    check(uploaded.get(ZIP, (None, None, ""))[2] == "application/zip", "the zip is sent as application/zip")
    check(all(auth == "token secret" for _, _, auth in FakeGitea.calls), "every call carries the token")

    result = run_publish("V1.9.0 again")
    check(
        result.returncode == 0
        and len(FakeGitea.releases) == 1
        and release["name"] == "V1.9.0 again"
        and sorted(asset["name"] for asset in release["assets"]) == sorted(path.name for path in files),
        "run again for the same tag: the release is updated and its files replaced, not doubled",
    )

    result = run_publish("V1.9.0", {"RELEASE_TOKEN": "wrong"})
    check(
        result.returncode != 0 and "401" in result.stderr,
        f"a token Gitea refuses: stops with Gitea's answer ({result.stderr.strip()[:80]})",
    )
    result = run_publish(
        "V1.9.0 inside", {"GITHUB_SERVER_URL": "https://gitea.example.invalid", "GITEA_INTERNAL_URL": gitea_url}
    )
    check(
        result.returncode == 0 and release["name"] == "V1.9.0 inside",
        "public address unreachable from the runner: GITEA_INTERNAL_URL is used instead",
    )
    result = run_publish("V1.9.0", {"RELEASE_TOKEN": ""})
    check(
        result.returncode != 0 and "RELEASE_TOKEN" in result.stderr, "no token: stops and says which setting is missing"
    )
    result = run_publish("V1.9.0", upload=[])
    check(
        result.returncode != 0 and "Nothing to upload" in result.stderr, "no files named: stops before touching Gitea"
    )
    server.shutdown()


if __name__ == "__main__":
    try:
        test_notes()
        test_package()
        test_publish()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED")
        sys.exit(1)
    print("All checks passed.")
