import { describe, expect, it } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import TurnIcon from './TurnIcon'

const html = (step) => renderToStaticMarkup(createElement(TurnIcon, { step }))

describe('TurnIcon', () => {
  it('mirrors left maneuvers and only those', () => {
    expect(html({ maneuver_type: 'left', instruction: 'Turn left onto Hemphill Street' })).toContain('scale(-1 1)')
    expect(html({ maneuver_type: 'right', instruction: 'Turn right onto West Magnolia Avenue' })).not.toContain('scale(-1 1)')
    expect(html({ maneuver_type: 'keep-right', instruction: 'Keep right' })).not.toContain('scale(-1 1)')
    expect(html({ maneuver_type: 'keep-left', instruction: 'Keep left onto US 287 Bus' })).toContain('scale(-1 1)')
  })
  it('follows the text when the type contradicts it', () => {
    const out = html({ maneuver_type: 'left', instruction: 'Turn right onto West Magnolia Avenue' })
    expect(out).toContain('data-maneuver="right"')
    expect(out).not.toContain('scale(-1 1)')
  })
  it('is an SVG, not a font glyph', () => {
    expect(html({ maneuver_type: 'straight' })).toMatch(/^<svg[^>]*viewBox="0 0 24 24"/)
  })
})
