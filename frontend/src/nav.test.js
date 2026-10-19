import { describe, expect, it } from 'vitest'
import {
  announceThresholds, bearing, buildTrack, currentStep, fmtDist, nextManeuver, pointAt, snapToTrack,
  stepMiles, upcomingCheckpoint,
} from './nav'

// Straight line north along lon -97: 1 degree latitude ~ 69.1 mi.
const geom = [[32, -97], [32.5, -97], [33, -97]]
const track = buildTrack(geom)

describe('nav helpers', () => {
  it('builds cumulative miles', () => {
    expect(track.total).toBeCloseTo(69.1, 0)
    expect(track.cum[1]).toBeCloseTo(34.55, 1)
  })
  it('interpolates position and heading', () => {
    const p = pointAt(track, track.total / 4)
    expect(p.lat).toBeCloseTo(32.25, 3)
    expect(p.lon).toBeCloseTo(-97, 6)
    expect(p.heading).toBeCloseTo(0, 0) // north
    expect(pointAt(track, 999).lat).toBeCloseTo(33, 6) // clamped to the end
    expect(bearing([0, 0], [0, 1])).toBeCloseTo(90, 3) // east
  })
  it('finds current step and next maneuver', () => {
    const steps = [{ span: [0, 1] }, { span: [1, 2] }, { span: [2, 2] }]
    const miles = stepMiles(track, steps)
    expect(currentStep(miles, 10)).toBe(0)
    expect(nextManeuver(miles, 10).index).toBe(1)
    expect(nextManeuver(miles, 10).distance).toBeCloseTo(24.55, 1)
    expect(currentStep(miles, 40)).toBe(1)
    expect(nextManeuver(miles, track.total)).toBeNull()
  })
  it('upcoming checkpoint and GPS snap', () => {
    const cps = [{ mile: 0 }, { mile: 25 }, { mile: 50 }, { mile: 69 }]
    expect(upcomingCheckpoint(cps, 26).mile).toBe(50)
    expect(snapToTrack(track, 32.49, -97.01)).toBeCloseTo(34.55, 1)
  })
  it('scales announcement thresholds with speed', () => {
    expect(announceThresholds(0.0167).early).toBe(0.5) // ~60 mph real time
    expect(announceThresholds(5).early).toBe(30)       // 300x
    expect(fmtDist(0.05)).toBe('260 ft')
    expect(fmtDist(2.34)).toBe('2.3 mi')
  })
})

// ---- regression tests for the navigation arrow bugs (real ORS/OSRM data, see __fixtures__) ----
import {
  geometryKey, headingAt, iconFor, ICON_SHAPES, maneuverOf, resumeMile, unwrapAngle,
} from './nav'
import fixtures from './__fixtures__/routes-to-new-york.json'

const angleDiff = (a, b) => Math.abs(((((a - b) % 360) + 540) % 360) - 180)
// Signed turn at vertex i of a [lat, lon] polyline, measured ~30 m before/after (+ = right).
function turnAt(g, i, look = 0.02) {
  const t = buildTrack(g)
  const m = t.cum[i]
  if (m < look || t.total - m < look) return null
  const inH = headingAt(t, m - look, look), outH = headingAt(t, m, look)
  return ((((outH - inH) % 360) + 540) % 360) - 180
}

describe('heading follows the drawn polyline', () => {
  it('points the way of travel in every direction ([lat, lon] order)', () => {
    const south = buildTrack([[33, -97], [32, -97]])
    const east = buildTrack([[32, -97], [32, -96]])
    const west = buildTrack([[32, -96], [32, -97]])
    expect(pointAt(south, 10).heading).toBeCloseTo(180, 0)
    expect(pointAt(east, 10).heading).toBeCloseTo(90, 0)
    expect(pointAt(west, 10).heading).toBeCloseTo(270, 0)
    expect(pointAt(east, 9999).heading).toBeCloseTo(90, 0) // at the very end: looks back
  })

  it('uses the marker position, not the segment start, on long segments', () => {
    // North 1 mile, then east: half-way up the first leg the truck faces north.
    const g = [[32, -97], [32 + 1 / 69.1, -97], [32 + 1 / 69.1, -96.9]]
    expect(pointAt(buildTrack(g), 0.5).heading).toBeCloseTo(0, 0)
  })

  for (const [name, fx] of Object.entries(fixtures)) {
    // Heading looks ~30 m ahead, so right before a sharp corner it already leans into the
    // turn; it must never point back against the direction of travel, though.
    it(`${name} (${fx.provider}): heading never points backwards`, () => {
      const t = buildTrack(fx.geometry)
      for (let m = 0; m < t.total - 0.02; m += 0.003) {
        const p = pointAt(t, m), q = pointAt(t, m + 0.003)
        if (haversine(p, q) < 0.002) continue
        expect(angleDiff(p.heading, bearing([p.lat, p.lon], [q.lat, q.lon]))).toBeLessThan(135)
      }
    })
  }
})

const haversine = (p, q) => buildTrack([[p.lat, p.lon], [q.lat, q.lon]]).total

describe('marker rotation is unwrapped (no spin through 180 at north)', () => {
  it('takes the short way round', () => {
    expect(unwrapAngle(359, 1)).toBe(361)
    expect(unwrapAngle(10, 350)).toBe(-10)
    expect(unwrapAngle(720, 90)).toBe(810)
    expect(unwrapAngle(null, 45)).toBe(45)
  })
  it('jitter around due north never produces a big swing', () => {
    let rot = null, maxStep = 0
    for (const h of [358, 2, 359, 1, 357, 3, 0, 359.5]) {
      const next = unwrapAngle(rot, h)
      if (rot != null) maxStep = Math.max(maxStep, Math.abs(next - rot))
      rot = next
    }
    expect(maxStep).toBeLessThan(10)
  })
  it('dallas: per-frame rotation change stays small along the real route', () => {
    const t = buildTrack(fixtures.dallas.geometry)
    let rot = null, maxStep = 0, wrapped = 0, prevH = null
    for (let m = 0; m < t.total; m += 0.005) {
      const h = pointAt(t, m).heading
      if (prevH != null && Math.abs(h - prevH) > 180) wrapped++ // what a raw rotate() + CSS transition would spin through
      prevH = h
      const next = unwrapAngle(rot, h)
      if (rot != null) maxStep = Math.max(maxStep, Math.abs(next - rot))
      rot = next
    }
    expect(wrapped).toBeGreaterThan(0) // this stretch really crosses north (the old bug's trigger)
    expect(maxStep).toBeLessThan(120)  // only real corners, never a 358-degree spin
  })
})

describe('maneuver icon agrees with the instruction', () => {
  it('text wins over a contradicting maneuver_type', () => {
    expect(maneuverOf({ maneuver_type: 'left', instruction: 'Turn right onto West Magnolia Avenue' })).toBe('right')
    expect(maneuverOf({ maneuver_type: 'right', instruction: 'Turn left onto Hemphill Street' })).toBe('left')
    expect(maneuverOf({ maneuver_type: 'keep-left', instruction: 'Keep right' })).toBe('keep-right')
    expect(maneuverOf({ maneuver_type: 'sharp-right', instruction: 'Turn sharp left onto South Freeway' })).toBe('sharp-left')
    expect(maneuverOf({ maneuver_type: 'straight', instruction: 'Bear slight left' })).toBe('slight-left')
    expect(maneuverOf({ maneuver_type: 'merge', instruction: 'Merge left onto I-35' })).toBe('merge-left')
  })
  it('leaves consistent or side-less steps alone', () => {
    expect(maneuverOf({ maneuver_type: 'right', instruction: 'Turn right onto Left Fork Road' })).toBe('right')
    expect(maneuverOf({ maneuver_type: 'exit-right', instruction: 'Take the exit toward Waco' })).toBe('exit-right')
    expect(maneuverOf({ maneuver_type: 'arrive', instruction: 'Arrive at your destination, on the left' })).toBe('arrive')
    expect(maneuverOf({ maneuver_type: 'uturn', instruction: 'Make a U-turn' })).toBe('uturn')
    expect(maneuverOf({})).toBe('straight')
  })
  it('left icons are the mirrored right icons, right icons are never mirrored', () => {
    const types = ['left', 'right', 'sharp-left', 'sharp-right', 'slight-left', 'slight-right', 'keep-left', 'keep-right',
      'exit-left', 'exit-right', 'exit', 'merge', 'merge-left', 'merge-right', 'straight', 'uturn', 'roundabout', 'depart', 'arrive']
    for (const t of types) {
      const { shape, mirror } = iconFor(t)
      expect(ICON_SHAPES[shape], t).toBeTruthy()
      expect(mirror, t).toBe(t.includes('left'))
      if (t.includes('left')) expect(shape).toBe(t.replace('left', 'right'))
    }
    expect(iconFor('weird').shape).toBe('straight')
  })
  for (const [name, fx] of Object.entries(fixtures)) {
    it(`${name} (${fx.provider}): every real turn icon points the way the road turns`, () => {
      let checked = 0
      for (const s of fx.steps) {
        const type = maneuverOf(s)
        if (!/^(left|right|sharp-|slight-)/.test(type)) continue
        const turn = turnAt(fx.geometry, s.span[0])
        if (turn == null || Math.abs(turn) < 30) continue
        expect(iconFor(type).mirror, `${s.instruction} (turn ${Math.round(turn)} deg)`).toBe(turn < 0)
        checked++
      }
      expect(checked).toBeGreaterThan(0)
    })
  }
})

describe('re-plan keeps the marker on the drawn route', () => {
  it('geometryKey identifies the same polyline across responses', () => {
    const a = fixtures.oklahomaCity.geometry
    expect(geometryKey(a.map((p) => [...p]))).toBe(geometryKey(a))
    expect(geometryKey(a.slice(1))).not.toBe(geometryKey(a))
    expect(geometryKey([])).toBe('')
  })
  it('resumeMile carries progress onto a new track only if it passes the truck', () => {
    const t = buildTrack(fixtures.oklahomaCity.geometry)
    const p = pointAt(t, 3)
    expect(resumeMile(t, p.lat, p.lon)).toBeCloseTo(3, 1)
    expect(resumeMile(t, p.lat + 1, p.lon)).toBeNull()
  })
})
