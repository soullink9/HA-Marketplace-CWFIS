# Privacy

There are no accounts, API keys, analytics or tracking. Nothing is stored anywhere except your own Home Assistant. The integration makes these requests and no others:

| Sent to | What is sent | Why | How often |
|---|---|---|---|
| `geoserver.cwfif.nrcan.gc.ca` (Natural Resources Canada) | Search filters only (fire year and date), no location | Reported fires, prescribed burns and last year's numbers | Every 30 minutes. Last year's numbers are fetched once a day. |
| `cwfis.cfs.nrcan.gc.ca` (Natural Resources Canada) | A search box around Home and each watch zone (your radius, so roughly where you are) | Hotspots, perimeters and the fire danger at each zone | Every 30 minutes |
| `cwfis.cfs.nrcan.gc.ca` (Natural Resources Canada) | A fixed Canada-wide map request, no location | Map images, only if you've turned them on | When an image is viewed, at most once per update |
| `air-quality-api.open-meteo.com` (Open-Meteo) | Your Home latitude and longitude | The PM2.5 smoke forecast | Every 30 minutes |

Like any web request, these servers also see your public IP address. Your wind and PM2.5 sensors are read locally and never sent anywhere.

For how those services handle requests, see their own sites: [Open-Meteo](https://open-meteo.com/en/licence) and [Natural Resources Canada](https://natural-resources.canada.ca/).