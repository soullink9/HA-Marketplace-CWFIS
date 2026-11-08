# Changelog

## Unreleased

### Repository

- Gitea is the main copy: its runner checks every push and publishes releases (`.gitea/workflows/`), with nothing
  downloaded from GitHub, so it keeps working when GitHub can't be reached. Gitea push-mirrors to GitHub, and a
  version tag arriving there publishes the same release on GitHub, where the Marketplace installs from.
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
