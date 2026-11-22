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
CONF_AQ_SCALE = "air_quality_scale"
CONF_DANGER_DISTANCE = "danger_distance"
CONF_WARNING_DISTANCE = "warning_distance"

DEFAULT_RADIUS = 250  # km
DEFAULT_SMOKE_RADIUS = 1000  # km
DEFAULT_PM25 = 35  # µg/m³ (US EPA 24-hour standard)
DEFAULT_MAP_FIRES = "all"
DEFAULT_AQ_SCALE = "auto"
DEFAULT_DANGER_DISTANCE = 25  # km
DEFAULT_WARNING_DISTANCE = 50  # km

# ---------------------------------------------------------------------------
# Tuning
# ---------------------------------------------------------------------------
UPWIND_SPREAD = 45  # a fire counts as "upwind" within ±45° of the direction the wind blows from
GROWTH_FACTOR = 1.25  # "Fire grew" alert: size up 25 % ...
GROWTH_MIN_HA = 10  # ... and by at least 10 ha since the last alert
MAX_LISTED_FIRES = 20  # cap on fires listed in one entity's attributes (keeps the database small)

# The Fire alert entity saves what it last saw in .storage/, so a restart doesn't lose the growth baseline or the
# changes made while Home Assistant was stopped. Bump the version when the saved layout changes.
ALERT_STORAGE_VERSION = 1
ALERT_STORAGE_KEY = "cwfis.{entry_id}.fire_alert"
# A saved baseline older than this is dropped (Home Assistant was off a long time): starting afresh beats a burst of
# alerts about old news.
ALERT_BASELINE_MAX_AGE = timedelta(hours=12)

# ---------------------------------------------------------------------------
# Limits on what the servers send. Anything outside them is treated as missing, so one bad value can't produce a
# nonsense state or stop an update.
# ---------------------------------------------------------------------------
MAX_FIRE_SIZE_HA = 10_000_000  # ha; Canada's largest recorded fires are around 1.5 million ha
MAX_PM25 = 5_000  # µg/m³; the worst wildfire smoke ever measured is well under this
FIRE_YEARS = (1900, 2200)  # a fire_year outside this range is treated as missing
MAX_TEXT = 100  # characters kept from a text field (fire ID, agency, stage, date)
MAX_GEOMETRY_DEPTH = 8  # GeoJSON nests at most 4 deep (MultiPolygon); deeper parts are skipped
MAX_PERIMETER_VERTICES = 500_000  # perimeter vertices measured per zone and update
MAX_MAP_BYTES = 10 * 1024 * 1024  # a rendered map is well under 1 MB

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

# Optional map images: key -> WMS data layer. Their names are in translations/en.json (entity.image.map_<key>, and
# selector.map_images for the Configure form).
# None means "tomorrow's fire danger forecast", whose layer name contains the date.
MAPS = {
    "fire_danger": "public:fdr",
    "fire_danger_tomorrow": None,
    "smoke": "public:currentSmoke",
    "hotspots": "public:hotspots_24h",
}

# Which fires get a map marker (Configure -> Fires on map); labels in translations/en.json under selector.map_fires.
MAP_FIRES_MODES = ["all", "nearby", "none"]

# ---------------------------------------------------------------------------
# Local impact (Smoke impact and Fire threat sensors)
# ---------------------------------------------------------------------------
# Air quality scales for Smoke impact (Configure -> Air quality scale); labels in translations/en.json under
# selector.air_quality_scale. "auto" picks Canada's AQHI when Home Assistant's country is Canada, else the US AQI.
AQ_SCALES = ["auto", "us_aqi", "ca_aqhi"]

# US EPA AQI for PM2.5 (2024 breakpoints): (level, highest PM2.5 in µg/m³, AQI low, AQI high, advice).
# The PM2.5 ranges are the ones between breakpoints; the last level is open-ended.
US_AQI = [
    ("good", 9.0, 0, 50, "Air quality is good. No action needed."),
    (
        "moderate",
        35.4,
        51,
        100,
        "Unusually sensitive people should consider less prolonged or heavy exertion outdoors.",
    ),
    (
        "unhealthy_sensitive",
        55.4,
        101,
        150,
        "People with heart or lung disease, older adults, children and pregnant people should cut back on time and "
        "heavy exertion outdoors. Consider closing windows and running an air purifier.",
    ),
    (
        "unhealthy",
        125.4,
        151,
        200,
        "Everyone should cut back on outdoor exertion, and sensitive groups should avoid it. Keep windows closed and "
        "run an air purifier or set the HVAC to recirculate.",
    ),
    (
        "very_unhealthy",
        225.4,
        201,
        300,
        "Everyone should avoid prolonged outdoor exertion, and sensitive groups should stay indoors. Keep windows "
        "closed, filter indoor air, and wear an N95 respirator outside.",
    ),
    (
        "hazardous",
        325.4,
        301,
        500,
        "Everyone should stay indoors with windows closed and filtered air. Wear an N95 respirator if you must go out.",
    ),
]

# Canada's AQHI-Plus (the PM2.5-only AQHI used for wildfire smoke): one point per 10 µg/m³ of 1-hour PM2.5,
# shown as "10+" above 100. Levels: (level, highest AQHI in it, advice).
CA_AQHI = [
    ("low_risk", 3, "Ideal air quality for outdoor activities."),
    (
        "moderate_risk",
        6,
        "At-risk people should consider reducing or rescheduling strenuous outdoor activities if they have symptoms. "
        "Others needn't change their plans unless they have symptoms.",
    ),
    (
        "high_risk",
        10,
        "At-risk people should reduce or reschedule strenuous outdoor activities, and children and older adults "
        "should take it easy. Everyone should cut back if they have symptoms. Keep windows closed and filter indoor "
        "air.",
    ),
    (
        "very_high_risk",
        None,
        "At-risk people, children and older adults should avoid strenuous activity outdoors, and everyone should "
        "reduce or reschedule it, especially with symptoms such as coughing or throat irritation. Stay indoors with "
        "filtered air.",
    ),
]

# Fire threat levels, lowest first, with the advice shown for each.
FIRE_THREAT = {
    "none": "No reported fire is close enough to matter here.",
    "watch": "There's fire activity in the region. Stay informed and review your evacuation plan.",
    "warning": "A fire is close. Be ready to leave: pack essentials, keep your vehicle fuelled and follow local "
    "authorities.",
    "danger": "A fire is very close. Follow local authorities' instructions and be ready to leave immediately.",
}
# Fire danger ratings that raise Fire threat to "watch" on their own.
WATCH_DANGER_LEVELS = {"Very high", "Extreme"}
