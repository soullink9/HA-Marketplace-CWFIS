# Tests

Run everything from the repository root. Each test is a plain Python script, not a pytest suite: it prints what it
checks and exits non-zero if anything failed. These are the commands the Test workflow runs:

```sh
python3 tests/test_integration.py
python3 tests/test_release.py
```

| Script | What it checks |
|---|---|
| `test_integration.py` | Offline simulation of the CWFIS integration — run before every release |
| `test_release.py` | The release scripts in `scripts/`: the version check and notes, building and checking the zip, and publishing to a fake Gitea server |

[CONTRIBUTING.md](../CONTRIBUTING.md#checking-a-change) says which to run for which change, and how long each takes.
The tests stand in for Home Assistant (`stubs.py`), so they can't prove the integration works on a real Home
Assistant: try changes on a real installation too.
