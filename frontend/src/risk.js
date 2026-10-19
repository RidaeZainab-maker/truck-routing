// Client-side copy of backend/routing/services/{risk,recommend}.py.
// The backend sends 48 h of hourly forecast per checkpoint, so the departure
// slider re-scores routes here instantly instead of calling the API per tick.
// Keep thresholds in sync with risk.py (covered by backend tests).

export const LEVELS = ['Low', 'Moderate', 'High', 'Severe', 'No Travel']
export const SCORES = { Low: 1, Moderate: 2, High: 3, Severe: 4, 'No Travel': 5 } // 1-5 scale
export const RISK_COLORS = {
  Low: '#10b981', Moderate: '#f59e0b', High: '#f97316', Severe: '#ef4444', 'No Travel': '#991b1b',
}

const band = (v, edges, noTravelAbove) => {
  if (noTravelAbove != null && v > noTravelAbove) return 'No Travel'
  let lvl = 'Low'
  edges.forEach((e, i) => { if (v >= e) lvl = LEVELS[i + 1] })
  return lvl
}
export const worse = (a, b) => (SCORES[a] >= SCORES[b] ? a : b)

export function classify({ wind_mph = 0, rain_in_hr = 0, snow_in_hr = 0 }, load) {
  const wind = Math.max(wind_mph || 0, 0)
  let windLvl = band(wind, [25, 35, 45, 55])
  if (wind >= 45 && wind < 55 && load > 30000) windLvl = 'No Travel'
  else if (wind >= 35 && wind < 45 && load > 40000) windLvl = worse(windLvl, 'Severe')
  return [windLvl, band(rain_in_hr || 0, [0.1, 0.25, 0.5], 1.0), band(snow_in_hr || 0, [0.5, 1.0, 2.0], 3.0)]
    .reduce(worse)
}

// Weather a checkpoint sees when leaving `offset` hours later (falls back to the
// base forecast at offset 0 or if the series is short).
export function weatherAt(cp, offset) {
  const s = cp.series
  if (!offset || !s || !s.wind_mph || offset >= s.wind_mph.length) return cp.weather
  return {
    wind_mph: s.wind_mph[offset], gust_mph: s.gust_mph[offset], rain_in_hr: s.rain_in_hr[offset],
    snow_in_hr: s.snow_in_hr[offset], temp_f: s.temp_f[offset],
  }
}

// Re-score every route for a departure offset; same ranking as recommend.py.
export function scoreRoutes(routes, offset, load) {
  const scored = routes.map((r) => {
    const cps = r.checkpoints.map((cp) => {
      const weather = weatherAt(cp, offset)
      const level = offset ? classify(weather, load) : cp.risk.level
      return { ...cp, weather, level, eta: new Date(new Date(cp.eta).getTime() + offset * 3600e3) }
    })
    // Each stretch between checkpoints counts as its worse end, using real mile
    // markers, so the level miles sum to the route length (same as recommend.py).
    const raw = Object.fromEntries(LEVELS.map((l) => [l, 0]))
    for (let k = 1; k < cps.length; k++) raw[worse(cps[k - 1].level, cps[k].level)] += cps[k].mile - cps[k - 1].mile
    const miles = Object.fromEntries(LEVELS.map((l) => [l, Math.round(raw[l] * 10) / 10]))
    const avg = cps.length ? cps.reduce((a, c) => a + SCORES[c.level], 0) / cps.length : 0
    return { ...r, cps, miles, avg: Math.round(avg * 100) / 100 }
  })
  const key = (r) => [r.miles['No Travel'], r.miles.Severe, r.miles.High, r.avg, r.duration_s, r.provider === 'osrm-car' ? 1 : 0]
  let best = null
  scored.forEach((r, i) => {
    if (best == null) { best = i; return }
    const a = key(r), b = key(scored[best])
    for (let k = 0; k < a.length; k++) {
      if (a[k] !== b[k]) { if (a[k] < b[k]) best = i; break }
    }
  })
  return { scored, best }
}

// 0..1 "how bad is it" from the raw values, used only for heatmap intensity
// (width/opacity), never for the risk level itself. Fractions of the No Travel limits.
export function severity(w) {
  const s = Math.max((w.wind_mph || 0) / 55, (w.gust_mph || 0) / 75, (w.rain_in_hr || 0) / 1.0, (w.snow_in_hr || 0) / 3.0)
  return Math.sqrt(Math.min(1, Math.max(0, s))) // sqrt: light winds still show visible variation
}

const R = 3958.8
const hav = ([la1, lo1], [la2, lo2]) => {
  const p1 = (la1 * Math.PI) / 180, p2 = (la2 * Math.PI) / 180
  const a = Math.sin((p2 - p1) / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(((lo2 - lo1) * Math.PI) / 360) ** 2
  return 2 * R * Math.asin(Math.sqrt(a))
}

// Cut a [lat, lon] polyline into one piece per checkpoint-to-checkpoint stretch
// (same haversine walk the backend uses to place checkpoints). Run once per route.
export function splitAtMiles(geometry, miles) {
  const pieces = []
  let k = 0, acc = 0, cur = [geometry[0]]
  for (let i = 1; i < geometry.length && k < miles.length - 1; i++) {
    const a = geometry[i - 1], b = geometry[i], d = hav(a, b)
    while (k < miles.length - 1 && acc + d >= miles[k + 1] && d > 0) {
      const f = (miles[k + 1] - acc) / d
      const p = [a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])]
      cur.push(p); pieces.push(cur); cur = [p]; k++
    }
    cur.push(b); acc += d
  }
  if (k < miles.length - 1) pieces.push(cur)
  return pieces
}

// Cumulative mile / ETA per step, plus the risk of the nearest checkpoint.
// Step durations are scaled to the route's (possibly truck-adjusted) total time.
export function enrichSteps(route, departure, offsetH) {
  const steps = route.steps || []
  const total = steps.reduce((a, s) => a + s.duration_s, 0) || 1
  const scale = route.duration_s / total
  const start = new Date(departure).getTime() + offsetH * 3600e3
  let mi = 0, sec = 0
  return steps.map((s) => {
    const cp = route.cps.reduce((best, c) => (Math.abs(c.mile - mi) < Math.abs(best.mile - mi) ? c : best), route.cps[0])
    const row = { ...s, atMile: mi, eta: new Date(start + sec * scale * 1000), level: cp?.level ?? 'Low' }
    mi += s.distance_mi
    sec += s.duration_s
    return row
  })
}

