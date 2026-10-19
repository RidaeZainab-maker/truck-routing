# Spotter SafeRoute: Weather-Aware Truck Routing

**Live app:** https://spotter-saferoute.vercel.app

A React + Django web app that helps a truck driver pick the **safest** route. Enter an origin, a destination, a departure time and the load weight. The app finds up to 3 truck routes, checks the forecast at checkpoints along each route **for the hour the truck will actually be there**, rates each checkpoint from **Low** to **No Travel** using the brief's wind / rain / snow and load rules, and recommends the best route.

## Features

- **3 truck routes** from OpenRouteService (`driving-hgv`, the heavy-goods-vehicle profile), with an OSRM fallback when ORS is slow (see [Routing and fallback](#routing-and-fallback)).
- **Checkpoints every 10, 25 or 50 miles**, each with an ETA, an hourly forecast (wind, gusts, rain, snow, temperature) from Open-Meteo, and a risk level.
- **Recommendation:** least dangerous route first, travel time as the tie-break. Shown as a "★ RECOMMENDED" badge.
- **Route cards:** drive time, distance, average risk (1–5 scale), arrival time, and a miles-per-risk-level bar. The bar's miles add up exactly to the route length.
- **Map** (Leaflet, keyless Esri tiles): **Dark / Streets / Satellite** basemaps, a glowing selected route, dashed alternatives you can click, A/B pins, checkpoint markers with hover tooltips and popups (mile, ETA, weather), a legend and a scale bar.
- **Weather heatmap with a 0–48 h slider:** risk-colored glow along the corridor. Its width and brightness follow wind/rain/snow intensity. The slider shifts the departure time 0–48 h, and **▶ Play** animates it. The API sends 48 h of hourly forecast per checkpoint, so the browser re-scores risk, heatmap, ETAs and the recommendation instantly. Moving the slider makes no new request.
- **Directions tab:** turn-by-turn steps with arrows, distance, mile, ETA and nearby risk. Clicking a step flies the map to street level, highlights that stretch and opens a popup. "⤢ Back to full route" zooms back out.
- **Navigation mode** (**▶ GO**): a Google-Maps-style simulated drive on the Streets basemap. It shows a turn banner ("In 0.3 mi … Then …"), a bottom bar (time left, miles to go, ETA, risk at the next checkpoint) and warning toasts before Moderate-or-worse checkpoints. Speeds are **1× / 10× / 60× / 300×**. It also has pause/resume, voice guidance (Web Speech API) with mute, and an optional **📍 GPS** toggle that follows the device location.

## Tech stack

| Layer    | Tech |
|----------|------|
| Frontend | React 19, Vite, Leaflet / react-leaflet, plain CSS, Vitest |
| Backend  | Python 3.12, Django, Django REST Framework, requests |
| APIs     | [OpenRouteService](https://openrouteservice.org/) (truck routes + geocoding, free key), [Open-Meteo](https://open-meteo.com/) (forecast, no key). Fallbacks: [OSRM demo server](https://project-osrm.org/) (routes), [Nominatim](https://nominatim.org/) (geocoding) |
| Hosting  | Vercel (static frontend + Python serverless function); Dockerfile as an alternative |

## How it works

```
React (side panel + Leaflet map)                     frontend/src/App.jsx
   │  POST /api/routes {origin, destination, departure, load_weight_lb, interval_miles}
   ▼
Django REST view                                     backend/routing/views.py
   1. validate input                                 routing/serializers.py
   2. geocode origin + destination (in parallel)     services/ors.py   (ORS, Nominatim fallback)
   3. up to 3 truck routes + turn-by-turn steps      services/ors.py, services/steps.py
   4. checkpoints every N miles + ETA per route      services/weather.py (haversine walk)
      forecasts for all routes, in parallel          services/weather.py -> Open-Meteo
   5. classify each checkpoint                       services/risk.py
   6. summarise each route + pick the best           services/recommend.py
   7. JSON: routes, [lat, lon] geometry, steps, checkpoints (+48 h series), recommendation
```

Endpoints: `GET /api/health` → `{"status": "ok"}` and `POST /api/routes` (example below).

### Risk rules

Each checkpoint gets a level for wind, rain and snow. The **worst** of the three is the checkpoint's level.

| Condition    | Low    | Moderate    | High        | Severe      | No Travel |
|--------------|--------|-------------|-------------|-------------|-----------|
| Wind (mph)   | < 25   | 25 – 34     | 35 – 44     | 45 – 54     | ≥ 55      |
| Rain (in/hr) | < 0.10 | 0.10 – 0.25 | 0.25 – 0.50 | 0.50 – 1.00 | > 1.00    |
| Snow (in/hr) | < 0.5  | 0.5 – 1.0   | 1.0 – 2.0   | 2.0 – 3.0   | > 3.0     |

Lower edges are inclusive (25 mph = Moderate). Rain and snow are No Travel only when strictly above 1.00 / 3.0.

Load rules: ≥ 55 mph wind → No Travel for any load. 45–54 mph with > 30,000 lb → No Travel. 35–44 mph with > 40,000 lb → at least Severe.

Scores (1–5): Low 1, Moderate 2, High 3, Severe 4, No Travel 5.

### Recommendation

For each route, every stretch between two checkpoints counts as the worse of its two ends, measured with the real mile markers, so the level miles sum to the route length. Routes are ranked by:

1. fewest **No Travel** miles (added before the brief's list, because these are worse than Severe)
2. fewest **Severe** miles
3. fewest **High** miles
4. lowest **average risk score**
5. shortest **drive time**
6. on an exact tie, an ORS truck route before an OSRM car route

The same rules are mirrored in `frontend/src/risk.js` so the slider can re-score without a request. The backend tests cover the Python side.

### Routing and fallback

The free ORS `driving-hgv` endpoint can be slow on long trips, so `services/ors.py`:

- **Alternatives:** ORS `alternative_routes` only works for short trips (~100 km). Long trips get alternatives from the main route plus `driving-hgv` routes through via-points left and right of the midpoint. All requests are sent at once, and near-duplicates (< 1% length difference) are dropped.
- **Time budget, not retries:** ORS gets a **7 s budget**. The public **OSRM** server (car profile) runs **in parallel** as a standby.
  - If ORS delivers 3 routes, OSRM's answer is ignored.
  - If ORS fails completely, all routes come from OSRM and keep their car times.
  - If ORS returns 1–2 routes, OSRM tops up the list, and OSRM durations are **converted to truck time**: × (ORS truck time / OSRM car time for the fastest route of each), floored at distance ÷ 55 mph. Such routes show "truck-adj." on the card and keep the raw `car_duration_s`.
  - The UI shows a notice whenever OSRM routes are used.
- **Geocoding:** ORS first. **Nominatim** is used if ORS errors or times out (identifying User-Agent, ≤ 1 request/s).

### Performance

- Geocoding, routing and forecasts run in parallel.
- Forecasts are deduplicated per ~1 km cell and fetched in multi-location Open-Meteo batches.
- Keep-alive HTTP sessions.
- In-memory TTL caches: routes 10 min, forecasts 15 min.
- `GZipMiddleware` shrinks the Dallas → Chicago response from ~560 kB to ~150 kB.

Typical Dallas → Chicago times: ~2 s on a cold request, ~0.1 s when cached. If ORS is down: ~7–8 s.

## API example

```bash
curl -X POST https://spotter-saferoute.vercel.app/api/routes \
  -H 'Content-Type: application/json' \
  -d '{"origin": "Dallas, TX", "destination": "Chicago, IL",
       "departure": "2026-10-19T08:00:00Z", "load_weight_lb": 40000, "interval_miles": 25}'
```

`interval_miles` is optional (10, 25 or 50; default 25). A departure without a timezone is treated as UTC.

Response from the live API, trimmed (`…` = more items):

```json
{
  "origin": {"query": "Dallas, TX", "lon": -96.784359, "lat": 32.736212},
  "destination": {"query": "Chicago, IL", "lon": -87.66063, "lat": 41.87897},
  "departure": "2026-10-19T08:00:00+00:00",
  "load_weight_lb": 40000.0,
  "interval_miles": 25,
  "routes": [
    {
      "index": 0,
      "provider": "ors-hgv",
      "distance_mi": 969.7,
      "duration_s": 77970.7,
      "duration_h": 21.7,
      "duration_adjusted": false,
      "car_duration_s": null,
      "geometry": [[32.73614, -96.78445], [32.73606, -96.78439], "…"],
      "steps": [
        {"instruction": "Turn right onto Rector Street", "road_name": "Rector Street",
         "distance_mi": 0.1, "duration_s": 39, "maneuver_type": "right",
         "location": [32.73606, -96.78439], "span": [1, 4]},
        "…"
      ],
      "checkpoints": [
        {
          "lat": 32.90616, "lon": -96.45258, "mile": 25,
          "eta": "2026-10-19T08:33:30.183085+00:00",
          "weather": {"wind_mph": 6.7, "gust_mph": 11.6, "rain_in_hr": 0, "snow_in_hr": 0,
                      "temp_f": 51.0, "forecast_time": "2026-10-19T09:00Z"},
          "series": {"start": "2026-10-19T09:00Z", "wind_mph": [6.7, 7.0, 6.7, "…"],
                     "gust_mph": [11.6, 12.1, 11.6, "…"], "rain_in_hr": [0, 0, 0, "…"],
                     "snow_in_hr": [0, 0, 0, "…"], "temp_f": [51.0, 50.7, 49.8, "…"]},
          "risk": {"level": "Low", "score": 1, "reasons": []}
        },
        "…"
      ],
      "summary": {"low_miles": 969.7, "moderate_miles": 0.0, "high_miles": 0.0,
                  "severe_miles": 0.0, "no_travel_miles": 0.0, "total_miles": 969.7,
                  "avg_score": 1.0}
    },
    "…"
  ],
  "recommended_route_index": 0,
  "providers": ["ors-hgv"],
  "fallback_used": false,
  "notice": ""
}
```

Response fields:
- `geometry` is `[lat, lon]` (Leaflet order).
- `series` holds 49 hourly values (k = leave k hours later) for the slider.
- `provider` is `"ors-hgv"` or `"osrm-car"`.

Errors come back as `{"error": "..."}` with status 400 (bad input / place not found) or 502 (routing or weather service failed). Error messages never include URLs or keys.

## Run locally (macOS)

You need Python 3.12+, Node.js 20+ and a free ORS key from <https://openrouteservice.org/dev/#/signup>.

```bash
# Backend (terminal 1)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # set ORS_API_KEY=your-key in .env (git-ignored)
python manage.py runserver        # http://localhost:8000/api/health

# Frontend (terminal 2)
cd frontend
npm install
npm run dev                       # http://localhost:5173
```

Locally the frontend calls `http://localhost:8000`. Set `VITE_API_URL` (see `frontend/.env.example`) to use another API. Set it to an empty string to call `/api` on the same origin, as the Vercel and Docker builds do.

## Tests

```bash
cd backend && python manage.py test      # 35 tests: risk bands + load rules, checkpoints/ETAs,
                                         # 48 h series, ranking + miles breakdown, routing fallback +
                                         # truck-time adjustment, steps, API endpoint (offline, APIs mocked)
cd frontend && npm test -- --exclude '**/._*'   # 5 Vitest tests for the navigation geometry (src/nav.js)
```

The `--exclude '**/._*'` flag skips macOS `._*` metadata files if your disk creates them. Both suites pass: 35/35 backend and 5/5 frontend.

## Deployment (Vercel)

The live app is **one Vercel project** on one origin, so no CORS setup is needed in production:

- `vercel.json` installs and builds the Vite frontend with `VITE_API_URL=` (same origin) and serves `frontend/dist` as static files.
- `api/index.py` exposes the Django WSGI app as a Python serverless function. `vercel.json` rewrites `/api/*` to it, and every other path goes to `index.html`.
- Root `requirements.txt` holds the function's Python dependencies (kept in sync with `backend/requirements.txt`).
- On Vercel (`VERCEL=1`), `DEBUG` is off by default, `ALLOWED_HOSTS` is `.vercel.app`, and SQLite (unused by the API) lives in `/tmp`.
- **Secrets:** `ORS_API_KEY` and `DJANGO_SECRET_KEY` are set as sensitive production environment variables in Vercel. They are not in the repo or sent to the browser. The ORS key is sent in a request header, never in a URL.

**Alternative: Docker.** The `Dockerfile` builds the frontend and serves it from Django with gunicorn + WhiteNoise in one container on port 7860:

```bash
docker build -t saferoute .
docker run -p 7860:7860 -e ORS_API_KEY=... -e DJANGO_SECRET_KEY=... \
  -e ALLOWED_HOSTS=localhost -e CSRF_TRUSTED_ORIGINS=http://localhost:7860 saferoute
```

(`render.yaml` is an older, unused Render blueprint.)

## Project layout

```
api/index.py                    Vercel serverless entry (Django WSGI)
vercel.json                     Vercel build, function and rewrite config
Dockerfile                      single-container alternative
requirements.txt                Python deps for the Vercel function
backend/
  config/settings.py            settings from env vars (key, debug, hosts), gzip, CORS
  routing/views.py              /api/health and the /api/routes pipeline
  routing/serializers.py        request validation
  routing/services/ors.py       geocoding + routes: ORS truck, OSRM/Nominatim fallbacks
  routing/services/steps.py     turn-by-turn steps from ORS/OSRM in one shape
  routing/services/weather.py   checkpoints, ETAs, batched/cached Open-Meteo forecasts
  routing/services/risk.py      risk table + load rules
  routing/services/recommend.py route summary + ranking
  routing/services/cache.py     small thread-safe TTL cache
  routing/tests.py              35 offline tests
frontend/src/
  App.jsx                       side panel: form, tabs, route cards, slider
  RouteMap.jsx                  Leaflet map: basemaps, heatmap, routes, checkpoints, pins, legend
  Directions.jsx                turn-by-turn list
  NavMode.jsx                   navigation mode (simulated drive, voice, GPS)
  nav.js / nav.test.js          navigation geometry helpers + Vitest tests
  risk.js                       client copy of risk rules + ranking (for the slider)
  App.css                       plain-CSS dark UI
```

## Design decisions

- **Weather at the ETA, not at departure:** the forecast for Chicago now doesn't matter if the truck arrives tomorrow.
- **Safety before speed:** dangerous miles decide the ranking. Time only breaks ties.
- **Fair fallback:** OSRM car routes keep the app working when ORS is slow. Their times are scaled to truck speed so a car route can't win just by being faster.
- **Slider without requests:** sending 48 h of forecast once lets the browser re-score instantly, which keeps the UI smooth and avoids rate limits.
- **Smooth navigation:** the truck marker, camera and route lines update in one `requestAnimationFrame` loop outside React. React only re-renders the banner and bottom bar about 4× per second.
- **Small, testable services:** routing, steps, weather, risk and recommendation are separate plain-Python modules, so each can be unit-tested on its own with the outside APIs mocked.

## Known limitations

- **Free-tier services:** ORS and the OSRM demo server have rate limits and can be slow. There are no ORS retries, just the 7 s budget and then the OSRM fallback.
- **OSRM routes are car routes:** they ignore truck restrictions (height, weight, hazmat). Their times are adjusted, but they should be treated as approximate. They are clearly labelled.
- **Long-trip alternatives** come from via-point detours. They are real truck routes but can be noticeably longer than the main route.
- **ETAs assume a steady pace:** no stops, traffic or Hours-of-Service breaks.
- **Gusts not scored:** the wind level uses sustained 10 m wind. Gusts are shown but not scored.
- **Caches are in memory:** each serverless instance has its own, and a cold start begins empty.
- **Forecast range:** Open-Meteo covers up to 16 days from 00:00 UTC today. ETAs outside that window use the nearest available hour.
