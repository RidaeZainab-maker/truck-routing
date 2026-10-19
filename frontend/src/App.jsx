import { useEffect, useMemo, useRef, useState } from 'react'
import RouteMap from './RouteMap'
import Directions from './Directions'
import { LEVELS, RISK_COLORS, enrichSteps, scoreRoutes } from './risk'
import { geometryKey } from './nav'
import './App.css'

// VITE_API_URL unset -> local Django dev server; set to '' -> same origin (single-container build).
const API = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000').replace(/\/$/, '')
const PROVIDER_LABEL = { 'ors-hgv': 'ORS truck (HGV)', 'osrm-car': 'OSRM car' }

const toLocalInput = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
const fmtTime = (d) => d.toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' })

function RiskBar({ miles }) {
  const parts = [['Low', miles.Low], ['Moderate', miles.Moderate], ['High', miles.High],
    ['Severe', miles.Severe + miles['No Travel']]]
  const total = parts.reduce((a, [, m]) => a + m, 0) || 1
  return (
    <>
      <div className="riskbar">
        {parts.map(([lvl, m]) => m > 0 && (
          <span key={lvl} style={{ width: `${(m / total) * 100}%`, background: RISK_COLORS[lvl] }} title={`${lvl}: ${m} mi`} />
        ))}
      </div>
      <div className="riskbar-legend mono">
        {parts.map(([lvl, m]) => <span key={lvl}><i style={{ background: RISK_COLORS[lvl] }} />{lvl.slice(0, 3)} {Math.round(m)}</span>)}
      </div>
    </>
  )
}

export default function App() {
  const [status, setStatus] = useState('checking')
  const [form, setForm] = useState(() => ({
    origin: 'Dallas, TX', destination: 'Chicago, IL', departure: toLocalInput(new Date()), loadWeight: '35000',
  }))
  const [interval, setInterval] = useState(25)
  const [offset, setOffset] = useState(0)          // 0-48 h, scored client-side
  const [playing, setPlaying] = useState(false)
  const [result, setResult] = useState(null)
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [tab, setTab] = useState('routes')        // routes | directions
  const [focusStep, setFocusStep] = useState(null) // index of the step the map is zoomed to
  const [fitNonce, setFitNonce] = useState(0)      // bump to refit the map to all routes
  const [elapsed, setElapsed] = useState(0)
  const [navigating, setNavigating] = useState(false)
  const [navStep, setNavStep] = useState(0)

  // Elapsed-seconds counter for the loading skeleton.
  useEffect(() => {
    if (!loading) return undefined
    const t0 = Date.now()
    const t = window.setInterval(() => setElapsed((Date.now() - t0) / 1000), 100)
    return () => { window.clearInterval(t); setElapsed(0) }
  }, [loading])

  useEffect(() => {
    fetch(`${API}/api/health`).then((r) => r.json()).then((d) => setStatus(d.status)).catch(() => setStatus('offline'))
  }, [])

  // "Play" steps the slider through 48 h; purely local, no network.
  useEffect(() => {
    if (!playing) return undefined
    const t = window.setInterval(() => setOffset((o) => (o >= 48 ? 0 : o + 1)), 400)
    return () => window.clearInterval(t)
  }, [playing])

  const update = (key) => (e) => setForm({ ...form, [key]: e.target.value })

  // Only the newest plan may land: clicking 10 -> 25 -> 50 fires three requests whose
  // answers can arrive out of order; older ones are aborted and ignored.
  const planReq = useRef(null)
  const plan = async (every = interval) => {
    planReq.current?.abort()
    const req = new AbortController()
    planReq.current = req
    // While navigating, stay on the route being driven if the new plan still has it.
    const keepKey = navigating && result?.routes[selected] ? geometryKey(result.routes[selected].geometry) : null
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${API}/api/routes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: req.signal,
        body: JSON.stringify({
          origin: form.origin, destination: form.destination,
          departure: new Date(form.departure).toISOString(),
          load_weight_lb: Number(form.loadWeight), interval_miles: every,
        }),
      })
      const data = await res.json()
      if (planReq.current !== req) return
      if (!res.ok) throw new Error(data.error || JSON.stringify(data))
      const kept = keepKey ? data.routes.findIndex((r) => geometryKey(r.geometry) === keepKey) : -1
      setResult(data)
      setFocusStep(null)
      setOffset(0)
      setSelected(kept >= 0 ? kept : data.recommended_route_index)
    } catch (err) {
      if (planReq.current === req && err.name !== 'AbortError') setError(err.message)
    } finally {
      if (planReq.current === req) setLoading(false)
    }
  }

  const selectRoute = (i) => { if (navigating) return; setSelected(i); setFocusStep(null); setFitNonce((n) => n + 1) }
  const startNav = () => { setPlaying(false); setFocusStep(null); setNavStep(0); setTab('directions'); setNavigating(true) }
  const exitNav = () => { setNavigating(false); setFitNonce((n) => n + 1) }
  const routes = useMemo(() => result?.routes ?? [], [result])
  // Re-score for the slider offset: cheap (a few hundred checkpoints), no API call.
  const { scored, best } = useMemo(
    () => (result ? scoreRoutes(routes, offset, result.load_weight_lb)
      : { scored: [], best: null }),
    [routes, offset, result],
  )
  const activeSteps = useMemo(
    () => (scored[selected] ? enrichSteps(scored[selected], result.departure, offset) : []),
    [scored, selected, result, offset],
  )

  return (
    <div className="app">
      <RouteMap result={result} scored={scored} selected={selected} onSelect={selectRoute}
        focusStep={!navigating && focusStep != null ? activeSteps[focusStep] : null} fitNonce={fitNonce}
        navigating={navigating} navSteps={activeSteps} offset={offset} onNavStep={setNavStep} onExitNav={exitNav} />

      <aside className="hud panel">
        <header className="hud-head">
          <h1><span className={`dot ${status === 'ok' ? 'ok' : 'bad'}`} />SPOTTER <em>SafeRoute</em></h1>
          <span className="pill mono">API {status}</span>
        </header>

        <form className="form" onSubmit={(e) => { e.preventDefault(); plan() }}>
          <label>Origin<input value={form.origin} onChange={update('origin')} required /></label>
          <label>Destination<input value={form.destination} onChange={update('destination')} required /></label>
          <label>Departure<input type="datetime-local" value={form.departure} onChange={update('departure')} required /></label>
          <label>Load (lb)<input type="number" min="0" value={form.loadWeight} onChange={update('loadWeight')} required /></label>
          <label className="span2">Checkpoint every
            <div className="seg">
              {[10, 25, 50].map((m) => (
                <button type="button" key={m} className={interval === m ? 'on' : ''}
                  onClick={() => { setInterval(m); if (result) plan(m) }}>{m} mi</button>
              ))}
            </div>
          </label>
          <button className="primary span2" disabled={loading}>{loading ? 'Planning routes…' : 'Plan routes'}</button>
        </form>

        {error && <div className="alert error">{error}</div>}
        {result?.notice && <div className="alert warn">⚠ {result.notice}</div>}

        {loading && (
          <div className="cards" aria-busy="true">
            <div className="muted small mono">Geocoding, routing (truck + standby car) and forecasts in parallel… {elapsed.toFixed(1)} s</div>
            <div className="progress"><span /></div>
            {[0, 1, 2].map((k) => <div key={k} className="card skeleton"><i /><i /><i /></div>)}
          </div>
        )}

        {result && !loading && (
          <div className="seg tabs">
            <button type="button" className={tab === 'routes' ? 'on' : ''} onClick={() => setTab('routes')}>Routes</button>
            <button type="button" className={tab === 'directions' ? 'on' : ''} onClick={() => setTab('directions')}>
              Directions{scored[selected] ? ` · Route ${selected + 1}` : ''}
            </button>
          </div>
        )}

        {result && !loading && scored[selected] && !navigating && (
          <button type="button" className="go" onClick={startNav}>▶ GO · Start navigation (Route {selected + 1})</button>
        )}
        {navigating && <button type="button" className="nav-btn exit" onClick={exitNav}>✕ Exit navigation</button>}

        {!loading && tab === 'directions' && result && (
          <Directions steps={activeSteps} focus={focusStep} current={navigating ? navStep : null}
            onFocus={(k) => { if (!navigating) setFocusStep(k) }}
            onBack={() => { setFocusStep(null); setFitNonce((n) => n + 1) }} />
        )}

        {!loading && tab === 'routes' && (
        <div className="cards">
          {scored.map((r, i) => (
            <div key={i} role="button" tabIndex={0} className={`card ${i === selected ? 'active' : ''}`}
              onClick={() => selectRoute(i)} onKeyDown={(e) => e.key === 'Enter' && selectRoute(i)}>
              <div className="card-top">
                <b>Route {i + 1}</b>
                {i === best && <span className="rec">★ RECOMMENDED</span>}
                <span className="prov mono">{PROVIDER_LABEL[r.provider] || r.provider}</span>
              </div>
              <div className="card-stats">
                <b>{r.duration_h} h</b>{r.duration_adjusted && <span className="muted" title={`Car time ${(r.car_duration_s / 3600).toFixed(1)} h, scaled to truck speed`}> (truck-adj.)</span>} · {r.distance_mi} mi · avg risk <b className="sky">{r.avg.toFixed(1)}</b><span className="muted">/5</span>
              </div>
              <div className="muted small">
                Arrive {fmtTime(new Date(new Date(result.departure).getTime() + (offset * 3600 + r.duration_s) * 1000))}
                {r.miles['No Travel'] > 0 && <span className="nt"> · ⛔ {r.miles['No Travel']} mi No Travel</span>}
              </div>
              <RiskBar miles={r.miles} />
            </div>
          ))}
        </div>
        )}

        {result && (
          <div className="legend">
            {LEVELS.map((l) => <span key={l}><i style={{ background: RISK_COLORS[l] }} />{l}</span>)}
          </div>
        )}
      </aside>

      {result && !navigating && (
        <div className="hud scrubber">
          <div className="scrub-head">
            <span className="label">Weather heatmap · departure shift (0–48 h)</span>
            <button type="button" className="link" onClick={() => setPlaying((p) => !p)}>{playing ? '⏸ Pause' : '▶ Play'}</button>
            <span className="pill mono">+{offset} h · {fmtTime(new Date(new Date(result.departure).getTime() + offset * 3600e3))}</span>
          </div>
          <input type="range" min="0" max="48" step="1" value={offset}
            onChange={(e) => { setPlaying(false); setOffset(Number(e.target.value)) }} />
          <div className="ticks"><span>Now</span><span>+12 h</span><span>+24 h</span><span>+36 h</span><span>+48 h</span></div>
        </div>
      )}
    </div>
  )
}
