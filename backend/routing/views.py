from concurrent.futures import ThreadPoolExecutor
from datetime import timezone

import requests
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .serializers import RouteRequestSerializer
from .services import ors, weather, risk, recommend as rec

ROUTE_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix='route-weather')


@api_view(['GET'])
def health(request):
    return Response({'status': 'ok'})


@api_view(['POST'])
def routes(request):
    """Plan weather-aware routes.

    Body: {origin, destination, departure (ISO datetime), load_weight_lb, interval_miles?}
    """
    # 1. Validate input
    ser = RouteRequestSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    data = ser.validated_data
    departure = data['departure']
    if departure.tzinfo is None:
        departure = departure.replace(tzinfo=timezone.utc)
    interval = data['interval_miles']

    try:
        # 2. Geocode
        origin, dest = ors.geocode_pair(data['origin'], data['destination'])
        # 3. Up to 3 truck routes
        raw_routes = ors.get_routes(origin, dest)
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except requests.RequestException as e:
        # Don't echo the raw exception: it can contain request URLs.
        return Response({'error': f'Routing services (ORS + OSRM fallback) failed: {type(e).__name__}'},
                        status=status.HTTP_502_BAD_GATEWAY)

    # 4. Checkpoints + ETAs for every route, then all routes' forecasts in parallel.
    all_cps = [weather.sample_checkpoints(r['geometry'], r['duration_s'], departure, interval)
               for r in raw_routes]
    try:
        all_forecasts = list(ROUTE_POOL.map(lambda cps: weather.get_forecasts(cps, with_series=True), all_cps))
    except requests.RequestException as e:
        return Response({'error': f'Weather service (Open-Meteo) failed: {type(e).__name__}'},
                        status=status.HTTP_502_BAD_GATEWAY)

    out = []
    for i, (r, cps, forecasts) in enumerate(zip(raw_routes, all_cps, all_forecasts)):
        # 5. Classify each checkpoint
        checkpoints = []
        for c, w in zip(cps, forecasts):
            series = w.pop('series', None)
            checkpoints.append({
                'lat': round(c['lat'], 5), 'lon': round(c['lon'], 5), 'mile': c['mile'],
                'eta': c['eta'].isoformat(), 'weather': w, 'series': series,
                'risk': risk.classify_checkpoint(w, data['load_weight_lb']),
            })
        out.append({
            'index': i,
            'provider': r.get('provider', ors.PROVIDER_ORS),
            'distance_mi': round(r['distance_m'] / 1609.34, 1),
            'duration_s': r['duration_s'],
            'duration_adjusted': r.get('duration_adjusted', False),  # OSRM car time scaled to truck time
            'car_duration_s': r.get('car_duration_s'),
            'duration_h': round(r['duration_s'] / 3600, 1),
            # Leaflet wants [lat, lon]; 5 decimals (~1 m) keeps the payload small.
            'geometry': [[round(lat, 5), round(lon, 5)] for lon, lat in r['geometry']],
            'steps': r.get('steps', []),
            'checkpoints': checkpoints,
            'summary': rec.summarize_route(checkpoints, interval),
        })

    # 6. Pick best, 7. return everything
    best = rec.recommend(out)
    providers = sorted({r['provider'] for r in out})
    fallback = ors.PROVIDER_OSRM in providers
    return Response({
        'origin': {'query': data['origin'], 'lon': origin[0], 'lat': origin[1]},
        'destination': {'query': data['destination'], 'lon': dest[0], 'lat': dest[1]},
        'departure': departure.isoformat(),
        'load_weight_lb': data['load_weight_lb'],
        'interval_miles': interval,
        'routes': out,
        'recommended_route_index': best,
        'providers': providers,
        'fallback_used': fallback,
        'notice': _notice(out),
    })


def _notice(routes):
    """Tell the user when (and how much) the OSRM car fallback was used."""
    n_osrm = sum(r['provider'] == ors.PROVIDER_OSRM for r in routes)
    n_ors = len(routes) - n_osrm
    if not n_osrm:
        return ''
    if not n_ors:
        return 'Truck routing service slow — showing car-road routes from OSRM'
    s = lambda n: '' if n == 1 else 's'
    return (f'{n_ors} truck route{s(n_ors)} from ORS, {n_osrm} car-road alternative{s(n_osrm)} '
            f'from OSRM (times adjusted to truck speeds)')
