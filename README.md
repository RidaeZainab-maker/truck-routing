# Weather-Aware Truck Routing

A small web app for truck drivers and dispatchers. You enter an **origin**, a **destination**, a **departure time** and the **load weight**. The app finds 2–3 truck routes, checks the weather forecast at points along each route for the time the truck will actually be there, rates each point from **Low** to **No Travel**, and recommends the safest route.

## Features

- 3 heavy-goods-vehicle (HGV) routes from OpenRouteService (`driving-hgv` profile), with an automatic OSRM fallback (see below).
- Weather checkpoints every **10, 25 or 50 miles**, each with an ETA based on the route's drive time.
- Hourly forecast (wind, gusts, rain, snow, temperature) from Open-Meteo for the hour nearest each ETA.
- Risk level per checkpoint using the brief's wind / rain / snow table plus load-weight rules.
- Recommended route: least dangerous first, fastest as the tie-break.
- Map with all routes, colour-coded checkpoint markers and popups (ETA, weather, reasons).
- "Leave later" slider (0–48 h): the API returns 48 h of hourly forecast per checkpoint, so the browser re-scores risk, the heatmap and the recommendation instantly (no request per slider tick).
- Dark "Spotter SafeRoute" UI: Esri dark-gray tiles, glowing active route, dashed alternatives, risk-coloured heatmap halos and checkpoints, route cards with a Low/Mod/High/Severe miles bar.

- **Navigation mode** (Google-Maps style): "GO" flies to the origin at street zoom on the Streets basemap and follows a heading-rotated truck marker along the route. The drive is simulated at the route's real average pace × 1/10/60/300 (requestAnimationFrame; marker, camera and route lines are updated imperatively, React only refreshes the HUD ~4×/s). Top banner: maneuver arrow, "In 0.3 mi", instruction, "Then …". Bottom bar: time and miles remaining, ETA, risk chip of the next checkpoint, and a warning toast + voice alert before Moderate+ checkpoints. Voice guidance via the Web Speech API (~0.5 mi before and at each turn, thresholds scale with speed), mute, pause/resume, optional device GPS (`navigator.geolocation`, snapped to the route), exit restores the previous basemap. Route ahead is bold blue, travelled part dimmed grey, and the current step is highlighted in the Directions list. Geometry helpers live in `frontend/src/nav.js` (unit-tested with Vitest: `npm test`).

## Tech stack

| Layer    | Tech |
|----------|------|
| Frontend | React 19, Vite, Leaflet / react-leaflet, plain CSS, Esri World Dark Gray Canvas tiles |
| Backend  | Python 3.12+, Django, Django REST Framework, django-cors-headers, python-dotenv, requests |
| APIs     | [OpenRouteService](https://openrouteservice.org/) (geocoding + truck directions, free API key), [Open-Meteo](https://open-meteo.com/) (forecast, no key); fallbacks: [OSRM demo server](https://project-osrm.org/) (directions), [Nominatim](https://nominatim.org/) (geocoding) |

## Architecture and data flow

```
React (HUD panel + Leaflet map)                       frontend/src/App.jsx
   │  POST /api/routes {origin, destination, departure, load_weight_lb, interval_miles}
   ▼
Django REST view                                     backend/routing/views.py
   1. validate input                                 routing/serializers.py
   2. geocode origin + destination                   services/ors.py  -> ORS /geocode/search
   3. get 2–3 truck routes                           services/ors.py  -> ORS /v2/directions/driving-hgv
        - trip < 80 km straight line: ORS alternative_routes
        - longer trips (or too few alternatives): main route + detours through
          via-points left/right of the midpoint
   4. for each route: checkpoints every N miles + ETA   services/weather.py (haversine walk)
      forecasts for all checkpoints in batched calls     services/weather.py -> Open-Meteo
   5. classify each checkpoint                       services/risk.py
   6. summarise each route + pick the best           services/recommend.py
   7. JSON response (routes, [lat, lon] geometry, checkpoints, recommended_route_index)
```

Endpoints:

- `GET /api/health` → `{"status": "ok"}`
- `POST /api/routes` → plan routes (see example below)

## Routing fallback

The free ORS `driving-hgv` endpoint is sometimes very slow on long trips (e.g. Dallas → Chicago times out). `services/ors.py` therefore:

- gives ORS directions a **7 s total budget** (OSRM runs concurrently as a standby) to produce all 3 routes itself (`alternative_routes` on short trips, otherwise `driving-hgv` via-point detours left/right of the midpoint);
- **never mixes providers silently.** If ORS fails entirely, all 3 routes come from the public **OSRM demo server** (`alternatives=true` plus via-point detours, 12 s budget, started in parallel with ORS) and keep their car times. Ranking is then like-with-like (all car routes).
- If ORS returns 1–2 truck routes but runs out of time for the rest, OSRM tops up the list and **its durations are converted to truck time**: `factor = ORS truck time / OSRM car time` for each provider's fastest route on this trip (≥ 1), plus a floor of distance ÷ 55 mph. The raw car time is kept as `car_duration_s` and the route has `duration_adjusted: true` (the card shows "truck-adj."). On an exact tie a real ORS truck route ranks ahead of an adjusted car route. This keeps the recommendation from picking a car route just because cars are faster.
- geocodes with ORS (8 s timeout) and falls back to **Nominatim** (identifying User-Agent, max 1 request/second) if ORS errors.

Every route in the response has `provider`: `"ors-hgv"` or `"osrm-car"`. The response also carries `providers`, `fallback_used` and a `notice` shown in the UI: empty for all-ORS, "Truck routing service slow — showing car-road routes from OSRM" for all-OSRM, and e.g. "1 truck route from ORS, 2 car-road alternatives from OSRM (times adjusted to truck speeds)" when mixed. OSRM routes are **car** routes: they ignore truck restrictions (height/weight limits, hazmat), so treat them as approximate. Worst case (ORS down) a request takes about 7–8 s plus weather calls.

## Performance

`/api/routes` is built to answer in a few seconds:

- origin and destination are geocoded in parallel (cached per process);
- ORS truck routing and the OSRM standby run **concurrently**. ORS fires the main route and all via-point detours at once (plus `alternative_routes` on short trips, only waited for if needed) and gets a 7 s budget; if it fails, the OSRM answer is usually already in hand. Fairness rules above still apply;
- forecasts for all routes are fetched in parallel, deduplicated per ~1 km cell, in multi-location Open-Meteo batches;
- keep-alive `requests.Session`s, in-memory TTL caches (routes 10 min, forecasts 15 min per cell/hour), coordinates rounded to 5 decimals, and `GZipMiddleware` (~650 kB → ~150 kB for Dallas → Chicago).

Measured on the dev box (real APIs, ORS healthy): Dallas → Chicago ~2.3 s cold / 0.08 s warm (was ~11 s / ~8 s), Dallas → Fort Worth ~1.0 s cold / 0.01 s warm (was ~8–9 s). If ORS is down the request takes ~7–8 s (ORS budget, then OSRM).

## Turn-by-turn directions

Each route carries `steps`: `{instruction, road_name, distance_mi, duration_s, maneuver_type, location [lat, lon], span [i0, i1]}` (`services/steps.py`). ORS supplies the instruction text; for OSRM the text is built from maneuver type/modifier, road ref/name and signposted destinations ("Turn left onto I-35", "Take the exit toward Waco"). The **Directions** tab lists the selected route's steps with maneuver arrows, step distance, cumulative mile, ETA (shifted by the slider) and the risk colour of the nearest checkpoint. Clicking a step flies the map to the turn at zoom 17, highlights the step's stretch and opens a popup; "Back to full route" refits. The map zooms to 19: the Streets and Satellite basemaps are native to 19, the dark canvas upscales past its native zoom 16.

## Risk rules

Each checkpoint gets a level for wind, rain and snow; the **worst** of the three is the checkpoint level.

| Condition        | Low      | Moderate  | High      | Severe    | No Travel |
|------------------|----------|-----------|-----------|-----------|-----------|
| Wind (mph)       | < 25     | 25 – 34   | 35 – 44   | 45 – 54   | ≥ 55      |
| Rain (in/hr)     | < 0.10   | 0.10 – 0.25 | 0.25 – 0.50 | 0.50 – 1.00 | > 1.00 |
| Snow (in/hr)     | < 0.5    | 0.5 – 1.0 | 1.0 – 2.0 | 2.0 – 3.0 | > 3.0     |

Band edges are inclusive at the lower end (25 mph = Moderate, 0.25 in/hr = High). Rain and snow only become No Travel when strictly above 1.00 / 3.0.

**Load rules** (heavier trucks are harder to control in strong side winds):

| Wind        | Load            | Result      |
|-------------|-----------------|-------------|
| ≥ 55 mph    | any             | No Travel   |
| 45 – 54 mph | > 30,000 lb     | No Travel   |
| 35 – 44 mph | > 40,000 lb     | Severe      |

Scores used for averages (1–5 scale): Low 1, Moderate 2, High 3, Severe 4, No Travel 5. The UI shows e.g. "avg risk 1.0/5".

## How the recommendation works

For every route the backend counts how many miles fall in each level (each stretch between consecutive checkpoints counts as the worse of its two ends, using real mile markers, so the levels sum to the route length) and the average score. Routes are then sorted by, in order:

1. fewest **No Travel** miles
2. fewest **Severe** miles
3. fewest **High** miles
4. lowest **average risk score**
5. shortest **drive time** (OSRM car times are truck-adjusted when mixed with ORS routes; see Routing fallback)
6. on an exact tie, an ORS truck route before an OSRM car route

So a slightly longer route wins if it avoids dangerous weather; if all routes are equally safe, the fastest one wins.

## Setup (macOS)

Prerequisites: Python 3.12+ (`brew install python`), Node.js 20+ (`brew install node`), and a free OpenRouteService API key from <https://openrouteservice.org/dev/#/signup>.

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then edit .env and set ORS_API_KEY=your-key-here
python manage.py migrate
python manage.py runserver      # http://localhost:8000/api/health
```

`backend/.env` should contain only:

```
ORS_API_KEY=your-openrouteservice-key
```

`.env` is in `.gitignore` - never commit your key.

Run the tests (offline, external APIs are mocked):

```bash
python manage.py test
```

### Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev                     # http://localhost:5173
```

The frontend calls `http://localhost:8000` by default. To point it elsewhere, copy `frontend/.env.example` to `frontend/.env` and set `VITE_API_URL` (read at build time, e.g. `VITE_API_URL=https://your-api.example.com npm run build` for hosting). The backend allows CORS from `http://localhost:5173` and `http://127.0.0.1:5173`.

Production build: `npm run build` (output in `frontend/dist`).

## API example

Request:

```bash
curl -X POST http://localhost:8000/api/routes \
  -H 'Content-Type: application/json' \
  -d '{
        "origin": "Dallas, TX",
        "destination": "Chicago, IL",
        "departure": "2026-10-18T15:30:00Z",
        "load_weight_lb": 40000,
        "interval_miles": 25
      }'
```

`interval_miles` is optional (10, 25 or 50; default 25). A departure without a timezone is treated as UTC.

Response (shortened):

```json
{
  "origin": {"query": "Dallas, TX", "lon": -96.784359, "lat": 32.736212},
  "destination": {"query": "Chicago, IL", "lon": -87.66063, "lat": 41.87897},
  "departure": "2026-10-18T15:30:00+00:00",
  "load_weight_lb": 40000.0,
  "interval_miles": 25,
  "recommended_route_index": 0,
  "routes": [
    {
      "index": 0,
      "distance_mi": 969.6,
      "duration_s": 61834.6,
      "duration_h": 17.2,
      "geometry": [[32.736158, -96.784463], [32.736137, -96.784448], "..."],
      "summary": {"no_travel_miles": 0, "severe_miles": 0, "high_miles": 0, "avg_score": 0.0},
      "checkpoints": [
        {
          "lat": 32.906, "lon": -96.453, "mile": 25,
          "eta": "2026-10-18T15:58:47+00:00",
          "weather": {"wind_mph": 6.3, "gust_mph": 7.6, "rain_in_hr": 0, "snow_in_hr": 0,
                      "temp_f": 62.0, "forecast_time": "2026-10-18T16:00Z"},
          "risk": {"level": "Low", "score": 0, "reasons": []}
        }
      ]
    }
  ]
}
```

`geometry` is a list of `[lat, lon]` pairs (Leaflet order). Errors come back as `{"error": "..."}` with status 400 (bad input / place not found) or 502 (OpenRouteService or Open-Meteo failed).

## Project layout

```
backend/
  config/settings.py          Django settings, loads backend/.env, CORS
  routing/views.py            /api/health and /api/routes pipeline
  routing/serializers.py      request validation
  routing/services/ors.py     geocoding + truck routes (alternatives / detour fallback)
  routing/services/weather.py checkpoints, ETAs, batched Open-Meteo forecasts
  routing/services/risk.py    risk table + load rules
  routing/services/recommend.py  route summary + ranking
  routing/tests.py            offline unit tests
frontend/
  src/App.jsx                 form, route cards, slider, Leaflet map
```

## Known limitations

- **ORS alternative routes only work for short trips** (about 100 km on the free plan). For longer trips the app builds alternatives itself by forcing the route through a via-point to the left and right of the midpoint. These detours are real truck routes but can be noticeably longer than the main route, and sometimes only 2 distinct routes come back.
- **Forecast window.** Open-Meteo's forecast starts at 00:00 UTC today. The app asks for at least 3 days and up to 16 (as much as the latest ETA needs). Checkpoints outside that window (a departure far in the future or in the past) use the nearest available hour.
- **ORS free-tier rate limits** (per-minute and daily quotas for geocoding and directions). Each request uses 2 geocoding calls and 1–5 directions calls, so many quick re-plans (interval toggle, slider) can hit the limit; you then get a 502 error. ORS can also be slow or temporarily down; the backend retries once on 429/5xx and gives up on detours after ~60 s.
- ETAs assume constant speed along the route (no stops, traffic or Hours-of-Service breaks).
- "Miles at risk" are approximate: checkpoints at a level × interval miles.
- Wind level uses sustained wind speed (10 m); gusts are shown but not scored.
- Development settings only (`DEBUG = True`, SQLite, dev secret key); not hardened for production.


## Deploy (Render)

`render.yaml` is a Render Blueprint for the API (gunicorn, `DJANGO_DEBUG=False`, generated `DJANGO_SECRET_KEY`, `ALLOWED_HOSTS`) and the static frontend. After the first deploy set `ORS_API_KEY` and `CORS_ALLOWED_ORIGINS` (frontend URL) on the API, and `VITE_API_URL` (API URL) on the frontend, then redeploy the frontend. Settings read `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS` from the environment with local-dev defaults.
