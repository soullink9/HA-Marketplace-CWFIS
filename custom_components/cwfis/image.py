"""Map images: Canada-wide maps rendered by the CWFIS map server (show with a Picture entity card).

Each picture is downloaded only when someone views it, and at most once per data update.
If the map server fails, a single warning is logged and the entity retries after the next update.
"""

from __future__ import annotations

from datetime import timedelta
import logging
import re

import aiohttp
from homeassistant.components.image import ImageEntity
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import CANADA_BBOX_3978, CONF_MAP_IMAGES, LEGACY_WMS, MAPS
from .entity import CwfisEntity

_LOGGER = logging.getLogger(__name__)

# Drawn under / over the data layer for context (land, then province borders on top).
BASEMAP_UNDER = "public:basemap_land"
BASEMAP_OVER = "public:basemap_inside_bndry"


async def async_setup_entry(hass, entry, async_add_entities):
    """One image entity per map picked under Configure -> Map images."""
    async_add_entities(CwfisMap(hass, entry, key) for key in entry.options.get(CONF_MAP_IMAGES, []) if key in MAPS)


class CwfisMap(CwfisEntity, ImageEntity):
    """One rendered CWFIS map."""

    _attr_content_type = "image/png"

    def __init__(self, hass, entry, key: str):
        """Set up the entity; the picture itself is downloaded on first view."""
        name, self._layer = MAPS[key]
        CwfisEntity.__init__(self, entry, f"map_{key}", name, "mdi:map")
        ImageEntity.__init__(self, hass)
        self._attr_image_last_updated = dt_util.utcnow()
        self._image: bytes | None = None
        self._tried = False  # one download attempt per data update, so a broken layer isn't hammered
        self._warned = False  # warn once per outage, then stay quiet until it recovers

    @callback
    def _handle_coordinator_update(self):
        """New data arrived: mark the picture stale."""
        # It is re-rendered (downloaded again) the next time someone views it.
        self._image, self._tried, self._attr_image_last_updated = None, False, dt_util.utcnow()
        super()._handle_coordinator_update()

    def _data_layer(self) -> str:
        """The WMS layer to draw. Tomorrow's forecast layer is named by date, e.g. public:fdr20261013xf."""
        return self._layer or f"public:fdr{dt_util.now().date() + timedelta(days=1):%Y%m%d}xf"

    def _log(self, msg: str, *args):
        """Warning the first time a map fails, debug level while it keeps failing."""
        (_LOGGER.debug if self._warned else _LOGGER.warning)(msg, *args)

    async def _render(self, layers: str) -> bytes | None:
        """Ask the WMS server to draw `layers`; returns PNG bytes, or None (and logs why) on failure."""
        params = {
            "SERVICE": "WMS",
            "VERSION": "1.3.0",
            "REQUEST": "GetMap",
            "LAYERS": layers,
            "STYLES": "",
            "CRS": "EPSG:3978",
            "BBOX": CANADA_BBOX_3978,
            "WIDTH": 768,
            "HEIGHT": 646,
            "FORMAT": "image/png",
            "TRANSPARENT": "FALSE",
        }
        session = async_get_clientsession(self.hass)
        async with session.get(LEGACY_WMS, params=params, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            if resp.status == 200 and resp.content_type.startswith("image/"):
                return await resp.read()
            text = await resp.text()
        # GeoServer reports problems as XML <ServiceException> elements; log their text.
        errors = re.findall(r"<ServiceException(?:\s[^>]*)?>(.*?)</ServiceException>", text, re.S)
        self._log(
            "%s: CWFIS could not draw layers %s: %s",
            self.name,
            layers,
            " | ".join(" ".join(e.split()) for e in errors) or f"HTTP {resp.status} {text[:300]}",
        )
        return None

    async def async_image(self) -> bytes | None:
        """Return the picture, downloading it first if it's stale (called by HA when the image is viewed)."""
        if self._image is None and not self._tried:
            self._tried = True
            layer = self._data_layer()
            try:
                # Try with the basemap first; if that fails, draw the data layer on its own.
                self._image = await self._render(f"{BASEMAP_UNDER},{layer},{BASEMAP_OVER}") or await self._render(layer)
            except (aiohttp.ClientError, TimeoutError) as err:
                self._log("%s: CWFIS map request failed: %s", self.name, err)

            if self._image is None:
                self._warned = True
            elif self._warned:
                _LOGGER.info("%s: CWFIS map is drawing again", self.name)
                self._warned = False
        return self._image
