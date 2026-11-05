# Dashboards and Automations

Everything here uses Home Assistant's built-in cards and the automation editor. No custom cards or helpers are needed.

## Summary and map

A summary row plus a map of every active fire:

```yaml
type: vertical-stack
cards:
  - type: glance
    title: Canadian Wildland Fires
    entities:
      - sensor.cwfis_reported_today
      - sensor.cwfis_active_fires
      - sensor.cwfis_out_fires
      - sensor.cwfis_total_fires
      - sensor.cwfis_area_burned
  - type: map
    geo_location_sources:
      - cwfis
    default_zoom: 3
```

`geo_location_sources: [cwfis]` makes the map show only this integration's fire markers.

## Near me

```yaml
type: entities
title: Fires near me
entities:
  - binary_sensor.cwfis_fire_within_alert_radius
  - sensor.cwfis_nearest_active_fire
  - sensor.cwfis_active_fires_nearby
  - sensor.cwfis_hotspots_nearby_24h
  - sensor.cwfis_smoke_forecast_pm2_5_24h_max
```

## Map images and alert history

- **Map image:** add a **Picture entity** card and pick, for example, `image.cwfis_fire_danger_map`. Putting it in a grid next to the markers map works well.
- **Alert history:** add a **Logbook** card for `event.cwfis_fire_alert`.
- **Season trend:** add a **Statistics graph** card for **Active fires** or **Area burned**. These sensors keep long-term statistics, so the whole season's curve is available.

## Alert notifications

In **Settings → Automations & scenes → Create automation**:

1. **Trigger:** Entity → **State**, entity **CWFIS Fire alert**, with "from" and "to" left empty.
2. **Condition (optional):** Entity → **State** on the same entity, choosing the **Event type** attribute, if you only want some event types.
3. **Action:** your notify action, with a message such as:

```text
{{ trigger.to_state.attributes.event_type }} – {{ trigger.to_state.attributes.fire }},
{{ trigger.to_state.attributes.distance_km }} km {{ trigger.to_state.attributes.direction }} of {{ trigger.to_state.attributes.zone }}
```

## Other useful automations

- **Smoke tomorrow:** use a **Numeric state** trigger on **Smoke forecast PM2.5 (24h max)** going above 35, to get a reminder to close the windows or change the furnace filter.
- **Smoke now:** use a **State** trigger on **Wildfire smoke** turning **on**, to turn on an air purifier or close the windows.
- **Daily growth:** use a **Derivative** helper (created in the UI) on **Area burned** to see hectares burned per day.