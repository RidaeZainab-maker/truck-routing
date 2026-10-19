// Pure helpers for navigation mode (no React/Leaflet). Distances in miles.
// geometry: [[lat, lon], ...] as sent by the API.

const R = 3958.8
const rad = (d) => (d * Math.PI) / 180

export function haversineMi([la1, lo1], [la2, lo2]) {
  const a = Math.sin(rad(la2 - la1) / 2) ** 2 + Math.cos(rad(la1)) * Math.cos(rad(la2)) * Math.sin(rad(lo2 - lo1) / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(a))
}

/** Initial bearing a -> b in degrees (0 = north, clockwise). */
export function bearing([la1, lo1], [la2, lo2]) {
  const y = Math.sin(rad(lo2 - lo1)) * Math.cos(rad(la2))
  const x = Math.cos(rad(la1)) * Math.sin(rad(la2)) - Math.sin(rad(la1)) * Math.cos(rad(la2)) * Math.cos(rad(lo2 - lo1))
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360
}

/** Precompute cumulative miles along the polyline (once per route). */
export function buildTrack(geometry) {
  const cum = new Float64Array(geometry.length)
  for (let i = 1; i < geometry.length; i++) cum[i] = cum[i - 1] + haversineMi(geometry[i - 1], geometry[i])
  return { pts: geometry, cum, total: cum[cum.length - 1] || 0 }
}

/** Index i such that cum[i] <= mile < cum[i+1] (binary search). */
export function segmentIndex(track, mile) {
  const { cum } = track
  let lo = 0, hi = cum.length - 1
  if (mile <= 0) return 0
  if (mile >= cum[hi]) return Math.max(0, hi - 1)
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (cum[mid] <= mile) lo = mid
    else hi = mid
  }
  return lo
}

/** Position + heading at `mile` along the track. */
export function pointAt(track, mile) {
  const { pts, cum } = track
  if (pts.length < 2) return { lat: pts[0][0], lon: pts[0][1], heading: 0, idx: 0 }
  const m = Math.min(Math.max(mile, 0), track.total)
  const i = segmentIndex(track, m)
  const a = pts[i], b = pts[i + 1]
  const len = cum[i + 1] - cum[i]
  const f = len > 0 ? (m - cum[i]) / len : 0
  // Heading from a short look-ahead so tiny zig-zags in the geometry don't make the arrow jitter.
  let j = i + 1
  while (j < pts.length - 1 && cum[j] - cum[i] < 0.02) j++
  return { lat: a[0] + f * (b[0] - a[0]), lon: a[1] + f * (b[1] - a[1]), heading: bearing(a, pts[j]), idx: i }
}

/** Mile at which each step's maneuver happens (from its geometry span). */
export function stepMiles(track, steps) {
  return steps.map((s) => track.cum[Math.min(s.span?.[0] ?? 0, track.cum.length - 1)])
}

/** Index of the step being driven: last step whose maneuver is at or behind `mile`. */
export function currentStep(miles, mile) {
  let k = 0
  for (let i = 0; i < miles.length; i++) if (miles[i] <= mile + 1e-6) k = i
  return k
}

/** Next maneuver ahead of `mile`: {index, distance} (null at the end). */
export function nextManeuver(miles, mile) {
  const k = currentStep(miles, mile)
  return k + 1 < miles.length ? { index: k + 1, distance: Math.max(0, miles[k + 1] - mile) } : null
}

/** First checkpoint at or beyond `mile` (cps carry .mile). */
export function upcomingCheckpoint(cps, mile) {
  return cps.find((c) => c.mile >= mile - 0.5) || cps[cps.length - 1]
}

/** Snap a GPS fix to the nearest track mile (searches around `hintIdx` first). */
export function snapToTrack(track, lat, lon, hintIdx = 0, window = 2000) {
  const { pts, cum } = track
  let best = hintIdx, bestD = Infinity
  const from = Math.max(0, hintIdx - window), to = Math.min(pts.length, hintIdx + window)
  for (let i = from; i < to; i++) {
    const d = (pts[i][0] - lat) ** 2 + (pts[i][1] - lon) ** 2
    if (d < bestD) { bestD = d; best = i }
  }
  return cum[best]
}

/**
 * Voice/announcement thresholds in miles for a given ground speed (mi/s, already
 * multiplied by the sim speed). "Early" ~0.5 mi before, or ~6 s ahead at high speed;
 * "now" ~0.05 mi, or ~1.5 s ahead.
 */
export function announceThresholds(speedMiPerS) {
  return { early: Math.max(0.5, speedMiPerS * 6), now: Math.max(0.05, speedMiPerS * 1.5) }
}

export const fmtDist = (mi) => (mi < 0.1 ? `${Math.max(10, Math.round((mi * 5280) / 10) * 10)} ft` : `${mi.toFixed(mi < 10 ? 1 : 0)} mi`)

// Arrow glyph per normalised maneuver_type (backend services/steps.py).
export const ARROWS = {
  depart: '●', arrive: '⚑', left: '↰', right: '↱', 'sharp-left': '↰', 'sharp-right': '↱',
  'slight-left': '↖', 'slight-right': '↗', 'keep-left': '↖', 'keep-right': '↗', straight: '↑',
  uturn: '↶', roundabout: '⟳', merge: '⤴', exit: '↗',
}
