"""Constants for the CWFIS integration.

Everything that might need changing when a data source moves or renames something lives here:
server URLs, layer names, option keys, defaults and lookup tables.
"""

from datetime import timedelta

DOMAIN = "cwfis"

# How often all data is refreshed. CWFIS itself updates hourly.
UPDATE_INTERVAL = timedelta(minutes=30)

# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------
# New CWFIF GeoServer (Natural Resources Canada): agency-reported and prescribed fires.
CWFIF_WFS = "https://geoserver.cwfif.nrcan.gc.ca/geoserver/wfs"
# Legacy CWFIS GeoServer: hotspots, perimeters, fire danger and rendered maps.
# NRCan plans to migrate these to CWFIF; if they move, only these URLs/layers need updating.
LEGACY_WFS = "https://cwfis.cfs.nrcan.gc.ca/geoserver/public/wfs"
LEGACY_WMS = "https://cwfis.cfs.nrcan.gc.ca/geoserver/public/wms"
# Open-Meteo air-quality API (ECMWF CAMS model): hourly PM2.5 forecast for home.
OPEN_METEO_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

LAYER_REPORTED = "public:cwfif_national_reportedfires"
LAYER_PRESCRIBED = "public:cwfif_national_prescribedfires"
LAYER_HOTSPOTS = "public:hotspots_last24hrs"
LAYER_PERIMETERS = "public:m3_polygons_current"
LAYER_DANGER = "public:fdr_current_shp"

# Fields requested for every reported fire (keeps responses small).
FIRE_FIELDS = "national_fire_id,agency_code,stage_of_control_status,fire_size,latitude,longitude,status_date,fire_year"

# Canada-wide bounding box in EPSG:3978 (Canada Atlas Lambert), taken from the CWFIS
# "How to Access CWFIS Data Services" guide. Used for the rendered map images.
CANADA_BBOX_3978 = "-2378164,-707617,3039835,3854382"

# ---------------------------------------------------------------------------
# Options (Settings -> Devices & services -> CWFIS -> Configure)
# The string values double as keys in translations/en.json.
# ---------------------------------------------------------------------------
CONF_RADIUS = "radius"
CONF_ZONES = "zones"
CONF_SMOKE_RADIUS = "smoke_radius"
CONF_WIND = "wind_entity"
CONF_PM25 = "pm25_entity"
CONF_PM25_THRESHOLD = "pm25_threshold"
CONF_PROVINCES = "provinces"
CONF_MAP_FIRES = "map_fires"
CONF_MAP_IMAGES = "map_images"

DEFAULT_RADIUS = 250  # km
DEFAULT_SMOKE_RADIUS = 1000  # km
DEFAULT_PM25 = 35  # µg/m³ (US EPA 24-hour standard)
DEFAULT_MAP_FIRES = "all"

# ---------------------------------------------------------------------------
# Tuning
# ---------------------------------------------------------------------------
UPWIND_SPREAD = 45  # a fire counts as "upwind" within ±45° of the direction the wind blows from
GROWTH_FACTOR = 1.25  # "Fire grew" alert: size up 25 % ...
GROWTH_MIN_HA = 10  # ... and by at least 10 ha since the last alert
MAX_LISTED_FIRES = 20  # cap on fires listed in one entity's attributes (keeps the database small)

# ---------------------------------------------------------------------------
# Lookup tables
# ---------------------------------------------------------------------------
# Stage-of-control codes used by Canadian fire agencies. "EX" (out) is handled separately.
STAGES = {"OC": "Out of control", "BH": "Being held", "UC": "Under control"}

# Fire danger classes; the list index equals the GRIDCODE in the CWFIS fire danger layer.
DANGER_LEVELS = ["Low", "Moderate", "High", "Very high", "Extreme"]

# Reporting agencies (provinces, territories and Parks Canada) by agency code.
PROVINCES = {
    "AB": "Alberta",
    "BC": "British Columbia",
    "MB": "Manitoba",
    "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador",
    "NS": "Nova Scotia",
    "NT": "Northwest Territories",
    "NU": "Nunavut",
    "ON": "Ontario",
    "PC": "Parks Canada",
    "PE": "Prince Edward Island",
    "QC": "Quebec",
    "SK": "Saskatchewan",
    "YT": "Yukon",
}

# Optional map images: key -> (entity name, WMS data layer).
# None means "tomorrow's fire danger forecast", whose layer name contains the date.
MAPS = {
    "fire_danger": ("Fire danger map", "public:fdr"),
    "fire_danger_tomorrow": ("Fire danger forecast map (tomorrow)", None),
    "smoke": ("Smoke map", "public:currentSmoke"),
    "hotspots": ("Hotspots map (24h)", "public:hotspots_24h"),
}
