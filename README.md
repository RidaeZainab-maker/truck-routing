# Weather-Aware Truck Routing

React (Vite + Material UI + Leaflet) frontend, Django REST Framework backend.
Enter origin, destination, departure time and load weight -> get 3 truck routes, weather risk along each, and a recommended route.

> Skeleton only. Business logic is marked with `TODO` for me to implement.

## Setup

### Backend
```bash
cd backend
python3 -m venv .venv          # already created
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env           # then paste your ORS_API_KEY
python manage.py migrate
python manage.py runserver     # http://localhost:8000/api/health
```

### Frontend
```bash
cd frontend
npm install
cp .env.example .env           # VITE_API_URL=http://localhost:8000
npm run dev                    # http://localhost:5173
```

## Architecture

```
React (MUI form + Leaflet map)
   │ POST /api/routes {origin, destination, departure, load_weight_lb}
   ▼
Django REST (routing/views.py)
   ├─ services/ors.py        geocode + 3 driving-hgv routes (OpenRouteService)
   ├─ services/weather.py    checkpoints every 10/25/50 mi + ETA, Open-Meteo hourly forecast
   ├─ services/risk.py       wind / rain / snow thresholds + load rules -> Low/Moderate/High/Severe
   └─ services/recommend.py  rank: fewest Severe mi > fewest High mi > lowest avg risk > shortest time
```

Endpoints: `GET /api/health` (works), `POST /api/routes` (stub returning placeholder JSON).

## Build plan

- **Day 1 – Routes:** get free ORS key, implement `ors.geocode` + `ors.get_routes`, return route geometries from `/api/routes`, draw `<Polyline>`s on the map.
- **Day 2 – Weather + risk:** implement `sample_checkpoints` (haversine + ETA), `get_forecast_at` (Open-Meteo, batch/cache), `classify_checkpoint`; show colored checkpoint markers with ETA popups.
- **Day 3 – Recommendation + UI:** `summarize_route` + `recommend`; route cards in sidebar (distance, time, Severe/High miles), highlight recommended route; interval selector (10/25/50 mi).
- **Day 4 – Heatmap slider:** grid of points around the corridor, forecast 0–48h, MUI `<Slider>` to change hour, render colored circles/heat layer.
- **Hosting:** Django on Render (gunicorn, `ALLOWED_HOSTS`, CORS for Vercel domain, `ORS_API_KEY` env var); React on Vercel (`VITE_API_URL` = Render URL).
- **Loom:** demo the flow, then walk through each service file and explain the risk rules and ranking.
