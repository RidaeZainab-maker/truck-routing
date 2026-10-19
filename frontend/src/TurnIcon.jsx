import { ICON_SHAPES, iconFor, maneuverOf } from './nav'

/**
 * Maneuver icon as inline SVG (font-independent). Pass the step: the icon is chosen by
 * maneuverOf(step), the same rule that keeps it in line with the instruction text.
 */
export default function TurnIcon({ step, type, size = 24, className = '' }) {
  const t = type ?? maneuverOf(step)
  const { shape, mirror } = iconFor(t)
  const s = ICON_SHAPES[shape]
  return (
    <svg className={`turn-icon ${className}`} width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"
      role="img" aria-label={t} data-maneuver={t}>
      <g transform={mirror ? 'translate(24 0) scale(-1 1)' : undefined}>
        {(s.faint || []).map((d) => <path key={d} d={d} opacity="0.35" />)}
        {s.main.map((d) => <path key={d} d={d} />)}
        {s.dot && <circle cx="12" cy="20" r="2.2" fill="currentColor" stroke="none" />}
      </g>
    </svg>
  )
}
