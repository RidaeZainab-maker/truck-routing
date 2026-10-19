"""Offline tests for the pure logic (no network: ORS and Open-Meteo are mocked)."""
from datetime import datetime, timedelta, timezone
from unittest import mock

from django.test import SimpleTestCase
from rest_framework.test import APIClient

import threading
from concurrent.futures import ThreadPoolExecutor

import requests

from .services import ors, recommend, risk, steps, weather


def lvl(wind=0, rain=0, snow=0, load=0):
    return risk.classify_checkpoint({'wind_mph': wind, 'rain_in_hr': rain, 'snow_in_hr': snow}, load)['level']


class RiskTableTests(SimpleTestCase):
    def test_wind_bands(self):
        for wind, expected in [(0, 'Low'), (24.9, 'Low'), (25, 'Moderate'), (34.9, 'Moderate'),
                               (35, 'High'), (45, 'Severe'), (54.9, 'Severe'), (55, 'No Travel')]:
            self.assertEqual(lvl(wind=wind), expected, wind)

    def test_rain_bands(self):
        for rain, expected in [(0.09, 'Low'), (0.10, 'Moderate'), (0.25, 'High'), (0.50, 'Severe'),
                               (1.00, 'Severe'), (1.01, 'No Travel')]:
            self.assertEqual(lvl(rain=rain), expected, rain)

    def test_snow_bands(self):
        for snow, expected in [(0.4, 'Low'), (0.5, 'Moderate'), (1.0, 'High'), (2.0, 'Severe'),
                               (3.0, 'Severe'), (3.1, 'No Travel')]:
            self.assertEqual(lvl(snow=snow), expected, snow)

    def test_load_rules(self):
        self.assertEqual(lvl(wind=50, load=30000), 'Severe')      # not over 30k
        self.assertEqual(lvl(wind=50, load=30001), 'No Travel')
        self.assertEqual(lvl(wind=40, load=40000), 'High')        # not over 40k
        self.assertEqual(lvl(wind=40, load=40001), 'Severe')

    def test_worst_condition_wins(self):
        self.assertEqual(lvl(wind=26, rain=0.6), 'Severe')


class RecommendTests(SimpleTestCase):
    def route(self, levels, duration):
        cps = [{'mile': 25 * k, 'risk': {'level': l, 'score': risk.SCORES[l]}} for k, l in enumerate(levels)]
        return {'summary': recommend.summarize_route(cps, 25), 'duration_s': duration}

    def test_safety_beats_speed(self):
        routes = [self.route(['Low', 'Severe'], 100), self.route(['Low', 'High'], 200)]
        self.assertEqual(recommend.recommend(routes), 1)

    def test_no_travel_is_worst(self):
        routes = [self.route(['Low', 'No Travel'], 100), self.route(['Severe', 'Severe', 'Severe'], 200)]
        self.assertEqual(recommend.recommend(routes), 1)

    def test_tie_goes_to_fastest(self):
        routes = [self.route(['Low'], 300), self.route(['Low'], 200)]
        self.assertEqual(recommend.recommend(routes), 1)

    def test_breakdown_sums_to_route_length(self):
        # 966.6 mi route, checkpoints every 25 mi plus a short last stretch.
        miles = [float(m) for m in range(0, 966, 25)] + [966.6]
        levels = ['Low', 'Moderate', 'High', 'Severe', 'No Travel']
        cps = [{'mile': m, 'risk': {'level': levels[k % 5], 'score': risk.SCORES[levels[k % 5]]}}
               for k, m in enumerate(miles)]
        s = recommend.summarize_route(cps, 25)
        parts = sum(s[k] for k in ('low_miles', 'moderate_miles', 'high_miles', 'severe_miles', 'no_travel_miles'))
        self.assertAlmostEqual(parts, s['total_miles'], delta=0.1)
        self.assertAlmostEqual(s['total_miles'], 966.6, delta=0.1)

    def test_avg_score_scale(self):
        cps = [{'mile': m, 'risk': {'level': 'Low', 'score': risk.SCORES['Low']}} for m in (0, 10)]
        self.assertEqual(recommend.summarize_route(cps)['avg_score'], 1)  # all Low = 1, not 0

    def test_mixed_tie_prefers_truck_route(self):
        a = dict(self.route(['Low', 'Low'], 1000), provider='osrm-car')
        b = dict(self.route(['Low', 'Low'], 1000), provider='ors-hgv')
        self.assertEqual(recommend.recommend([a, b]), 1)

    def test_adjusted_car_route_no_longer_wins_on_time(self):
        # Unadjusted, the 17.3 h car route would beat the 21.6 h truck route; adjusted it doesn't.
        truck = [{'duration_s': 21.6 * 3600, 'distance_m': 1555000, 'provider': 'ors-hgv'}]
        car = ors._to_truck_time([{'duration_s': 17.3 * 3600, 'distance_m': 1489000, 'provider': 'osrm-car'}], truck)
        routes = [dict(self.route(['Low', 'Low'], truck[0]['duration_s']), provider='ors-hgv'),
                  dict(self.route(['Low', 'Low'], car[0]['duration_s']), provider='osrm-car')]
        self.assertEqual(recommend.recommend(routes), 0)

    def test_empty(self):
        self.assertIsNone(recommend.recommend([]))


class WeatherTests(SimpleTestCase):
    def test_checkpoints_every_interval(self):
        # ~69 mi per degree of latitude: 1 degree straight north, 1 hour drive.
        geom = [[-97.0, 32.0], [-97.0, 33.0]]
        dep = datetime(2026, 1, 1, tzinfo=timezone.utc)
        cps = weather.sample_checkpoints(geom, 3600, dep, 25)
        self.assertEqual([c['mile'] for c in cps], [0.0, 25.0, 50.0, 69.1])
        self.assertEqual(cps[-1]['eta'], dep + timedelta(hours=1))

    def test_snowfall_already_in_inches(self):
        fc = {'hourly': {'time': ['2026-01-01T00:00'], 'wind_speed_10m': [10], 'wind_gusts_10m': [20],
                         'rain': [0], 'snowfall': [1.2], 'temperature_2m': [30]}}
        w = weather._pick_hour(fc, datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(w['snow_in_hr'], 1.2)

    def test_forecast_days_cover_late_etas(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(weather._days_needed([{'eta': now}]), 3)
        self.assertGreaterEqual(weather._days_needed([{'eta': now + timedelta(hours=70)}]), 4)
        self.assertEqual(weather._days_needed([{'eta': now + timedelta(days=40)}]), 16)


class RoutesEndpointTests(SimpleTestCase):
    def test_pipeline_with_mocked_services(self):
        geom = [[-96.8, 32.78], [-97.33, 32.75]]
        fake_route = {'geometry': geom, 'distance_m': 50000, 'duration_s': 3000, 'segments': []}
        calm = {'wind_mph': 5, 'gust_mph': 10, 'rain_in_hr': 0, 'snow_in_hr': 0, 'temp_f': 70}
        windy = dict(calm, wind_mph=40)
        with mock.patch('routing.services.ors.geocode', side_effect=[(-96.8, 32.78), (-97.33, 32.75)]), \
             mock.patch('routing.services.ors.get_routes', return_value=[fake_route, dict(fake_route, duration_s=2500)]), \
             mock.patch('routing.services.weather.get_forecasts',
                        side_effect=lambda cps, **kw: [windy if (cps[-1]['eta'] - cps[0]['eta']).total_seconds() < 2900 else calm] * len(cps)):
            # route 0 gets calm weather, route 1 gets 40 mph wind
            resp = APIClient().post('/api/routes', {
                'origin': 'Dallas, TX', 'destination': 'Fort Worth, TX',
                'departure': '2026-10-18T12:00:00Z', 'load_weight_lb': 45000, 'interval_miles': 25,
            }, format='json')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body['routes']), 2)
        self.assertEqual(body['routes'][1]['checkpoints'][0]['risk']['level'], 'Severe')  # 40 mph + >40k lb
        self.assertEqual(body['recommended_route_index'], 0)  # calm route wins although slower
        self.assertEqual(body['routes'][0]['geometry'][0], [32.78, -96.8])  # [lat, lon] for Leaflet

    def test_bad_interval_rejected(self):
        resp = APIClient().post('/api/routes', {'origin': 'a', 'destination': 'b',
                                                'departure': '2026-10-18T12:00:00Z',
                                                'load_weight_lb': 1, 'interval_miles': 7}, format='json')
        self.assertEqual(resp.status_code, 400)


def _resp(status=200, payload=None):
    r = mock.Mock(status_code=status, ok=status < 400)
    r.json.return_value = payload
    r.raise_for_status.side_effect = None if status < 400 else requests.HTTPError(str(status))
    return r


def _osrm(*distances):
    return {'code': 'Ok', 'routes': [{'geometry': {'coordinates': [[-96.8, 32.8], [-87.6, 41.9]]},
                                      'distance': d, 'duration': d / 25} for d in distances]}


DAL, CHI = (-96.8, 32.78), (-87.63, 41.88)


def _osrm_route(d, dur=None):
    return {'geometry': {'coordinates': [[-96.8, 32.8], [-87.6, 41.9]]}, 'distance': d,
            'duration': dur if dur is not None else d / 25, 'legs': []}


def _ors_feat(d, dur=None):
    return {'geometry': {'coordinates': [[-96.8, 32.8], [-87.6, 41.9]]},
            'properties': {'summary': {'distance': d, 'duration': dur if dur is not None else d / 20}}}


def fake_osrm(main, via=(), fail=False):
    """requests.get stand-in for OSRM: main O/D call vs via-point (detour) calls, by URL."""
    vias, lock = iter(via), threading.Lock()

    def get(url, **kw):
        if fail:
            raise requests.ConnectionError('osrm down')
        if url.count(';') == 1:
            return _resp(200, {'code': 'Ok', 'routes': main})
        with lock:  # detours are fetched from several threads at once
            nxt = next(vias, None)
        if nxt is None:
            raise requests.ReadTimeout('no more detours')
        return _resp(200, {'code': 'Ok', 'routes': [nxt]})
    return get


def fake_ors(main=None, via=(), fail=False):
    vias, lock = iter(via), threading.Lock()

    def post(url, json=None, **kw):
        if fail:
            raise requests.ReadTimeout('ors slow')
        if len(json['coordinates']) == 2:
            if main is None:
                raise requests.ReadTimeout('ors slow')
            return _resp(200, {'features': main})
        with lock:
            nxt = next(vias, None)
        if nxt is None:
            raise requests.ReadTimeout('ors slow')
        return _resp(200, {'features': [nxt]})
    return post


class RoutingFallbackTests(SimpleTestCase):
    """ORS failures must fall back to OSRM / Nominatim (all HTTP mocked; providers run concurrently)."""

    def setUp(self):
        ors.geocode.cache_clear()
        ors.ROUTE_CACHE.clear()

    def run_routes(self, post, get, o=DAL, d=CHI):
        # Fresh pools per call, drained before the mocks are removed, so a provider still
        # running in the background can't leak calls into the next test.
        outer, inner = ThreadPoolExecutor(8), ThreadPoolExecutor(16)
        with mock.patch('routing.services.ors.HTTP.post', side_effect=post) as p, \
             mock.patch('routing.services.ors.HTTP.get', side_effect=get) as g, \
             mock.patch.object(ors, 'OUTER', outer), mock.patch.object(ors, 'INNER', inner):
            routes = ors.get_routes(o, d)
            outer.shutdown(wait=True)
            inner.shutdown(wait=True)
        return routes, p, g

    def test_ors_timeout_falls_back_to_osrm_with_detours(self):
        routes, _, g = self.run_routes(fake_ors(fail=True),
                                       fake_osrm([_osrm_route(1500000), _osrm_route(1560000)], [_osrm_route(1640000)]))
        self.assertEqual(len(routes), 3)
        self.assertTrue(all(r['provider'] == 'osrm-car' for r in routes))
        self.assertFalse(any(r.get('duration_adjusted') for r in routes))  # all-car: raw times kept
        self.assertIn('User-Agent', g.call_args_list[0].kwargs['headers'])

    def test_duplicate_detours_skipped(self):
        routes, _, _ = self.run_routes(
            fake_ors(fail=True),
            fake_osrm([_osrm_route(1500000)], [_osrm_route(1500100), _osrm_route(1500100),
                                               _osrm_route(1600000), _osrm_route(1700000)]))
        self.assertEqual(sorted(r['distance_m'] for r in routes)[0], 1500000)
        self.assertEqual(len({round(r['distance_m'], -3) for r in routes}), len(routes))  # all distinct

    def test_ors_success_wins_even_if_osrm_answers(self):
        routes, _, _ = self.run_routes(fake_ors([_ors_feat(50000), _ors_feat(56000), _ors_feat(61000)]),
                                       fake_osrm([_osrm_route(49000)]), (-96.8, 32.78), (-97.33, 32.75))
        self.assertEqual([r['provider'] for r in routes], ['ors-hgv'] * 3)

    def test_long_trip_ors_main_plus_parallel_detours(self):
        routes, p, _ = self.run_routes(fake_ors([_ors_feat(1500000)], [_ors_feat(1600000), _ors_feat(1700000)]),
                                       fake_osrm([_osrm_route(1400000)]))
        self.assertEqual([r['provider'] for r in routes], ['ors-hgv'] * 3)
        self.assertGreaterEqual(p.call_count, 3)

    def test_slow_ors_detours_topped_up_by_osrm(self):
        routes, _, _ = self.run_routes(fake_ors([_ors_feat(1450000)]),
                                       fake_osrm([_osrm_route(1500000), _osrm_route(1600000)]))
        self.assertEqual([r['provider'] for r in routes], ['ors-hgv', 'osrm-car', 'osrm-car'])

    def test_mixed_osrm_times_scaled_to_truck(self):
        # ORS truck route: 21.6 h. OSRM fastest car route 17.3 h -> factor 21.6/17.3.
        routes, _, _ = self.run_routes(
            fake_ors([_ors_feat(1555000, 21.6 * 3600)]),
            fake_osrm([_osrm_route(1489000, 17.3 * 3600), _osrm_route(1592000, 19.1 * 3600)]))
        factor = 21.6 / 17.3
        self.assertAlmostEqual(routes[1]['duration_s'], 17.3 * 3600 * factor, delta=2)
        self.assertEqual(routes[1]['car_duration_s'], 17.3 * 3600)
        self.assertTrue(routes[1]['duration_adjusted'])
        self.assertGreaterEqual(routes[1]['duration_s'], routes[0]['duration_s'])  # car no longer "faster"

    def test_slow_ors_does_not_block_past_budget(self):
        import time as _t

        def slow_post(url, json=None, timeout=None, **kw):
            _t.sleep(min(timeout, 1.5))
            raise requests.ReadTimeout('slow')
        with mock.patch.object(ors, 'ORS_BUDGET_S', 1.0):
            t0 = _t.monotonic()
            routes, _, _ = self.run_routes(slow_post, fake_osrm([_osrm_route(1e6), _osrm_route(1.1e6), _osrm_route(1.2e6)]))
            self.assertLess(_t.monotonic() - t0, 2.5)
        self.assertEqual({r['provider'] for r in routes}, {'osrm-car'})

    def test_route_cache_hit_skips_network(self):
        post, get = fake_ors(fail=True), fake_osrm([_osrm_route(1e6), _osrm_route(1.1e6), _osrm_route(1.2e6)])
        self.run_routes(post, get)
        _, p, g = self.run_routes(post, get)
        p.assert_not_called()
        g.assert_not_called()

    def test_truck_time_floor(self):
        ors_r = [{'duration_s': 100, 'distance_m': 1000}]
        osrm_r = [{'duration_s': 3600, 'distance_m': 160934, 'provider': 'osrm-car'}]  # 100 mi in 1 h
        out = ors._to_truck_time(osrm_r, ors_r)
        self.assertAlmostEqual(out[0]['duration_s'], 100 / 55 * 3600, delta=2)  # floored at 55 mph

    def test_geocode_falls_back_to_nominatim(self):
        def get(url, **kw):  # dispatch by URL (other tests' background threads may also call)
            if 'openrouteservice' in url:
                raise requests.ConnectTimeout('ors down')
            return _resp(200, [{'lon': '-96.79', 'lat': '32.77'}])
        with mock.patch('routing.services.ors.HTTP.get', side_effect=get) as m:
            self.assertEqual(ors.geocode('Dallas, TX'), (-96.79, 32.77))
        nominatim = [c for c in m.call_args_list if 'nominatim' in c.args[0]][0]
        self.assertIn('nominatim', nominatim.args[0])
        self.assertIn('SpotterSafeRoute', nominatim.kwargs['headers']['User-Agent'])

    @mock.patch('routing.services.ors.HTTP.post', side_effect=requests.ReadTimeout('slow'))
    @mock.patch('routing.services.ors.HTTP.get', side_effect=requests.ConnectionError('down'))
    def test_both_providers_down_returns_502(self, get, post):
        resp = APIClient().post('/api/routes', {'origin': 'A', 'destination': 'B',
                                                'departure': '2026-10-18T12:00:00Z',
                                                'load_weight_lb': 1, 'interval_miles': 25}, format='json')
        self.assertEqual(resp.status_code, 502)

    def test_endpoint_flags_fallback(self):
        r = {'geometry': [[-96.8, 32.78], [-97.33, 32.75]], 'distance_m': 50000, 'duration_s': 3000,
             'provider': 'osrm-car'}
        calm = {'wind_mph': 5, 'gust_mph': 10, 'rain_in_hr': 0, 'snow_in_hr': 0, 'temp_f': 70,
                'series': {'start': 'x', 'wind_mph': [5]}}
        with mock.patch('routing.services.ors.geocode', side_effect=[DAL, CHI]), \
             mock.patch('routing.services.ors.get_routes', return_value=[r]), \
             mock.patch('routing.services.weather.get_forecasts', side_effect=lambda cps, **kw: [dict(calm) for _ in cps]):
            body = APIClient().post('/api/routes', {'origin': 'A', 'destination': 'B',
                                                    'departure': '2026-10-18T12:00:00Z',
                                                    'load_weight_lb': 1}, format='json').json()
        self.assertTrue(body['fallback_used'])
        self.assertEqual(body['notice'], 'Truck routing service slow — showing car-road routes from OSRM')
        self.assertEqual(body['routes'][0]['provider'], 'osrm-car')
        self.assertEqual(body['routes'][0]['checkpoints'][0]['series']['wind_mph'], [5])
        self.assertNotIn('series', body['routes'][0]['checkpoints'][0]['weather'])


class SeriesTests(SimpleTestCase):
    def test_series_starts_at_eta_hour(self):
        times = [f'2026-01-01T{h:02d}:00' for h in range(24)]
        fc = {'hourly': {'time': times, 'wind_speed_10m': list(range(24)), 'wind_gusts_10m': [0] * 24,
                         'rain': [0] * 24, 'snowfall': [None] * 24, 'temperature_2m': [50] * 24}}
        s = weather._series(fc, datetime(2026, 1, 1, 5, 10, tzinfo=timezone.utc), hours=3)
        self.assertEqual(s['start'], '2026-01-01T05:00Z')
        self.assertEqual(s['wind_mph'], [5, 6, 7, 8])
        self.assertEqual(s['snow_in_hr'], [0, 0, 0, 0])


class NoticeTests(SimpleTestCase):
    def test_notice_variants(self):
        from .views import _notice
        mk = lambda *p: [{'provider': x} for x in p]
        self.assertEqual(_notice(mk('ors-hgv', 'ors-hgv', 'ors-hgv')), '')
        self.assertIn('showing car-road routes', _notice(mk('osrm-car', 'osrm-car')))
        self.assertEqual(_notice(mk('ors-hgv', 'osrm-car', 'osrm-car')),
                         '1 truck route from ORS, 2 car-road alternatives from OSRM (times adjusted to truck speeds)')


class StepTests(SimpleTestCase):
    """Turn-by-turn normalisation for both providers."""

    def test_ors_steps(self):
        geom = [[-96.8, 32.78], [-96.81, 32.79], [-96.9, 32.9], [-97.0, 33.0]]
        segments = [
            {'steps': [{'type': 11, 'instruction': 'Head north on Main St', 'name': 'Main St',
                        'distance': 1609.34, 'duration': 60, 'way_points': [0, 1]},
                       {'type': 10, 'instruction': 'Arrive at waypoint', 'name': '-',
                        'distance': 0, 'duration': 0, 'way_points': [1, 1]}]},
            {'steps': [{'type': 11, 'instruction': 'Head north', 'name': '-', 'distance': 0, 'duration': 0,
                        'way_points': [1, 1]},
                       {'type': 1, 'instruction': 'Turn right onto I-35 N', 'name': 'I-35 N',
                        'distance': 3218.68, 'duration': 120, 'way_points': [1, 3]},
                       {'type': 10, 'instruction': 'Arrive at your destination', 'name': '-',
                        'distance': 0, 'duration': 0, 'way_points': [3, 3]}]}]
        out = steps.from_ors(segments, geom)
        self.assertEqual([s['maneuver_type'] for s in out], ['depart', 'right', 'arrive'])  # via arrive/depart dropped
        self.assertEqual(out[1]['instruction'], 'Turn right onto I-35 N')
        self.assertEqual(out[1]['distance_mi'], 2.0)
        self.assertEqual(out[1]['location'], [32.79, -96.81])  # [lat, lon]
        self.assertEqual(out[1]['span'], [1, 3])
        self.assertEqual(out[2]['road_name'], '')

    def test_osrm_instruction_text(self):
        mk = lambda typ, mod='', **kw: {'maneuver': {'type': typ, 'modifier': mod, 'location': [0, 0], **kw.pop('m', {})}, **kw}
        self.assertEqual(steps.osrm_instruction(mk('turn', 'left', ref='I 35;US 77', name='')), 'Turn left onto I-35')
        self.assertEqual(steps.osrm_instruction(mk('off ramp', 'slight right', destinations='I 35 N: Waco')), 'Take the exit toward Waco')
        self.assertEqual(steps.osrm_instruction(mk('new name', 'straight', ref='US 75', name='')), 'Continue onto US-75')
        self.assertEqual(steps.osrm_instruction(mk('fork', 'slight left', name='Elm St')), 'Keep left at the fork onto Elm St')
        self.assertEqual(steps.osrm_instruction(mk('roundabout', 'right', name='Oak Ave', m={'exit': 2})),
                         'At the roundabout, take exit 2 onto Oak Ave')
        self.assertEqual(steps.osrm_instruction(mk('turn', 'uturn', name='')), 'Make a U-turn')
        self.assertEqual(steps.osrm_maneuver(mk('off ramp', 'right')), 'exit-right')
        self.assertEqual(steps.osrm_maneuver(mk('off ramp', 'slight left')), 'exit-left')
        self.assertEqual(steps.osrm_maneuver(mk('off ramp', '')), 'exit-right')
        self.assertEqual(steps.osrm_maneuver(mk('merge', 'slight left')), 'merge-left')
        self.assertEqual(steps.osrm_maneuver(mk('on ramp', 'straight')), 'merge')
        self.assertEqual(steps.osrm_maneuver(mk('fork', 'slight right')), 'keep-right')
        self.assertEqual(steps.osrm_maneuver(mk('turn', 'sharp left')), 'sharp-left')

    def test_osrm_steps_multi_leg(self):
        geom = [[0, 0], [0.5, 0], [1, 0], [1, 1]]
        st = lambda typ, loc, d, mod='', name='A': {'maneuver': {'type': typ, 'modifier': mod, 'location': loc},
                                                    'distance': d, 'duration': d / 20, 'name': name}
        legs = [{'steps': [st('depart', [0, 0], 1000), st('arrive', [1, 0], 0)]},
                {'steps': [st('depart', [1, 0], 0), st('turn', [1, 0], 2000, 'left', 'B'), st('arrive', [1, 1], 0)]}]
        out = steps.from_osrm(legs, geom)
        self.assertEqual([s['maneuver_type'] for s in out], ['depart', 'left', 'arrive'])
        self.assertEqual(out[1]['instruction'], 'Turn left onto B')
        self.assertEqual(out[1]['span'], [2, 3])
        self.assertEqual(out[0]['span'], [0, 2])


class ManeuverConsistencyTests(SimpleTestCase):
    """The icon is drawn from maneuver_type, the banner shows the text: they must agree."""

    def test_ors_type_codes(self):
        # https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/instruction-types
        self.assertEqual([steps.ORS_TYPES[i] for i in (0, 1, 2, 3, 4, 5, 6, 12, 13)],
                         ['left', 'right', 'sharp-left', 'sharp-right', 'slight-left', 'slight-right',
                          'straight', 'keep-left', 'keep-right'])

    def test_reconcile_text_wins(self):
        r = steps.reconcile
        self.assertEqual(r('Turn right onto West Magnolia Avenue', 'left'), 'right')
        self.assertEqual(r('Turn left onto Hemphill Street', 'right'), 'left')
        self.assertEqual(r('Keep right', 'keep-left'), 'keep-right')
        self.assertEqual(r('Turn sharp left onto South Freeway', 'sharp-right'), 'sharp-left')
        self.assertEqual(r('At the end of the road, turn left onto Elm St', 'right'), 'left')
        self.assertEqual(r('Merge left onto I-35', 'merge'), 'merge-left')
        self.assertEqual(r('Turn slight right', 'straight'), 'slight-right')

    def test_reconcile_leaves_consistent_steps(self):
        r = steps.reconcile
        self.assertEqual(r('Turn right onto Left Fork Road', 'right'), 'right')  # road name is not the verb
        self.assertEqual(r('Continue onto Right Lane Rd', 'straight'), 'straight')
        self.assertEqual(r('Arrive at your destination, on the left', 'arrive'), 'arrive')
        self.assertEqual(r('Make a U-turn', 'uturn'), 'uturn')
        self.assertEqual(r('Take the exit toward Waco', 'exit-right'), 'exit-right')
        self.assertEqual(r('', 'left'), 'left')

    def test_from_ors_fixes_contradicting_type(self):
        geom = [[0, 0], [0, 1], [1, 1]]
        seg = [{'steps': [{'type': 0, 'instruction': 'Turn right onto West Magnolia Avenue', 'name': 'W Magnolia',
                           'distance': 10, 'duration': 1, 'way_points': [1, 2]}]}]
        self.assertEqual(steps.from_ors(seg, geom)[0]['maneuver_type'], 'right')

    def test_osrm_text_and_type_agree(self):
        mk = lambda typ, mod: {'maneuver': {'type': typ, 'modifier': mod, 'location': [0, 0]}, 'name': 'X'}
        for typ in ('turn', 'end of road', 'fork', 'continue', 'off ramp', 'merge'):
            for mod in ('left', 'right', 'slight left', 'slight right', 'sharp left', 'sharp right'):
                s = mk(typ, mod)
                text, mtype = steps.osrm_instruction(s).lower(), steps.reconcile(steps.osrm_instruction(s), steps.osrm_maneuver(s))
                side = 'left' if 'left' in mod else 'right'
                self.assertIn(side, mtype, (typ, mod, text, mtype))
                self.assertNotIn('right' if side == 'left' else 'left', text.split(' onto ')[0], (typ, mod, text))


class OpenMeteoRetryTests(SimpleTestCase):
    def _resp(self, code, retry_after=None):
        r = mock.Mock(status_code=code, headers={'Retry-After': retry_after} if retry_after else {})
        r.json.return_value = [{'hourly': {}}]
        if code >= 400:
            r.raise_for_status.side_effect = requests.HTTPError(response=r)
        else:
            r.raise_for_status.return_value = None
        return r

    def test_backoff(self):
        self.assertEqual(weather._backoff(0), 1.5)
        self.assertEqual(weather._backoff(1), 3.0)
        self.assertEqual(weather._backoff(0, '2'), 2.0)
        self.assertEqual(weather._backoff(0, '120'), weather.MAX_BACKOFF_S)  # capped
        self.assertEqual(weather._backoff(1, 'Wed, 21 Oct 2026 07:28:00 GMT'), 3.0)

    def test_retries_429_then_succeeds(self):
        calls = [self._resp(429, '1'), self._resp(429), self._resp(200)]
        with mock.patch.object(weather.HTTP, 'get', side_effect=calls) as get, \
                mock.patch.object(weather.time, 'sleep') as sleep:
            self.assertEqual(weather._fetch([1], [2]), [{'hourly': {}}])
        self.assertEqual(get.call_count, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [1.0, 3.0])  # Retry-After, then backoff

    def test_retries_timeout_then_succeeds(self):
        with mock.patch.object(weather.HTTP, 'get', side_effect=[requests.ReadTimeout(), self._resp(200)]), \
                mock.patch.object(weather.time, 'sleep'):
            self.assertEqual(weather._fetch([1], [2]), [{'hourly': {}}])

    def test_gives_up_with_http_error(self):
        with mock.patch.object(weather.HTTP, 'get', return_value=self._resp(429)) as get, \
                mock.patch.object(weather.time, 'sleep'):
            with self.assertRaises(requests.HTTPError):
                weather._fetch([1], [2])
        self.assertEqual(get.call_count, weather.FETCH_ATTEMPTS)

    def test_no_retry_on_client_error(self):
        with mock.patch.object(weather.HTTP, 'get', return_value=self._resp(400)) as get, \
                mock.patch.object(weather.time, 'sleep') as sleep:
            with self.assertRaises(requests.HTTPError):
                weather._fetch([1], [2])
        self.assertEqual(get.call_count, 1)
        sleep.assert_not_called()

    def test_view_reports_status_code(self):
        r = self._resp(429)
        with mock.patch('routing.services.ors.geocode_pair', return_value=((-97, 32), (-96, 33))), \
                mock.patch('routing.services.ors.get_routes', return_value=[{
                    'geometry': [[-97, 32], [-96, 33]], 'distance_m': 1000, 'duration_s': 60, 'steps': []}]), \
                mock.patch('routing.services.weather.get_forecasts', side_effect=requests.HTTPError(response=r)):
            res = APIClient().post('/api/routes', {'origin': 'A', 'destination': 'B',
                                                   'departure': '2026-10-19T09:00:00Z', 'load_weight_lb': 1000},
                                   format='json')
        self.assertEqual(res.status_code, 502)
        self.assertIn('HTTPError 429', res.json()['error'])
        self.assertIn('rate limited', res.json()['error'])
