"""Open-Meteo forecast helpers (no API key): https://open-meteo.com/en/docs"""
import requests  # noqa: F401

OPEN_METEO_URL = 'https://api.open-meteo.com/v1/forecast'


def sample_checkpoints(geometry, duration_s, departure, interval_miles=25):
    """Walk the route polyline and drop a checkpoint every `interval_miles` (10/25/50).

    Returns list of {lat, lon, mile, eta (datetime)}.
    TODO: haversine distance between points; accumulate miles; ETA =
    departure + duration_s * (mile / total_miles) (or use ORS segment timing).
    """
    raise NotImplementedError


def get_forecast_at(lat, lon, eta):
    """Return weather at (lat, lon) for the hour nearest `eta`.

    TODO: GET OPEN_METEO_URL with hourly=wind_speed_10m,wind_gusts_10m,precipitation,
    rain,snowfall,temperature_2m & wind_speed_unit=mph & precipitation_unit=inch & timezone=UTC.
    Pick the hourly index closest to eta. Consider batching (Open-Meteo accepts
    comma-separated lat/lon lists) and caching.
    Returns {wind_mph, gust_mph, rain_in_hr, snow_in_hr, temp_f}.
    """
    raise NotImplementedError
