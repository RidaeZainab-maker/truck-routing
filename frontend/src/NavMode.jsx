import { useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import { useMap } from 'react-leaflet'
import { RISK_COLORS } from './risk'
import {
  ARROWS, announceThresholds, buildTrack, currentStep, fmtDist, nextManeuver, pointAt, snapToTrack,
  stepMiles, upcomingCheckpoint,
} from './nav'

const SPEEDS = [1, 10, 60, 300]
const NAV_ZOOM = 17
const UI_MS = 250        // banner/bottom bar refresh (React state)
const LINE_MS = 200      // travelled/ahead polyline refresh
const fmtTime = (d) => d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
const fmtDur = (s) => (s >= 3600 ? `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min` : `${Math.max(1, Math.round(s / 60))} min`)

const truckIcon = () => L.divIcon({
  className: '', iconSize: [44, 44], iconAnchor: [22, 22],
  html: '<div class="nav-truck"><svg viewBox="0 0 44 44"><circle cx="22" cy="22" r="20" fill="rgba(26,115,232,0.18)"/><path d="M22 7 L33 34 L22 28 L11 34 Z" fill="#1a73e8" stroke="#fff" stroke-width="2.5" stroke-linejoin="round"/></svg></div>',
})

function say(text, muted) {
  if (muted || typeof window === 'undefined' || !window.speechSynthesis) return
  window.speechSynthesis.cancel()
  window.speechSynthesis.speak(new window.SpeechSynthesisUtterance(text))
}

/**
 * Simulated (or GPS) turn-by-turn drive. Everything that changes per frame (truck
 * marker, rotation, camera, route lines) is updated imperatively on Leaflet objects
 * inside one requestAnimationFrame loop; React only re-renders the small banner and
 * bottom bar ~4x per second.
 */
export default function NavMode({ route, departure, offsetH, onStep, onExit }) {
  const map = useMap()
  const track = useMemo(() => buildTrack(route.geometry), [route.geometry])
  const miles = useMemo(() => stepMiles(track, route.steps), [track, route.steps])
  const pace = (route.distance_mi / Math.max(route.duration_s, 1)) // real mi per second
  const scaleMi = route.distance_mi / Math.max(track.total, 1e-9) // track miles -> reported route miles

  const [playing, setPlaying] = useState(true)
  const [mult, setMult] = useState(10)
  const [muted, setMuted] = useState(false)
  const [gps, setGps] = useState(false)
  const [ui, setUi] = useState({ mile: 0, wall: 0 })
  const [toast, setToast] = useState(null)
  const live = useRef({ mile: 0, playing: true, mult: 10, muted: false, gps: false, idx: 0, gpsHeading: null })
  const uiRef = useRef(null)
  const onStepRef = useRef(onStep)
  // Mirror UI state into the ref the animation loop reads (no loop restart on change).
  useEffect(() => {
    Object.assign(live.current, { playing, mult, muted, gps })
    onStepRef.current = onStep
  }, [playing, mult, muted, gps, onStep])

  // Overlay controls must not drag/zoom the map.
  useEffect(() => {
    if (uiRef.current) { L.DomEvent.disableClickPropagation(uiRef.current); L.DomEvent.disableScrollPropagation(uiRef.current) }
  }, [])

  useEffect(() => {
    const st = live.current
    st.mile = 0
    const pane = map.getPane('nav') || map.createPane('nav')
    pane.style.zIndex = 430
    const travelled = L.polyline([], { pane: 'nav', color: '#475569', weight: 7, opacity: 0.75, interactive: false }).addTo(map)
    const ahead = L.polyline(route.geometry, { pane: 'nav', color: '#1a73e8', weight: 9, opacity: 0.95, interactive: false }).addTo(map)
    const casing = L.polyline(route.geometry, { pane: 'nav', color: '#0b3d91', weight: 13, opacity: 0.5, interactive: false })
    casing.addTo(map); ahead.bringToFront()
    const start = pointAt(track, 0)
    const marker = L.marker([start.lat, start.lon], { icon: truckIcon(), interactive: false, zIndexOffset: 1000 }).addTo(map)
    const camera = (lat, lon, animate) => {
      // Keep the truck in the visible area right of the side panel, slightly below centre.
      const z = map.getZoom()
      const c = map.unproject(map.project([lat, lon], z).subtract([225, 110]), z)
      map.setView(c, z, { animate })
    }
    map.setZoom(NAV_ZOOM, { animate: false })
    camera(start.lat, start.lon, false)
    say(`Starting navigation. ${route.steps[0]?.instruction || ''}`, st.muted)

    const announced = new Set(), warned = new Set()
    let raf, last = performance.now(), lastLine = 0, lastUi = 0, lastStep = -1
    const frame = (now) => {
      const dt = Math.min((now - last) / 1000, 0.25)
      last = now
      if (st.playing && !st.gps) st.mile = Math.min(track.total, st.mile + (pace / scaleMi) * st.mult * dt)
      const p = pointAt(track, st.mile)
      st.idx = p.idx
      marker.setLatLng([p.lat, p.lon])
      const el = marker.getElement()?.firstChild
      if (el) el.style.transform = `rotate(${st.gps && st.gpsHeading != null ? st.gpsHeading : p.heading}deg)`
      camera(p.lat, p.lon, false)

      if (now - lastLine > LINE_MS) {
        lastLine = now
        travelled.setLatLngs([...route.geometry.slice(0, p.idx + 1), [p.lat, p.lon]])
        const rest = [[p.lat, p.lon], ...route.geometry.slice(p.idx + 1)]
        ahead.setLatLngs(rest); casing.setLatLngs(rest)
      }

      // Voice: early (~0.5 mi) and at-the-turn announcements, scaled with sim speed.
      const speed = (pace / scaleMi) * (st.gps ? 1 : st.mult)
      const th = announceThresholds(speed)
      const nx = nextManeuver(miles, st.mile)
      if (nx) {
        const s = route.steps[nx.index]
        if (nx.distance <= th.early && nx.distance > th.now && !announced.has(`e${nx.index}`)) {
          announced.add(`e${nx.index}`)
          say(`In ${fmtDist(nx.distance * scaleMi).replace('mi', 'miles').replace('ft', 'feet')}, ${s.instruction}`, st.muted)
        } else if (nx.distance <= th.now && !announced.has(`n${nx.index}`)) {
          announced.add(`n${nx.index}`); announced.add(`e${nx.index}`)
          say(s.instruction, st.muted)
        }
      }
      // Weather warning before a Moderate+ checkpoint.
      const cp = upcomingCheckpoint(route.cps, st.mile * scaleMi)
      if (cp && cp.level !== 'Low' && !warned.has(cp.mile) && cp.mile - st.mile * scaleMi <= Math.max(5, speed * scaleMi * 10)) {
        warned.add(cp.mile)
        setToast({ level: cp.level, text: `${cp.level} weather risk ahead at mile ${cp.mile} — wind ${cp.weather.wind_mph} mph, rain ${cp.weather.rain_in_hr} in/hr, snow ${cp.weather.snow_in_hr} in/hr` })
        say(`Caution: ${cp.level} weather risk ahead`, st.muted)
        window.setTimeout(() => setToast(null), 5000)
      }

      const k = currentStep(miles, st.mile)
      if (k !== lastStep) { lastStep = k; onStepRef.current?.(k) }
      if (now - lastUi > UI_MS) { lastUi = now; setUi({ mile: st.mile, wall: Date.now() }) }
      if (st.mile >= track.total && !announced.has('end')) { announced.add('end'); say('You have arrived at your destination', st.muted); setPlaying(false) }
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => {
      cancelAnimationFrame(raf)
      ;[travelled, ahead, casing, marker].forEach((l) => l.remove())
      window.speechSynthesis?.cancel()
    }
  }, [map, route, track, miles, pace, scaleMi])

  // Optional real GPS (works on devices with location; the sim pauses while it is on).
  useEffect(() => {
    if (!gps || !navigator.geolocation) return undefined
    const id = navigator.geolocation.watchPosition((pos) => {
      live.current.mile = snapToTrack(track, pos.coords.latitude, pos.coords.longitude, live.current.idx)
      live.current.gpsHeading = Number.isFinite(pos.coords.heading) ? pos.coords.heading : null
    }, () => setGps(false), { enableHighAccuracy: true, maximumAge: 1000 })
    return () => navigator.geolocation.clearWatch(id)
  }, [gps, track])

  const mile = ui.mile
  const frac = track.total ? mile / track.total : 0
  const nx = nextManeuver(miles, mile)
  const step = nx ? route.steps[nx.index] : route.steps[route.steps.length - 1]
  const then = nx && route.steps[nx.index + 1]
  const remainS = route.duration_s * (1 - frac)
  const simNow = gps ? ui.wall : new Date(departure).getTime() + offsetH * 3600e3 + frac * route.duration_s * 1000
  const cp = upcomingCheckpoint(route.cps, mile * scaleMi)

  return (
    <div ref={uiRef} className="nav-ui">
      <div className="nav-banner">
        <div className="nav-arrow">{ARROWS[step?.maneuver_type] || '↑'}</div>
        <div className="nav-main">
          <div className="nav-dist">{nx ? `In ${fmtDist(nx.distance * scaleMi)}` : 'Arrived'}</div>
          <div className="nav-instr">{step?.instruction || 'Destination'}</div>
        </div>
        {then && <div className="nav-then">Then {ARROWS[then.maneuver_type] || '↑'} {then.instruction}</div>}
      </div>

      {toast && <div className="nav-toast" style={{ borderColor: RISK_COLORS[toast.level] }}>⚠ {toast.text}</div>}

      <div className="nav-bottom">
        <div className="nav-stats">
          <div><b>{fmtDur(remainS)}</b><span>remaining</span></div>
          <div><b>{(route.distance_mi * (1 - frac)).toFixed(1)} mi</b><span>to go</span></div>
          <div><b>{fmtTime(new Date(simNow + remainS * 1000))}</b><span>ETA</span></div>
          {cp && (
            <div><b className="nav-chip" style={{ background: RISK_COLORS[cp.level] }}>{cp.level}</b>
              <span>risk @ mi {Math.round(cp.mile)}</span></div>
          )}
        </div>
        <div className="nav-controls">
          <div className="seg">
            {SPEEDS.map((s) => <button key={s} type="button" className={s === mult ? 'on' : ''} onClick={() => setMult(s)} disabled={gps}>{s}×</button>)}
          </div>
          <button type="button" className="nav-btn" onClick={() => setPlaying((p) => !p)} disabled={gps}>{playing ? '⏸ Pause' : '▶ Resume'}</button>
          <button type="button" className={`nav-btn ${muted ? '' : 'on'}`} onClick={() => setMuted((m) => !m)}>{muted ? '🔇' : '🔊'}</button>
          <button type="button" className={`nav-btn ${gps ? 'on' : ''}`} onClick={() => setGps((g) => !g)} title="Follow device location">📍 GPS</button>
          <button type="button" className="nav-btn exit" onClick={onExit}>✕ Exit</button>
        </div>
      </div>
    </div>
  )
}
