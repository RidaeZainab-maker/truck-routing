"""Open-Meteo forecast helpers (no API key): https://open-meteo.com/en/docs"""
import math
import time
from datetime import datetime, timedelta, timezone

import requests
from concurrent.futures import ThreadPoolExecutor

from .cache import TTLCache

OPEN_METEO_URL = 'https://api.open-meteo.com/v1/forecast'
EARTH_RADIUS_MI = 3958.8
HTTP = requests.Session()
POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix='weather')
# Forecasts change hourly: cache per ~1 km cell for 15 min. Repeat plans and
# overlapping routes (shared start/end, same interstate) reuse the same data.
FORECAST_CACHE = TTLCache(ttl_s=900, max_items=5000)


def haversine_miles(lon1, lat1, lon2, lat2):
    """Straight-line distance in miles between two points on Earth."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(math.sqrt(a))


def sample_checkpoints(geometry, duration_s, departure, interval_miles=25):
    """Walk the route polyline and drop a checkpoint every `interval_miles` (10/25/50).

    geometry: list of [lon, lat] from ORS. departure: timezone-aware datetime.
    Returns list of {lat, lon, mile, eta (datetime)}. Always includes start and end.
    """
    if departure.tzinfo is None:
        departure = departure.replace(tzinfo=timezone.utc)

    # Total length first, so ETA can be spread evenly over the drive.
    total = sum(haversine_miles(*geometry[i], *geometry[i + 1]) for i in range(len(geometry) - 1))
    total = total or 1e-9

    def eta_at(mile):
        return departure + timedelta(seconds=duration_s * (mile / total))

    lon0, lat0 = geometry[0]
    checkpoints = [{'lat': lat0, 'lon': lon0, 'mile': 0.0, 'eta': departure}]
    travelled, next_mark = 0.0, interval_miles

    for i in range(len(geometry) - 1):
        (lon_a, lat_a), (lon_b, lat_b) = geometry[i], geometry[i + 1]
        step = haversine_miles(lon_a, lat_a, lon_b, lat_b)
        # A long straight segment can pass several marks; place each one on the line.
        while step > 0 and travelled + step >= next_mark:
            f = (next_mark - travelled) / step
            lon, lat = lon_a + f * (lon_b - lon_a), lat_a + f * (lat_b - lat_a)
            checkpoints.append({'lat': lat, 'lon': lon, 'mile': round(next_mark, 1), 'eta': eta_at(next_mark)})
            next_mark += interval_miles
        travelled += step

    lon_end, lat_end = geometry[-1]
    if total - checkpoints[-1]['mile'] > 1:  # don't duplicate a mark sitting on the finish
        checkpoints.append({'lat': lat_end, 'lon': lon_end, 'mile': round(total, 1),
                            'eta': departure + timedelta(seconds=duration_s)})
    return checkpoints


HOURLY = 'wind_speed_10m,wind_gusts_10m,precipitation,rain,snowfall,temperature_2m'


def _fetch(lats, lons, forecast_days=3):
    """One Open-Meteo call for many points (it accepts comma-separated lists)."""
    params = {
        'latitude': ','.join(f'{x:.4f}' for x in lats),
        'longitude': ','.join(f'{x:.4f}' for x in lons),
        'hourly': HOURLY,
        'wind_speed_unit': 'mph',
        'precipitation_unit': 'inch',
        'temperature_unit': 'fahrenheit',
        'timezone': 'UTC',
        'forecast_days': forecast_days,  # forecast starts at 00:00 UTC today
    }
    # Retry once on rate limits / server hiccups, which the free API sometimes returns.
    for attempt in range(2):
        resp = HTTP.get(OPEN_METEO_URL, timeout=15, params=params)
        if resp.status_code not in (429, 500, 502, 503, 504):
            break
        time.sleep(2)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else [data]


def _pick_hour(forecast, eta):
    """Take the hourly values closest to `eta`."""
    hourly = forecast['hourly']
    eta_utc = eta.astimezone(timezone.utc).replace(tzinfo=None)
    times = [datetime.fromisoformat(t) for t in hourly['time']]
    i = min(range(len(times)), key=lambda k: abs(times[k] - eta_utc))
    # With precipitation_unit=inch Open-Meteo already returns snowfall in inches
    # (hourly_units.snowfall == 'inch'), so no cm -> inch conversion is needed.
    snow_in = hourly['snowfall'][i] or 0
    return {
        'wind_mph': hourly['wind_speed_10m'][i] or 0,
        'gust_mph': hourly['wind_gusts_10m'][i] or 0,
        'rain_in_hr': hourly['rain'][i] or 0,
        'snow_in_hr': round(snow_in, 3),
        'temp_f': hourly['temperature_2m'][i],
        'forecast_time': hourly['time'][i] + 'Z',
    }


SLIDER_HOURS = 48  # the UI can shift departure 0-48 h without another request


def _series(forecast, eta, hours=SLIDER_HOURS):
    """Hourly values from the hour nearest `eta` to `eta + hours`, for the client-side slider.

    Index k is the weather this checkpoint sees if the truck leaves k hours later.
    """
    hourly = forecast['hourly']
    eta_utc = eta.astimezone(timezone.utc).replace(tzinfo=None)
    times = [datetime.fromisoformat(t) for t in hourly['time']]
    i = min(range(len(times)), key=lambda k: abs(times[k] - eta_utc))
    window = slice(i, i + hours + 1)
    col = lambda key, nd=2: [round(v or 0, nd) for v in hourly[key][window]]
    return {
        'start': hourly['time'][i] + 'Z',
        'wind_mph': col('wind_speed_10m', 1), 'gust_mph': col('wind_gusts_10m', 1),
        'rain_in_hr': col('rain', 3), 'snow_in_hr': col('snowfall', 3),
        'temp_f': col('temperature_2m', 1),
    }


def get_forecast_at(lat, lon, eta):
    """Return weather at (lat, lon) for the hour nearest `eta`.

    Returns {wind_mph, gust_mph, rain_in_hr, snow_in_hr, temp_f}.
    """
    return _pick_hour(_fetch([lat], [lon])[0], eta)


def _days_needed(checkpoints, extra_hours=0):
    """How many forecast days (from 00:00 UTC today) cover the latest ETA.

    A fixed 3 days was too short: leaving +48 h later on a 15 h drive needs ~4 days,
    and late checkpoints were silently given the last available hour.
    Open-Meteo allows up to 16 days.
    """
    today = datetime.now(timezone.utc).date()
    last = (max(c['eta'] for c in checkpoints) + timedelta(hours=extra_hours)).astimezone(timezone.utc).date()
    return min(16, max(3, (last - today).days + 1))


def _cell(c):
    return (round(c['lat'], 2), round(c['lon'], 2))


def get_forecasts(checkpoints, batch_size=50, with_series=False):
    """Weather for every checkpoint.

    Unique ~1 km cells only, cached for 15 min, missing cells fetched in parallel
    multi-location batches (Open-Meteo accepts comma-separated coordinate lists).
    with_series=True also attaches `series` (next 48 h) so the UI slider needs no new request.
    """
    if not checkpoints:
        return []
    days = _days_needed(checkpoints, SLIDER_HOURS if with_series else 0)
    hour = datetime.now(timezone.utc).strftime('%Y%m%d%H')
    keys = [(*_cell(c), days, hour) for c in checkpoints]
    have = {k: FORECAST_CACHE.get(k) for k in dict.fromkeys(keys)}
    missing = [k for k, v in have.items() if v is None]
    batches = [missing[s:s + batch_size] for s in range(0, len(missing), batch_size)]
    for batch, result in zip(batches, POOL.map(
            lambda b: _fetch([k[0] for k in b], [k[1] for k in b], days), batches)):
        for k, f in zip(batch, result):
            have[k] = FORECAST_CACHE.set(k, f)
    out = []
    for k, c in zip(keys, checkpoints):
        w = _pick_hour(have[k], c['eta'])
        if with_series:
            w['series'] = _series(have[k], c['eta'])
        out.append(w)
    return out
