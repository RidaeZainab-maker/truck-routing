import { useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import {
  CircleMarker, MapContainer, Marker, Pane, Polyline, Popup, ScaleControl, TileLayer, Tooltip, ZoomControl, useMap,
} from 'react-leaflet'
import NavMode from './NavMode'
import { LEVELS, RISK_COLORS, severity, splitAtMiles, worse } from './risk'

// Keyless tile services (CARTO basemaps now need an API key).
const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services'
const tile = (svc) => `${ESRI}/${svc}/MapServer/tile/{z}/{y}/{x}`
// native = deepest zoom the service has tiles for; beyond it Leaflet upscales instead of going blank.
const BASEMAPS = {
  Dark: { base: tile('Canvas/World_Dark_Gray_Base'), native: 16, roads: tile('Reference/World_Transportation'), roadsNative: 19,
    labels: tile('Canvas/World_Dark_Gray_Reference'), labelsNative: 16, attr: 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors' },
  Streets: { base: tile('World_Street_Map'), native: 19, attr: 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors' },
  Satellite: { base: tile('World_Imagery'), native: 19, roads: tile('Reference/World_Transportation'), roadsNative: 19,
    labels: tile('Reference/World_Boundaries_and_Places'), labelsNative: 19, attr: 'Imagery &copy; Esri, Maxar, Earthstar Geographics' },
}
const PANEL_PAD = { paddingTopLeft: [450, 50], paddingBottomRight: [60, 140] }
const fmtTime = (d) => d.toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' })

const pin = (cls, letter) => L.divIcon({ className: '', html: `<div class="pin ${cls}"><span>${letter}</span></div>`, iconSize: [30, 40], iconAnchor: [15, 38] })
const ORIGIN_ICON = pin('pin-a', 'A')
const DEST_ICON = pin('pin-b', 'B')
const STEP_ICON = L.divIcon({ className: '', html: '<div class="step-pin"></div>', iconSize: [22, 22], iconAnchor: [11, 11] })

// Fit to all routes when a new plan arrives or the user selects a route.
function FitBounds({ routes, fitNonce }) {
  const map = useMap()
  useEffect(() => {
    const pts = routes.flatMap((r) => r.geometry)
    if (pts.length) map.flyToBounds(pts, { ...PANEL_PAD, duration: 0.6 })
  }, [routes, fitNonce, map])
  useEffect(() => { if (import.meta.env.DEV) window.__saferouteMap = map }, [map]) // e2e screenshot hook
  return null
}

// Fly to a turn at street zoom and open its popup.
function FlyToStep({ step, markerRef }) {
  const map = useMap()
  const lat = step?.location[0], lon = step?.location[1]
  useEffect(() => {
    if (lat == null) return
    // Shift the target right so the turn isn't hidden behind the side panel.
    const z = 17
    const p = map.project([lat, lon], z).subtract([210, 0])
    map.flyTo(map.unproject(p, z), z, { duration: 0.8 })
    const t = window.setTimeout(() => markerRef.current?.openPopup(), 850)
    return () => window.clearTimeout(t)
  }, [lat, lon, map, markerRef])
  return null
}

export default function RouteMap({ result, scored, selected, onSelect, focusStep, fitNonce, navigating, navSteps, offset, onNavStep, onExitNav }) {
  const stepMarker = useRef(null)
  const [basemap, setBasemap] = useState('Dark')
  const [hover, setHover] = useState(null)
  // Navigation shows the Streets basemap; the user's own choice is kept and comes back on exit.
  const shownBasemap = navigating ? 'Streets' : basemap
  const routes = useMemo(() => result?.routes ?? [], [result])
  // Geometry split per checkpoint stretch: computed once per plan, not per slider tick.
  const pieces = useMemo(() => routes.map((r) => splitAtMiles(r.geometry, r.checkpoints.map((c) => c.mile))), [routes])
  const active = scored[selected]
  const navRoute = useMemo(() => (active && navigating ? { ...active, steps: navSteps } : null), [active, navigating, navSteps])
  const bm = BASEMAPS[shownBasemap]
  const tag = result?.departure

  // Per stretch: risk level (worse end, as in the mile breakdown) + 0..1 intensity from raw weather.
  const stretches = useMemo(() => {
    if (!active) return []
    return (pieces[selected] || []).map((pts, k) => {
      const a = active.cps[k], b = active.cps[k + 1] || a
      return { pts, level: worse(a.level, b.level), sev: (severity(a.weather) + severity(b.weather)) / 2 }
    })
  }, [active, pieces, selected])

  return (
    <MapContainer center={[39.5, -98.35]} zoom={5} maxZoom={19} zoomControl={false} preferCanvas className="map">
      <TileLayer key={`b-${shownBasemap}`} url={bm.base} attribution={bm.attr} maxNativeZoom={bm.native} maxZoom={19} keepBuffer={6} />
      {/* Highways, toned to soft grey on the dark map. */}
      <Pane name="roads" className={`roads-${shownBasemap}`} style={{ zIndex: 250, pointerEvents: 'none' }}>
        {bm.roads && <TileLayer key={`r-${shownBasemap}`} url={bm.roads} maxNativeZoom={bm.roadsNative} maxZoom={19} />}
      </Pane>
      {/* Labels sit above routes/heat (overlayPane 400) but below markers (600) and never catch clicks. */}
      <Pane name="labels" style={{ zIndex: 450, pointerEvents: 'none' }}>
        {bm.labels && <TileLayer key={`l-${shownBasemap}`} url={bm.labels} maxNativeZoom={bm.labelsNative} maxZoom={19} />}
      </Pane>
      {/* Heat: wide translucent strokes in a CSS-blurred pane -> soft continuous gradient. */}
      <Pane name="heat" style={{ zIndex: 380, filter: 'blur(9px)', pointerEvents: 'none' }}>
        {stretches.map((s, k) => (
          <Polyline key={`h-${tag}-${selected}-${k}`} positions={s.pts} interactive={false}
            pathOptions={{ color: RISK_COLORS[s.level], weight: 22 + 46 * s.sev, opacity: 0.28 + 0.5 * s.sev, lineCap: 'round' }} />
        ))}
      </Pane>
      <ZoomControl position="bottomright" />
      <ScaleControl position="bottomright" imperial metric={false} />
      <FitBounds routes={routes} fitNonce={fitNonce} />
      <FlyToStep step={focusStep} markerRef={stepMarker} />

      {scored.map((r, i) => i !== selected && (
        <Polyline key={`alt-${tag}-${i}`} positions={r.geometry}
          pathOptions={{ color: hover === i ? '#cbd5e1' : '#64748b', weight: hover === i ? 6 : 4, opacity: hover === i ? 0.9 : 0.6, dashArray: '7 9' }}
          eventHandlers={{ click: () => onSelect(i), mouseover: () => setHover(i), mouseout: () => setHover(null) }}>
          <Tooltip sticky className="dark-tip">Route {i + 1} · {r.distance_mi} mi · {r.duration_h} h — click to select</Tooltip>
        </Polyline>
      ))}

      {active && (
        <>
          <Polyline key={`glow-${tag}-${selected}`} positions={active.geometry} interactive={false}
            pathOptions={{ color: '#38bdf8', weight: 11, opacity: 0.22 }} />
          <Polyline key={`casing-${tag}-${selected}`} positions={active.geometry} interactive={false}
            pathOptions={{ color: '#020617', weight: 6.5, opacity: 0.9 }} />
          {stretches.map((s, k) => (
            <Polyline key={`seg-${tag}-${selected}-${k}`} positions={s.pts} interactive={false}
              pathOptions={{ color: RISK_COLORS[s.level], weight: 4, opacity: 1 }} />
          ))}
          {active.cps.map((c, k) => {
            const big = c.level !== 'Low'
            return (
              <CircleMarker key={`cp-${tag}-${selected}-${k}`} center={[c.lat, c.lon]} radius={big ? 6.5 : 3.5}
                pathOptions={{ color: big ? '#fff' : '#020617', weight: big ? 2 : 1, fillColor: RISK_COLORS[c.level], fillOpacity: 1 }}>
                <Tooltip direction="top" offset={[0, -6]} className="dark-tip">
                  Mile {c.mile} · {fmtTime(c.eta)} · <b style={{ color: RISK_COLORS[c.level] }}>{c.level}</b>
                </Tooltip>
                <Popup>
                  <div className="pop">
                    <div className="pop-head"><b>Mile {c.mile}</b><span className="badge" style={{ background: RISK_COLORS[c.level] }}>{c.level}</span></div>
                    <div className="muted">ETA <b>{fmtTime(c.eta)}</b></div>
                    <div>💨 Wind <b>{c.weather.wind_mph} mph</b> (gust {c.weather.gust_mph})</div>
                    <div>🌧️ Rain <b>{c.weather.rain_in_hr} in/hr</b></div>
                    <div>❄️ Snow <b>{c.weather.snow_in_hr} in/hr</b></div>
                    <div className="muted">🌡️ {c.weather.temp_f}°F</div>
                  </div>
                </Popup>
              </CircleMarker>
            )
          })}
        </>
      )}

      {active && focusStep && (
        <>
          {/* Highlight the stretch this step covers. */}
          <Polyline key={`stepseg-${focusStep.span.join('-')}`} interactive={false}
            positions={active.geometry.slice(focusStep.span[0], Math.max(focusStep.span[1], focusStep.span[0] + 1) + 1)}
            pathOptions={{ color: '#fde047', weight: 8, opacity: 0.85, lineCap: 'round' }} />
          <Marker key={`step-${focusStep.location.join(',')}`} ref={stepMarker} position={focusStep.location} icon={STEP_ICON}>
            <Popup autoPan={false}>
              <div className="pop">
                <div className="pop-head"><b>{focusStep.instruction}</b></div>
                {focusStep.road_name && <div className="muted">{focusStep.road_name}</div>}
                <div>Mile <b>{focusStep.atMile.toFixed(1)}</b> · ETA <b>{fmtTime(focusStep.eta)}</b></div>
                {focusStep.distance_mi > 0 && <div>Then {focusStep.distance_mi} mi</div>}
                <div>Weather risk nearby: <span className="badge" style={{ background: RISK_COLORS[focusStep.level] }}>{focusStep.level}</span></div>
              </div>
            </Popup>
          </Marker>
        </>
      )}

      {result && (
        <>
          <Marker position={[result.origin.lat, result.origin.lon]} icon={ORIGIN_ICON}>
            <Tooltip permanent direction="right" offset={[12, -22]} className="city-tip">{result.origin.query}</Tooltip>
          </Marker>
          <Marker position={[result.destination.lat, result.destination.lon]} icon={DEST_ICON}>
            <Tooltip permanent direction="right" offset={[12, -22]} className="city-tip">{result.destination.query}</Tooltip>
          </Marker>
        </>
      )}

      {navRoute && (
        <NavMode route={navRoute} departure={result.departure} offsetH={offset} onStep={onNavStep} onExit={onExitNav} />
      )}

      <div className={`map-ui ${navigating ? 'navigating' : ''}`}>
        <div className="basemaps">
          {Object.keys(BASEMAPS).map((k) => (
            <button key={k} type="button" className={k === shownBasemap ? 'on' : ''} onClick={() => setBasemap(k)} disabled={navigating}>{k}</button>
          ))}
        </div>
        {result && (
          <div className="map-legend">
            <div className="ml-title">Corridor weather risk</div>
            {LEVELS.map((l) => <div key={l}><i style={{ background: RISK_COLORS[l] }} />{l}</div>)}
            <div className="ml-note">Glow width/brightness = wind, rain &amp; snow intensity</div>
          </div>
        )}
      </div>
    </MapContainer>
  )
}
