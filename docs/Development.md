# Development

This page explains how the code fits together. How to check a change and how to release are in the repository's [CONTRIBUTING.md](../CONTRIBUTING.md).

## File structure

```text
README.md                 the front page; CHANGELOG.md and CONTRIBUTING.md sit next to it
docs/                     every other page
tests/
├── stubs.py                    stand-ins for Home Assistant and aiohttp
└── test_integration.py         offline simulation of the integration
custom_components/cwfis/
├── LICENSE                     MIT, the same as the repository's
├── __init__.py                 setup and unload
├── manifest.json               metadata and version number
├── const.py                    URLs, layer names, option keys, defaults, lookup tables
├── helpers.py                  small pure functions (distance, bearing, data clean-up)
├── coordinator.py              fetches all data once per update and does the calculations
├── entity.py                   base entity: shared device, naming and availability
├── sensor.py                   all sensors
├── binary_sensor.py            Fire within alert radius, Fire upwind, Wildfire smoke
├── event.py                    Fire alert event entity
├── geo_location.py             map markers
├── image.py                    map images
├── config_flow.py              setup and the Configure form
├── translations/en.json        text for the Configure form and event types
└── brand/                      integration icon (icon.png, icon@2x.png)
```

## How an update works

1. Every 30 minutes, `CwfisCoordinator._async_update_data()` in `coordinator.py` runs.
2. It fetches this season's reported fires, plus any older fire still burning. **This is the only required request**: if it fails, the update fails and Home Assistant retries.
3. Every other source is optional and wrapped in `_optional()`: prescribed burns, last year's numbers (cached for the day) and the Open-Meteo forecast. A failure there sets only its own value to `None`, which shows as "unknown".
4. For Home and each watch zone, `_zone_data()` fetches hotspots, perimeters and fire danger around that zone. It also works out the distance and bearing to every active fire. The small module-level helpers `_perimeter_distances()` and `_danger_codes()` turn the raw perimeter and danger layers into numbers, and `_by_province()` builds the per-agency totals.
5. Everything is returned as one plain dict, `coordinator.data`. Every entity reads from it, so the servers are queried once per update no matter how many entities there are.

## The data dict

| Key | Contents |
|---|---|
| `zones` | `{zone id: {...}}` for `home` and each watch zone: `name`, `all` (fires with distance and bearing, nearest first), `nearby`, `nearest`, `hotspots`, `perimeter`, `danger`, `prescribed` |
| `fires` | `{fire id: fire}`, measured from Home. Used by map markers and the "fire out" check. |
| `provinces` | `{agency code: {"active": n, "area": ha}}` |
| `reported_today`, `active`, `out`, `total`, `area`, `fires_vs_last_year`, `area_vs_last_year`, `smoke_forecast` | National sensor values |
| `<key>_attrs` | Attributes for the national sensor with that key, picked up automatically |
| `smoke_pool` | Fires within the smoke radius of Home, used by the binary sensors |

## Entity naming and IDs

`entity.py` builds every name and unique ID:

- National and Home entities use the plain name, with unique ID `<entry id>_<key>`.
- Extra zones get `(<zone name>)` added to the name, with unique ID `<entry id>_<zone id>_<key>`.
- Provinces get `(<province>)` added to the name, with unique ID `<entry id>_<code>_<key>`.

Unique IDs must never change. `tests/test_integration.py` fails if they do.

Map markers (`geo_location`) have no unique ID, by Home Assistant's design. They're created and removed on every update, so they never leave orphaned entities behind.

## Data sources

All URLs and layer names are in `const.py`. The fire data follows Natural Resources Canada's [How to Access CWFIS Data Services](https://cwfis.cfs.nrcan.gc.ca/downloads/docs/en/how-tos/how-to-access-cwfis-data-services.pdf) guide:

- **CWFIF GeoServer** (`geoserver.cwfif.nrcan.gc.ca`): WFS 2.0 with CQL filters. `now() >= record_start AND now() <= record_end` selects each fire's current record.
- **Legacy CWFIS GeoServer** (`cwfis.cfs.nrcan.gc.ca`): WFS 1.0.0 for hotspots, perimeters and fire danger, using a lon/lat bounding box around each zone, and WMS 1.3.0 for the map images. NRCan plans to migrate these layers to CWFIF.
- **Open-Meteo** air-quality API: hourly `pm2_5` for Home, three days ahead.

To see what a layer contains, request `...?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAMES=<layer>&COUNT=1&OUTPUTFORMAT=application/json` in a browser.

## Testing

```bash
python3 tests/test_integration.py
```

This runs in plain Python with no Home Assistant install. It stands in for Home Assistant and the servers with small fakes, sets the integration up, reads every entity the way the frontend does, and checks the results across eight scenarios. When adding a scenario, give it fake server data and the values you expect.