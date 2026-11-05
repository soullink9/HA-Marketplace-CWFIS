# Settings

Open **Settings → Devices & services → Canadian Wildland Fire Information System → Configure**. When you save, the integration reloads straight away, so new zones, provinces and maps appear immediately.

| Option | Default | What it does |
|---|---|---|
| Alert radius | 250 km | Agency-reported fires within this distance of a zone count as "nearby" and raise [Fire alert](Entities.md#fire-alert-event) events. Hotspots, perimeters and prescribed burns are also counted within this distance. |
| Extra watch zones | none | Any of your Home Assistant zones. Each one gets its own set of proximity sensors. Home is always included. |
| Smoke radius | 1000 km | How far away a fire can be and still count as a possible smoke source for **Fire upwind** and **Wildfire smoke**. |
| Wind direction sensor | none | A sensor reporting the direction the wind blows **from**, in degrees. Most weather stations report it this way. Enables **Fire upwind**. |
| PM2.5 sensor | none | An air-quality PM2.5 sensor, for example from Home Assistant's built-in AirNow or PurpleAir integrations. Enables **Wildfire smoke**. |
| PM2.5 smoke threshold | 35 µg/m³ | A PM2.5 reading at or above this counts as smoky. 35 µg/m³ is the US EPA 24-hour standard. |
| Province sensors | none | Adds **Active fires** and **Area burned** sensors for each agency you pick: provinces, territories and Parks Canada. |
| Fires on map | All active fires | Which fires get a map marker: all of them, only those inside an alert radius, or none. |
| Map images | none | Canada-wide map pictures to add as image entities. See [Entities](Entities.md#map-images). |

## Choosing your radii

Pick distances that suit where you live. As a guide, here are distances from southern New England:

| Place | Distance |
|---|---|
| Montreal | ~440 km |
| Quebec City | ~560 km |
| New Brunswick / Nova Scotia | ~710 km |
| Central Quebec (Chibougamau) | ~930 km |
| Northeastern Ontario (Timmins) | ~1,070 km |
| James Bay, Quebec | ~1,410 km |
| Manitoba (Winnipeg) | ~2,170 km |
| Alberta / British Columbia | 3,300 km and up |

- **Alert radius:** set this to the distance at which a fire would genuinely matter to you. If it's set too wide, you'll get alerts about the routine fires that burn in the far north all summer. From southern New England, about **600 km** covers southern Quebec and the Maritimes.
- **Smoke radius:** much of the smoke that has reached the US Northeast came from central and northern Quebec, often more than 1,000 km away. About **1,500 km** covers Quebec's main fire belt, northern Ontario and the Maritimes. You can set it wider, but **Fire upwind** will then be on far more often, because prevailing winds come from the west and northwest. **Wildfire smoke** still turns on only when your own PM2.5 sensor actually reads high.

If you live in Canada, a much smaller alert radius (for example 50–150 km) and a smoke radius of a few hundred kilometres usually make more sense.