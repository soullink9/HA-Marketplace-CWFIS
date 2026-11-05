# How the Numbers Work

## Where the data comes from

| Data | Source |
|---|---|
| Reported fires (summary, provinces, proximity, alerts, map markers) | CWFIF GeoServer, layer `cwfif_national_reportedfires`, from Natural Resources Canada. Fires are reported by the provinces, the territories and Parks Canada. |
| Prescribed burns | CWFIF GeoServer, layer `cwfif_national_prescribedfires` |
| Satellite hotspots (last 24 h) | CWFIS GeoServer, layer `hotspots_last24hrs` |
| Fire perimeter estimates | CWFIS GeoServer, layer `m3_polygons_current` |
| Fire danger | CWFIS GeoServer, layer `fdr_current_shp` |
| Map images | CWFIS map server (WMS): fire danger, the next day's forecast, smoke and hotspots |
| Smoke forecast | Open-Meteo air-quality API, using the ECMWF CAMS model |

All data refreshes every **30 minutes**, while CWFIS itself updates hourly. Map images are downloaded only when someone views them.

## Season numbers

- **Reported today, Out, Total, Area burned** and the province areas count fires from the **current calendar year**, the same as the CWFIS homepage.
- **Active fires** also includes fires from an earlier season that are still burning, so fires that carry over New Year keep being tracked and don't trigger false "Fire out" alerts at midnight. For a while after New Year, Active + Out can therefore be more than Total.
- **Reported today** counts fires that weren't in the data at local midnight.
- **Fires / Area burned vs last year** compare this season with last season's totals as they stood at this exact moment a year ago. On Feb 29 it compares with Feb 28. This is fetched once a day. Early in the season, small numbers can produce large percentages.
- If an agency sends two records for the same fire, only the newest one is counted. Records with missing coordinates are still counted, but they can't be placed on a map or measured.

## Distances

- Distances are straight lines from each zone to a fire's **reported location**.
- **Nearest fire perimeter** measures to the closest corner of the satellite-estimated perimeter shape. For large fires this can be closer than the reported location, and it may read slightly long because it measures to corners rather than edges.
- **Hotspots** and **prescribed burns** are counted inside the alert radius.
- **Fire danger** is the class of the CWFIS fire danger area covering the zone itself. Outside Canada it's unknown.

## Alerts

- An alert fires for each zone a fire is near. A fire inside both Home's radius and a cottage zone's radius produces two events, one per zone.
- **Fire grew** needs both +25 % and +10 ha since the last alert. The size at the last alert is remembered, so slow, steady growth eventually triggers it too.
- **Fire out** fires when a nearby fire leaves the active list. Leaving the radius list because a zone was removed doesn't count.
- After a restart, fires already nearby are not announced again.

## Smoke and wind

- **Smoke forecast** is *total* PM2.5 from all sources, not only smoke. Ordinary days usually sit around 5–15 µg/m³, while real smoke events go well above 35.
- **Fire upwind** compares each fire's compass bearing from Home with your wind direction (where the wind is blowing *from*). A fire within ±45° of it counts as upwind. Your station measures ground-level wind, but smoke often travels at altitude on different winds, so treat it as a heads-up rather than a forecast.
- **Wildfire smoke** needs evidence on both counts: your own sensor must read smoky air, and there must be a likely fire source. That keeps a smoggy day or a neighbour's barbecue from setting it off on its own.