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
