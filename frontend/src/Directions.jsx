import { useEffect, useRef } from 'react'
import { RISK_COLORS } from './risk'
import { ARROWS } from './nav'

const fmtTime = (d) => d.toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' })
const fmtMi = (mi) => (mi < 0.1 ? `${Math.round(mi * 5280)} ft` : `${mi.toFixed(mi < 10 ? 1 : 0)} mi`)

export default function Directions({ steps, focus, current, onFocus, onBack }) {
  const curRef = useRef(null)
  useEffect(() => { curRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }) }, [current])
  if (!steps.length) return <div className="muted small">No turn-by-turn steps for this route.</div>
  return (
    <div className="dirs">
      <div className="dirs-head">
        <span className="muted small">{steps.length} steps · click one to zoom to the turn</span>
        {focus != null && <button type="button" className="link" onClick={onBack}>⤢ Back to full route</button>}
      </div>
      <ol className="steps">
        {steps.map((s, k) => (
          <li key={k} ref={k === current ? curRef : null} className={`${k === focus ? 'on' : ''} ${k === current ? 'cur' : ''}`}>
            <button type="button" onClick={() => onFocus(k)}>
              <span className="arrow" style={{ borderColor: RISK_COLORS[s.level] }}>{ARROWS[s.maneuver_type] || '↑'}</span>
              <span className="step-body">
                <span className="step-text"><b className="muted">{k + 1}.</b> {s.instruction}</span>
                <span className="step-meta mono">
                  {s.distance_mi > 0 && <>{fmtMi(s.distance_mi)} · </>}mi {s.atMile.toFixed(0)} · {fmtTime(s.eta)}
                  <i style={{ background: RISK_COLORS[s.level] }} title={`Nearest checkpoint: ${s.level}`} />
                </span>
              </span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  )
}
