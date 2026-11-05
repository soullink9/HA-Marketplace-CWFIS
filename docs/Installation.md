# Installation

**Needs:** Home Assistant **2026.3 or newer**, which is the first version that shows the integration's built-in icon. It was developed and tested on Core 2026.9.4. Home Assistant must be able to reach `geoserver.cwfif.nrcan.gc.ca`, `cwfis.cfs.nrcan.gc.ca` and `air-quality-api.open-meteo.com`.

## From the Marketplace

In Home Assistant 2026.11 and newer, open **Settings → Marketplace**, search for **Canadian Wildland Fire Information System** and install it, then
restart Home Assistant. Updates then show up under **Settings → Updates**.

If it isn't listed yet, add it from its link instead: this repository's address,
`https://github.com/soullink9/HA-Marketplace-CWFIS`. Adding from a link needs Home Assistant to be connected to GitHub.

To install by hand instead, follow the steps below.

## Download

1. Copy the [`custom_components/cwfis`](../custom_components/cwfis) folder from this repository into `/config/custom_components/`, so that `config/custom_components/cwfis/manifest.json` exists.
2. Restart Home Assistant.

## Adding the integration

1. Go to **Settings → Devices & services → Add integration** and search for **Canadian Wildland Fire Information System**.
2. Click it. No questions are asked: it uses your Home Assistant **Home** location.
3. Open the integration and choose **Configure** to adjust it. The [Settings](Settings.md) page explains each option.

Only one CWFIS entry can be added. Use extra watch zones to cover more places.

## Updating

Replace the whole `custom_components/cwfis` folder with the new version, then restart.

Your settings and entity IDs carry over. The [changelog](../CHANGELOG.md) lists what changed.

## Removing

1. Go to **Settings → Devices & services → Canadian Wildland Fire Information System → ⋮ → Delete**.
2. Delete the `custom_components/cwfis` folder.
3. Restart Home Assistant.