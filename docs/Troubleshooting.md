# Troubleshooting

## Turning on debug logging

Go to **Settings → Devices & services → Canadian Wildland Fire Information System → ⋮ → Enable debug logging**. Wait for an update or two (they happen every 30 minutes, or sooner if you reload the integration), then check **Settings → System → Logs**. Turning debug logging off downloads the full log.

## Common questions

**A sensor shows "Unknown".**
That optional data source didn't answer during the last update. Everything else keeps working, and it tries again every 30 minutes. Debug logging shows which request failed.

**Every sensor is unavailable.**
The main CWFIS fire server couldn't be reached. Home Assistant keeps retrying automatically. Check that Home Assistant can reach `geoserver.cwfif.nrcan.gc.ca`.

**Fire danger is always unknown.**
CWFIS only rates locations inside Canada. Add a Canadian watch zone to use it.

**Fire alert shows "Unknown".**
That's normal. An event entity's state is the time of its last event, so it stays Unknown until the first alert fires.

**Fire within alert radius is on, but the fire is far away.**
It means a fire is inside *your* alert radius. Check the `alert_radius_km` and `nearest_distance_km` attributes, and lower the radius under [Settings](Settings.md) if needed.

**Fire upwind is on a lot.**
A large smoke radius almost always contains a fire somewhere to the west or northwest. Reduce the smoke radius, or rely on **Wildfire smoke**, which also needs your PM2.5 sensor to read high.

**The icon doesn't show.**
Built-in icons need Home Assistant 2026.3 or newer. After updating, hard-refresh the browser (Ctrl+Shift+R), because browsers cache integration icons.

## Known issues

- **The smoke map image is blank.** As of October 2026 the CWFIS server returns "Internal error" for its smoke layer. The integration logs one warning and recovers automatically when CWFIS fixes it. The PM2.5 forecast and **Wildfire smoke** sensors are unaffected.
- **The legacy CWFIS server will be retired.** Hotspots, perimeters, fire danger and map images come from CWFIS's older server, which Natural Resources Canada plans to migrate. If those start failing for good, only the URLs and layer names in `const.py` should need updating. See [Development](Development.md).