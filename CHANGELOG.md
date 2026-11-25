# Changelog

## 1.4.3 (2026-11-25)

Telemetry audit. Nothing changes in how CWFIS works: the integration itself never had analytics or tracking, and still
only contacts the servers listed in [Privacy](docs/Privacy.md).

### Repository

- Every CI workflow now sets `GH_TELEMETRY=false` and `DO_NOT_TRACK=1`. Since v2.91.0 the GitHub CLI (`gh`, used by
  GitHub's release workflow) sends usage telemetry unless told not to; this turns it off, along with any other tool
  that honours `DO_NOT_TRACK`. A new check in `tests/test_release.py` fails if a workflow leaves either out.

## 1.4.2 (2026-11-25)

Dependency update. Nothing changes in how CWFIS works; it still has no Python requirements of its own.

### Repository

- CI moves to the latest pinned versions: `actions/checkout` v7.0.1 (was v5.1.0), `actions/setup-python` v7.1.0
  (was v6.3.0), the latest `hassfest` from Home Assistant's actions, and a fresh `python:3.14-bookworm` image digest
  (Python 3.14.10) for the Gitea jobs. `ruff` 0.17.6 and the HACS action were already the latest.

## 1.4.1 (2026-11-22)

Hardening from a security review. Nothing changes in how CWFIS looks or what its entities are called.

- **Bad data from a server no longer takes everything down.** A malformed fire record, a value of the wrong type,
  NaN, infinity or an impossible number is now skipped or treated as missing, instead of failing the whole update and
  making every entity unavailable. Fire sizes, PM2.5 values, coordinates, fire danger codes and dates are all checked
  against believable ranges, so Smoke impact and Fire threat can't show nonsense.
- **Each optional source fails on its own.** A malformed hotspot, perimeter, fire danger or smoke forecast response
  now leaves only its own sensors unknown. **Reported today** is now optional too: if its query fails, only it shows
  unknown.
- **Fire alerts survive a restart.** What Fire alert last saw is saved, so changes made while Home Assistant was
  stopped are still announced, and the "Fire grew" baseline keeps adding up. After more than 12 hours off it starts
  afresh rather than sending a burst of old news. The saved file is removed with the integration.
- **Map images** accept only a real PNG of at most 10 MB, and the log shows only the map server's own error message,
  short and as plain text, never the raw response.
- Very deep or very large fire perimeters are capped, so an oversized response can't tie up Home Assistant.
- A sensor of yours (wind, PM2.5) that reports `nan` or `inf` now counts as unavailable.

### Repository

- Every GitHub action is pinned to a commit SHA, the Gitea job image to a digest, and `ruff` to a version and hashes
  (`requirements-ci.txt`), so an upstream change can't slip into a run that publishes a release.
- GitHub's release workflow grants write access only to the publishing job, and checkouts no longer keep the token.
- The release scripts and Gitea's release workflow refuse anything but a plain version tag (`v1.2.3`,
  `v1.3.0-beta`).
- New test scenarios for hostile server data, malformed optional responses, map downloads, and the saved alert
  baseline (restart, long time off, unreadable file).

## 1.4.0 (2026-11-21)

- **What it means for you.** Two new sensors for Home and every watch zone turn the fire and smoke data into a
  level you can act on, each with plain-language advice:
  - **Smoke impact**: how smoky the air is now or will be over the next 24 hours, on the US Air Quality Index or
    Canada's AQHI. It uses your own PM2.5 sensor for Home when you have one.
  - **Fire threat**: None, Watch, Warning or Danger, from how close fires, perimeters and hotspots are, whether a
    fire is under control, and the local fire danger.
- New settings: **Air quality scale** (automatic from Home Assistant's country, US AQI or Canada's AQHI) and the
  **danger** and **warning distances** for Fire threat.
- The smoke forecast now covers every watch zone, not just Home.
- A **Local impact** dashboard card and a **CWFIS local impact alert** blueprint that notifies your phone when smoke
  or fire threat gets worse, and can run your own actions such as turning on an air purifier. See
  [Dashboards and Automations](docs/Dashboards-and-Automations.md#local-impact).

## 1.3.0 (2026-11-15)

- **Needs Home Assistant 2026.11 or newer.** CWFIS now follows the latest Home Assistant release only, and the
  Marketplace won't offer this version to older ones. Nothing changes in how it works, and entity IDs and history are
  kept.
- Entity names and icons now come from the integration's translations, the way Home Assistant expects, so names
  follow Home Assistant's naming of devices and entities. The English names are unchanged.
- The Configure form's lists (Fires on map, Map images) are translated the same way.
- Built for Home Assistant 2026.11: `probatio` for the settings form, Python 3.14, typed setup throughout, and the
  map images download through the same connection as the rest of the data.

### Repository

- Every check and release runs on Python 3.14, the version Home Assistant 2026.11 runs on.
- The tests also check that every entity's name and icon resolve, and that the names never change.
- Gitea is the main copy: its runner checks every push and publishes releases (`.gitea/workflows/`), with nothing
  downloaded from GitHub, so it keeps working when GitHub can't be reached. Gitea push-mirrors to GitHub, and every
  push from it publishes on GitHub the releases GitHub doesn't have yet, with the same files and notes, where the
  Marketplace installs from.
- The release helpers live in `scripts/` and are used by both: the version check and notes, building the zip, and
  publishing on Gitea. Every release's notes now start with how to install it.
- The release's zip is now always `cwfis.zip` (it had the version in its name), so
  `.../releases/latest/download/cwfis.zip` always gets the newest. Each zip is checked before it's published.

## 1.2.0 (2026-11-04)

- Moved to its own repository, [HA-Marketplace-CWFIS](https://github.com/soullink9/HA-Marketplace-CWFIS), so it can be installed and updated
  from the Home Assistant Marketplace (Home Assistant 2026.11 and newer). Installing by hand works as before.
- Lists its categories, so it shows up in the right place when browsing the Marketplace. No other changes to how
  the integration works.

## 1.1.1 (2026-11-02)

- No changes to the integration.

## 1.1.0 (2026-11-01)

- No changes to the integration.

## 1.0.2 (2026-11-01)

- No changes to the integration.
- The simulation test now runs from a random Home location on every run.

## 1.0.0 (2026-11-01)

Initial release.

- National summary sensors: reported today, active, out, total fires and area burned this season.
- Same-date-last-year comparison sensors for fires and area burned.
- Per-province (agency) breakdown in attributes, plus optional dedicated province sensors.
- Proximity sensors for Home and any extra watch zones: nearest active fire, fires nearby, nearest fire perimeter, satellite hotspots (24 h), prescribed burns and fire danger.
- Binary sensors: Fire within alert radius (per zone), Fire upwind (with a wind sensor) and Wildfire smoke (with a PM2.5 sensor).
- Fire alert event entity: new fire nearby, stage changed, fire grew, fire out.
- 24/48-hour PM2.5 smoke forecast for Home (Open-Meteo / ECMWF CAMS).
- Map markers for active fires (all, nearby only, or none) and optional Canada-wide map images (fire danger today and tomorrow, smoke, hotspots).
- UI-only setup and options. No YAML, API keys or extra packages.
- Built-in integration icon (Home Assistant 2026.3+).
- Offline simulation test suite (`tests/simulate.py`).
