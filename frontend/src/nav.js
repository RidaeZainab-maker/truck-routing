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

// Interpolated [lat, lon] at `m` miles (already clamped) plus the segment index.
function posAt(track, m) {
  const { pts, cum } = track
  const i = segmentIndex(track, m)
  const a = pts[i], b = pts[i + 1]
  const len = cum[i + 1] - cum[i]
  const f = len > 0 ? (m - cum[i]) / len : 0
  return [a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]), i]
}

export const HEADING_LOOK_MI = 0.02 // ~30 m: smooths tiny zig-zags without cutting real corners much

/**
 * Direction of travel at `mile`, measured on the drawn polyline itself ([lat, lon]):
 * bearing from the marker's own position to the point `look` miles further along the
 * track (or from `look` miles back, at the very end). 0 = north, clockwise.
 */
export function headingAt(track, mile, look = HEADING_LOOK_MI) {
  if (track.pts.length < 2 || track.total <= 0) return 0
  const m = Math.min(Math.max(mile, 0), track.total)
  const here = posAt(track, m)
  if (track.total - m >= look * 0.25) return bearing(here, posAt(track, Math.min(track.total, m + look)))
  return bearing(posAt(track, Math.max(0, m - look)), here)
}

/** Position + heading at `mile` along the track. */
export function pointAt(track, mile) {
  const { pts } = track
  if (pts.length < 2) return { lat: pts[0][0], lon: pts[0][1], heading: 0, idx: 0 }
  const m = Math.min(Math.max(mile, 0), track.total)
  const [lat, lon, i] = posAt(track, m)
  return { lat, lon, heading: headingAt(track, m), idx: i }
}

/**
 * Continuous rotation for a CSS rotate(): the equivalent of `next` (0-360) closest to
 * `prev` (unbounded), so 359 -> 1 becomes 359 -> 361 instead of a 358-degree spin
 * through "backwards" (a CSS transition between rotate(359deg) and rotate(1deg)
 * interpolates the long way round).
 */
export function unwrapAngle(prev, next) {
  if (prev == null || !Number.isFinite(prev)) return next
  const d = ((((next - prev) % 360) + 540) % 360) - 180
  return prev + d
}

/** Cheap identity for a route geometry (same polyline -> same key). */
export function geometryKey(geometry) {
  if (!geometry?.length) return ''
  const n = geometry.length
  const pick = [0, n >> 2, n >> 1, (3 * n) >> 2, n - 1].map((i) => geometry[i].join(','))
  return `${n}|${pick.join('|')}`
}

/**
 * Mile on `track` closest to [lat, lon] (whole-track search), or null if the track
 * does not pass within `maxMi` of it. Used to carry progress over to a re-planned route.
 */
export function resumeMile(track, lat, lon, maxMi = 0.25) {
  const { pts, cum } = track
  let best = -1, bestD = Infinity
  for (let i = 0; i < pts.length; i++) {
    const d = (pts[i][0] - lat) ** 2 + (pts[i][1] - lon) ** 2
    if (d < bestD) { bestD = d; best = i }
  }
  if (best < 0 || haversineMi(pts[best], [lat, lon]) > maxMi) return null
  return cum[best]
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

// ---- maneuver icons -------------------------------------------------------
// One SVG shape per maneuver, drawn for the RIGHT-hand version; the left-hand version is
// the same shape mirrored. So left vs right can only come from the maneuver's side, never
// from which font happens to render an arrow glyph (the old Unicode arrows ↰ ↱ ↖ ↗ look
// different, and easy to misread, depending on the OS font fallback).

const TEXT_SIDE = /^(?:at the end of the road, )?(?:turn|keep|bear|merge|make a|veer)\s+(?:sharp\s+|slight\s+)?(left|right)\b/i

/**
 * maneuver_type to draw for a step. Same rule as backend steps.reconcile(): if the
 * instruction text names a side and the type disagrees, the text wins, so the icon can
 * never contradict what the banner says.
 */
export function maneuverOf(step) {
  const t = step?.maneuver_type || 'straight'
  const m = TEXT_SIDE.exec((step?.instruction || '').trim())
  if (!m || ['depart', 'arrive', 'roundabout', 'uturn'].includes(t)) return t
  const side = m[1].toLowerCase(), other = side === 'left' ? 'right' : 'left'
  if (t.includes(side)) return t
  if (t.includes(other)) return t.replace(other, side)
  return { straight: `slight-${side}`, merge: `merge-${side}` }[t] || side
}

// Right-hand shapes in a 24x24 box. `main` = the path to follow, `faint` = context (the
// road not taken), all stroked. Arrowheads are part of `main`.
export const ICON_SHAPES = {
  straight: { main: ['M12 21V4', 'M7 9l5-5 5 5'] },
  right: { main: ['M7 21v-8a4 4 0 0 1 4-4h9', 'M16 5l4 4-4 4'] },
  'sharp-right': { main: ['M8 21V7l10 10', 'M18 11v6h-6'] },
  'slight-right': { main: ['M9 21v-7l8-8', 'M11 6h6v6'] },
  'keep-right': { main: ['M11 21v-7l6-7', 'M12 7h5v5'], faint: ['M11 14L6 7'] },
  'exit-right': { main: ['M10 14l7-7', 'M12 7h5v5'], faint: ['M10 21V3'] },
  merge: { main: ['M12 21V4', 'M7 9l5-5 5 5'], faint: ['M5 21c0-5 7-6 7-11'] },
  'merge-right': { main: ['M6 21c0-6 6-7 6-12V4', 'M8 8l4-4 4 4'], faint: ['M17 21V10'] },
  uturn: { main: ['M17 21V10a5 5 0 0 0-10 0v7', 'M3 13l4 4 4-4'] }, // US U-turns go left
  roundabout: { main: ['M12 21v-5.5', 'M14.5 8.5L19 4', 'M15 4h4v4'], faint: ['M12 15.5a3.5 3.5 0 1 0 0-7a3.5 3.5 0 1 0 0 7'] },
  depart: { main: ['M12 21V8', 'M7 13l5-5 5 5'], dot: true },
  arrive: { main: ['M7 21V4', 'M7 4h11l-3 4 3 4H7'] },
}

/** {shape, mirror} for a maneuver_type: left variants reuse the right shape, mirrored. */
export function iconFor(type) {
  const t = type || 'straight'
  if (ICON_SHAPES[t]) return { shape: t, mirror: false }
  if (t === 'exit') return { shape: 'exit-right', mirror: false } // legacy backend value
  if (t.includes('left')) {
    const r = t.replace('left', 'right')
    if (ICON_SHAPES[r]) return { shape: r, mirror: true }
  }
  return { shape: 'straight', mirror: false }
}
