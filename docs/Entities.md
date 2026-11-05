# Entities

Everything belongs to one device called **CWFIS**. Entity IDs follow the entity names, for example `sensor.cwfis_active_fires`. Entities for extra zones and provinces have the zone or province name added, for example `sensor.cwfis_nearest_active_fire_cottage` or `sensor.cwfis_active_fires_quebec`.

Distance sensors show miles automatically if Home Assistant uses US units. Attributes are always in kilometres.

## National sensors

| Name | Unit | Notes |
|---|---|---|
| Reported today | fires | This season's fires first reported since local midnight. |
| Active fires | fires | Every fire not yet declared out. Attributes give counts by stage of control (`out_of_control`, `being_held`, `under_control`) and `by_province`. |
| Out fires | fires | This season's fires that have been declared out. |
| Total fires | fires | All fires this season. |
| Area burned | ha | This season's total. The `by_province_ha` attribute breaks it down by province. |
| Fires vs last year | % | Total fires compared with the same moment last year. Attributes give both numbers. |
| Area burned vs last year | % | Area burned compared with the same moment last year. Attributes give both numbers. |
| Smoke forecast PM2.5 (24h max) | µg/m³ | Highest forecast PM2.5 at Home over the next 24 hours. Attributes give `peak_time_24h`, `max_48h` and `peak_time_48h`. |

## Per-zone sensors

There's one set for Home and one for each extra watch zone.

| Name | Unit | Notes |
|---|---|---|
| Nearest active fire | km | Attributes give the fire ID, agency, stage, size, direction from the zone and last update. |
| Active fires nearby | fires | Fires inside the alert radius. Up to 20 of them are listed in the `fires` attribute. |
| Nearest fire perimeter | km | Distance to the closest satellite-estimated fire edge, searched out to roughly the alert radius. |
| Hotspots nearby (24h) | hotspots | Satellite heat detections inside the alert radius. These often show a new fire hours before it's reported. |
| Prescribed burns nearby | burns | Planned burns inside the alert radius. |
| Fire danger | text | Low, Moderate, High, Very high or Extreme. Only available for locations inside Canada. |

## Province sensors

These are optional. You get **Active fires** and **Area burned** for each agency picked under [Settings](Settings.md), for example `sensor.cwfis_active_fires_quebec`. Every agency is also listed in the national sensors' attributes, whether you pick it or not.

## Binary sensors

| Name | When it's on |
|---|---|
| Fire within alert radius | One per zone. On when an agency-reported active fire is inside that zone's alert radius. Attributes give `alert_radius_km`, `fires_in_radius`, `nearest_fire` and `nearest_distance_km`. |
| Fire upwind | Needs a wind sensor. On when a fire within the smoke radius lies within ±45° of the direction the wind is blowing from. The upwind fires are listed in the attributes. |
| Wildfire smoke | Needs a PM2.5 sensor. On when your measured PM2.5 is at or above the threshold **and** a likely fire source exists. That's an upwind fire if a wind sensor is set, or otherwise any fire within the smoke radius. Attributes give `pm25`, `threshold` and `likely_sources`. |

**Fire upwind** and **Wildfire smoke** update as soon as your wind or PM2.5 sensor changes, not just every 30 minutes.

## Fire alert event

`event.cwfis_fire_alert` fires one of these event types for any fire inside any zone's alert radius:

| Event type | When |
|---|---|
| New fire nearby | A fire appears inside the radius. |
| Stage changed | Its stage of control changes. The previous stage is included as `previous_stage`. |
| Fire grew | It has grown by 25 % and at least 10 ha since the last alert. `previous_size_ha` is included. |
| Fire out | It's declared out. |

Every event carries `zone`, `fire`, `agency`, `stage_of_control`, `size_ha`, `distance_km`, `direction` and `status_date`. An event entity's state is the time of its last event, so it shows **Unknown** until the first event fires. That's normal.

## Map markers

`geo_location.cwfis_<agency>_<fire>`, for example `geo_location.cwfis_bc_k71668`. There's one per active fire, created and removed automatically as fires start and go out. The **Fires on map** setting controls which fires get one. The state is the distance from Home, and the attributes give the agency, stage, size, direction and last update.

## Map images

These are optional and picked under [Settings](Settings.md). Show them with a **Picture entity** card.

| Name | Entity | Shows |
|---|---|---|
| Fire danger map | `image.cwfis_fire_danger_map` | Today's fire danger across Canada. |
| Fire danger forecast map (tomorrow) | `image.cwfis_fire_danger_forecast_map_tomorrow` | Tomorrow's forecast fire danger. |
| Smoke map | `image.cwfis_smoke_map` | Surface smoke (PM2.5). |
| Hotspots map (24h) | `image.cwfis_hotspots_map_24h` | Satellite hotspots from the last 24 hours. |