"""Routing + geocoding clients.

Primary: OpenRouteService (truck profile `driving-hgv`, https://openrouteservice.org/dev/#/api-docs).
Fallbacks, used only when ORS fails or is too slow:
  * directions -> public OSRM demo server (car profile, https://project-osrm.org/docs/v5.24.0/api/)
  * geocoding  -> Nominatim (https://nominatim.org/release-docs/latest/api/Search/)
"""
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from functools import lru_cache

from django.conf import settings
import requests

from . import steps as steps_mod
from .cache import TTLCache

ORS_BASE = 'https://api.openrouteservice.org'
OSRM_URL = 'https://router.project-osrm.org/route/v1/driving'
NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'
USER_AGENT = 'SpotterSafeRoute/1.0 (weather-aware truck routing demo)'

PROVIDER_ORS = 'ors-hgv'
PROVIDER_OSRM = 'osrm-car'

ORS_BUDGET_S = 7        # ORS gets this long to deliver; OSRM runs concurrently as a standby
OSRM_BUDGET_S = 12      # total time for OSRM main + detour calls
ROUTE_CACHE = TTLCache(ttl_s=600)   # same O/D within 10 min -> no routing calls

# One keep-alive session (connection reuse saves a TLS handshake per call) and
# two pools: OUTER runs the providers side by side, INNER runs each provider's
# parallel detour calls (separate pools so nested submits can't deadlock).
HTTP = requests.Session()
HTTP.headers['User-Agent'] = 'SpotterSafeRoute/1.0 (weather-aware truck routing demo)'
OUTER = ThreadPoolExecutor(max_workers=8, thread_name_prefix='route')
INNER = ThreadPoolExecutor(max_workers=16, thread_name_prefix='route-call')
GEOCODE_TIMEOUT_S = 8


class _Deadline:
    """Hands out per-call timeouts so a chain of HTTP calls respects one overall budget."""

    def __init__(self, seconds):
        self.end = time.monotonic() + seconds

    def left(self):
        return self.end - time.monotonic()

    def timeout(self, cap):
        left = self.left()
        if left < 1:
            raise requests.Timeout('time budget exhausted')
        return min(cap, left)


# ---------------------------------------------------------------- geocoding

@lru_cache(maxsize=256)
def geocode(text):
    """Place name -> (lon, lat). ORS first, Nominatim if ORS errors or times out."""
    try:
        return _geocode_ors(text)
    except ValueError:
        raise  # ORS answered "not found"; a second provider rarely knows better
    except (requests.RequestException, KeyError):
        return _geocode_nominatim(text)


def _geocode_ors(text):
    resp = HTTP.get(
        f'{ORS_BASE}/geocode/search',
        headers={'Authorization': settings.ORS_API_KEY},  # key in a header, never in the URL
        params={'text': text, 'size': 1},
        timeout=GEOCODE_TIMEOUT_S,
    )
    resp.raise_for_status()
    features = resp.json()['features']
    if not features:
        raise ValueError(f'Place not found: {text}')
    lon, lat = features[0]['geometry']['coordinates']  # ORS uses [lon, lat]
    return lon, lat


_nominatim_lock = threading.Lock()
_nominatim_last = [0.0]


def _geocode_nominatim(text):
    # Nominatim usage policy: identify yourself and make at most 1 request per second.
    with _nominatim_lock:
        wait = 1.0 - (time.monotonic() - _nominatim_last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            resp = HTTP.get(NOMINATIM_URL, headers={'User-Agent': USER_AGENT},
                                params={'q': text, 'format': 'json', 'limit': 1, 'countrycodes': 'us'},
                                timeout=GEOCODE_TIMEOUT_S)
        finally:
            _nominatim_last[0] = time.monotonic()
    resp.raise_for_status()
    hits = resp.json()
    if not hits:
        raise ValueError(f'Place not found: {text}')
    return float(hits[0]['lon']), float(hits[0]['lat'])


# ---------------------------------------------------------------- directions

def geocode_pair(a, b):
    """Geocode origin and destination at the same time."""
    fa, fb = OUTER.submit(geocode, a), OUTER.submit(geocode, b)
    return fa.result(), fb.result()


def get_routes(origin_lonlat, dest_lonlat, alternatives=3):
    """Return up to `alternatives` distinct routes, each tagged with its `provider`.

    ORS (truck) and OSRM (car) start at the same time. ORS is preferred: if it
    delivers all routes within ORS_BUDGET_S they are used and OSRM's answer is
    ignored. If ORS fails entirely, the OSRM routes (usually already in hand) are
    used as-is. Only if ORS returns some but not enough are OSRM routes added, with
    durations converted to truck time (see _to_truck_time), so ranking stays fair.
    """
    key = (round(origin_lonlat[0], 3), round(origin_lonlat[1], 3),
           round(dest_lonlat[0], 3), round(dest_lonlat[1], 3), alternatives)
    cached = ROUTE_CACHE.get(key)
    if cached:
        return cached

    ors_f = OUTER.submit(_ors_routes, origin_lonlat, dest_lonlat, alternatives, _Deadline(ORS_BUDGET_S))
    osrm_f = OUTER.submit(_osrm_routes, origin_lonlat, dest_lonlat, alternatives, _Deadline(OSRM_BUDGET_S))
    try:
        routes = ors_f.result(timeout=ORS_BUDGET_S + 0.5)
    except (FutureTimeout, requests.RequestException, KeyError, IndexError, ValueError):
        routes = []
    if len(routes) < alternatives:
        try:
            extra = osrm_f.result(timeout=OSRM_BUDGET_S + 0.5)
        except (FutureTimeout, requests.RequestException, KeyError, IndexError, ValueError):
            if not routes:
                raise requests.ConnectionError('ORS and OSRM routing both failed')
            extra = []
        if routes:
            # Mixed result: make OSRM car times comparable with the ORS truck route(s).
            extra = _to_truck_time(extra, routes)
        for r in extra:
            if len(routes) >= alternatives:
                break
            if _is_new(r, routes):
                routes.append(r)
    if routes:
        ROUTE_CACHE.set(key, routes)
    return routes


def _parallel(fn, args_list, deadline):
    """Run fn(*args) concurrently; return results that finished in time (errors -> None)."""
    futs = [INNER.submit(fn, *a) for a in args_list]
    out = []
    for f in futs:
        try:
            out.append(f.result(timeout=max(0.1, deadline.left())))
        except Exception:  # noqa: BLE001 - one failed detour must not sink the rest
            out.append(None)
    return out


HGV_MAX_AVG_MPH = 55  # a loaded truck rarely averages more than this over a long trip


def _to_truck_time(osrm_routes, ors_routes):
    """Scale OSRM car durations to truck speeds so mixed routes can be ranked fairly.

    factor = (ORS truck time / OSRM car time) for the fastest route of each provider,
    i.e. how much slower the truck profile is on this very trip. Durations are also
    floored at distance / HGV_MAX_AVG_MPH. The raw car time is kept in `car_duration_s`.
    """
    if not osrm_routes:
        return osrm_routes
    ors_fast = min(ors_routes, key=lambda r: r['duration_s'])
    osrm_fast = min(osrm_routes, key=lambda r: r['duration_s'])
    factor = max(1.0, ors_fast['duration_s'] / osrm_fast['duration_s']) if osrm_fast['duration_s'] else 1.0
    out = []
    for r in osrm_routes:
        floor_s = r['distance_m'] / 1609.34 / HGV_MAX_AVG_MPH * 3600
        out.append({**r, 'car_duration_s': r['duration_s'],
                    'duration_s': round(max(r['duration_s'] * factor, floor_s)),
                    'duration_adjusted': True})
    return out


def _ors_routes(origin, dest, alternatives, deadline):
    headers = {'Authorization': settings.ORS_API_KEY}
    url = f'{ORS_BASE}/v2/directions/driving-hgv/geojson'
    coords = [list(origin), list(dest)]
    base = {'instructions': True, 'units': 'm'}

    def post(body, cap):
        resp = HTTP.post(url, headers=headers, json={**base, **body}, timeout=deadline.timeout(cap))
        resp.raise_for_status()
        return [_from_ors(f) for f in resp.json()['features']]

    def via(point):
        return post({'coordinates': [coords[0], point, coords[1]], 'radiuses': [-1, -1, -1]}, 7)[0]

    # Main route + all four detours at once (each answers in well under a second).
    # ORS `alternative_routes` (short trips only, ~100 km limit) is slow (4-8 s), so it
    # runs in parallel and is only waited for if the detours didn't give enough routes.
    alt_f = None
    if _straight_km(origin, dest) < 80:
        alt_f = INNER.submit(post, {'coordinates': coords,
                                    'alternative_routes': {'target_count': alternatives,
                                                           'share_factor': 0.6, 'weight_factor': 1.6}}, 7)
    main_f = INNER.submit(post, {'coordinates': coords}, 7)
    detours = _parallel(via, [(p,) for p in _all_detours(origin, dest)], deadline)
    try:
        routes = main_f.result(timeout=max(0.1, deadline.left()))[:1]
    except Exception:  # noqa: BLE001
        if alt_f is None:
            raise
        routes = []
    routes = _dedupe(routes + [r for r in detours if r])
    if len(routes) < alternatives and alt_f is not None:
        routes = _dedupe(alt_f.result(timeout=max(0.1, deadline.left())) + routes)
    elif alt_f is not None:
        alt_f.cancel()
    if not routes:
        raise requests.ConnectionError('ORS returned no routes')
    return routes[:alternatives]


def _osrm_routes(origin, dest, alternatives, deadline):
    params = {'overview': 'full', 'geometries': 'geojson', 'steps': 'true'}

    def fetch(points, alts, cap):
        path = ';'.join(f'{lon:.6f},{lat:.6f}' for lon, lat in points)
        resp = HTTP.get(f'{OSRM_URL}/{path}', headers={'User-Agent': USER_AGENT},
                        params={**params, 'alternatives': 'true' if alts else 'false'},
                        timeout=deadline.timeout(cap))
        resp.raise_for_status()
        data = resp.json()
        if data.get('code') != 'Ok':
            raise ValueError(data.get('code', 'OSRM error'))
        return [_from_osrm(r) for r in data['routes']]

    # Main request (with alternatives) and both wide detours at once.
    main_f = INNER.submit(fetch, [origin, dest], True, 8)
    detours = _parallel(lambda p: fetch([origin, p, dest], False, 8)[0],
                        [(p,) for p in _detour_points(origin, dest)], deadline)
    routes = _dedupe(main_f.result(timeout=max(0.1, deadline.left())) + [r for r in detours if r])
    if len(routes) < alternatives and deadline.left() > 1.5:
        routes = _dedupe(routes + [r for r in _parallel(lambda p: fetch([origin, p, dest], False, 6)[0],
                                                         [(p,) for p in _detour_points(origin, dest, 0.06)],
                                                         deadline) if r])
    return routes[:alternatives]


def _dedupe(routes):
    out = []
    for r in routes:
        if _is_new(r, out):
            out.append(r)
    return out


# ---------------------------------------------------------------- helpers

def _is_new(route, routes, tol=0.01):
    """Distinct = length differs by more than 1% from every route we already have."""
    return all(abs(route['distance_m'] - x['distance_m']) > tol * x['distance_m'] for x in routes)


def _straight_km(a, b):
    """Rough straight-line distance in km between two [lon, lat] points."""
    (lon1, lat1), (lon2, lat2) = a, b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def _detour_points(origin, dest, offset=0.12):
    """Two points beside the straight-line midpoint, `offset` x trip length away."""
    (x1, y1), (x2, y2) = origin, dest
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    dx, dy = x2 - x1, y2 - y1          # direction of travel
    px, py = -dy * offset, dx * offset  # perpendicular to it
    return [[mx + px, my + py], [mx - px, my - py]]


def _all_detours(origin, dest):
    """Wide detours first, then tighter ones in case a wide point has no road nearby."""
    return _detour_points(origin, dest) + _detour_points(origin, dest, 0.06)


def _from_ors(feature):
    summary = feature['properties'].get('summary', {})
    return {
        'geometry': feature['geometry']['coordinates'],  # list of [lon, lat]
        'distance_m': summary.get('distance', 0),
        'duration_s': summary.get('duration', 0),
        'provider': PROVIDER_ORS,
        'steps': steps_mod.from_ors(feature['properties'].get('segments', []), feature['geometry']['coordinates']),
    }


def _from_osrm(route):
    return {
        'geometry': route['geometry']['coordinates'],  # GeoJSON [lon, lat]
        'distance_m': route['distance'],
        'duration_s': route['duration'],
        'provider': PROVIDER_OSRM,
        'steps': steps_mod.from_osrm(route.get('legs', []), route['geometry']['coordinates']),
    }
