"""OpenRouteService client (https://openrouteservice.org/dev/#/api-docs)."""
from django.conf import settings
import requests  # noqa: F401

ORS_BASE = 'https://api.openrouteservice.org'


def geocode(text):
    """Turn a place name into (lon, lat).

    TODO: call GET {ORS_BASE}/geocode/search?api_key=...&text=...
    Note ORS uses [lon, lat] order!
    """
    raise NotImplementedError


def get_routes(origin_lonlat, dest_lonlat, alternatives=3):
    """Return up to `alternatives` truck routes.

    TODO: POST {ORS_BASE}/v2/directions/driving-hgv/geojson
      headers: Authorization: settings.ORS_API_KEY
      body: {"coordinates": [origin, dest],
             "alternative_routes": {"target_count": 3, "share_factor": 0.6, "weight_factor": 1.6}}
    Return list of dicts: {geometry (list of [lon,lat]), distance_m, duration_s, segments}.
    Note: ORS limits alternative_routes to routes under ~100 km on the free plan - check docs
    and decide a fallback (e.g. different preference/avoid options).
    """
    raise NotImplementedError
