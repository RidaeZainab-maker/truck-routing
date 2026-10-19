"""Normalise turn-by-turn steps from ORS and OSRM into one shape:

{instruction, road_name, distance_mi, duration_s, maneuver_type, location [lat, lon], span [i0, i1]}

`span` indexes into the route geometry so the UI can highlight the step's stretch.
"""
M_PER_MI = 1609.34

# ORS instruction type codes -> our maneuver_type
ORS_TYPES = {0: 'left', 1: 'right', 2: 'sharp-left', 3: 'sharp-right', 4: 'slight-left', 5: 'slight-right',
             6: 'straight', 7: 'roundabout', 8: 'roundabout', 9: 'uturn', 10: 'arrive', 11: 'depart',
             12: 'keep-left', 13: 'keep-right'}


def from_ors(segments, geometry):
    """ORS GeoJSON `segments[].steps` (via-point routes have one segment per leg)."""
    raw = [s for seg in segments for s in seg.get('steps', [])]
    out = []
    for k, s in enumerate(raw):
        mtype = ORS_TYPES.get(s.get('type'), 'straight')
        if mtype == 'arrive' and k != len(raw) - 1:
            continue  # "arrive" at an intermediate detour via-point
        if mtype == 'depart' and out:
            continue  # leg 2 "depart" from the via-point
        i0, i1 = (s.get('way_points') or [0, 0])[:2]
        name = s.get('name') or ''
        out.append(_step(s.get('instruction') or '', '' if name == '-' else name, s.get('distance', 0),
                         s.get('duration', 0), mtype, geometry[min(i0, len(geometry) - 1)], [i0, i1]))
    return out


def osrm_road(step):
    ref = (step.get('ref') or '').split(';')[0].strip()
    name = step.get('name') or ''
    if ref:
        ref = ref.replace(' ', '-')  # "I 35" -> "I-35"
        return f'{ref} ({name})' if name and name != ref else ref
    return name


def osrm_instruction(step):
    """Readable text for an OSRM step (OSRM gives maneuver type/modifier, not text)."""
    m = step.get('maneuver', {})
    typ, mod = m.get('type', ''), m.get('modifier', '')
    road = osrm_road(step)
    toward = (step.get('destinations') or '').split(':')[-1].split(',')[0].strip()
    onto = f' onto {road}' if road else ''
    dirn = mod.replace('uturn', 'U-turn') if mod else ''
    if typ == 'depart':
        return f'Head out on {road}' if road else 'Depart'
    if typ == 'arrive':
        return 'Arrive at your destination' + (f', on the {mod}' if mod in ('left', 'right') else '')
    if mod == 'uturn':
        return f'Make a U-turn{onto}'
    if typ == 'turn':
        return f'Turn {dirn}{onto}' if mod != 'straight' else f'Continue straight{onto}'
    if typ in ('new name', 'continue'):
        return f'Continue onto {road}' if road else 'Continue'
    if typ == 'merge':
        return f'Merge{onto}' if road else f'Merge {dirn}'.strip()
    if typ == 'on ramp':
        return f'Take the ramp{onto}' + (f' toward {toward}' if toward else '')
    if typ == 'off ramp':
        return 'Take the exit' + (f' toward {toward}' if toward else onto)
    if typ == 'fork':
        side = 'left' if 'left' in mod else 'right' if 'right' in mod else ''
        return f'Keep {side} at the fork{onto}'.replace('Keep  ', 'Keep ') + (f' toward {toward}' if toward and not road else '')
    if typ == 'end of road':
        return f'At the end of the road, turn {dirn}{onto}'
    if typ in ('roundabout', 'rotary', 'roundabout turn'):
        ex = m.get('exit')
        return f'At the roundabout, take exit {ex}{onto}' if ex else f'Enter the roundabout{onto}'
    return f'Continue {dirn}{onto}'.replace('Continue  ', 'Continue ').strip() if (dirn or road) else 'Continue'


def osrm_maneuver(step):
    m = step.get('maneuver', {})
    typ, mod = m.get('type', ''), (m.get('modifier') or '').replace(' ', '-')
    if typ in ('depart', 'arrive'):
        return typ
    if mod == 'uturn':
        return 'uturn'
    if typ in ('roundabout', 'rotary', 'roundabout turn'):
        return 'roundabout'
    if typ == 'off ramp':
        return 'exit'
    if typ in ('on ramp', 'merge'):
        return 'merge'
    if typ == 'fork':
        return 'keep-left' if 'left' in mod else 'keep-right'
    return mod or 'straight'


def from_osrm(legs, geometry):
    """OSRM `legs[].steps` (needs steps=true). Spans found by a forward nearest-point scan."""
    raw = []
    for li, leg in enumerate(legs):
        for s in leg.get('steps', []):
            typ = s.get('maneuver', {}).get('type')
            if (typ == 'arrive' and li < len(legs) - 1) or (typ == 'depart' and li > 0):
                continue
            if s.get('maneuver', {}).get('type') in ('notification', 'use lane') or (
                    s.get('distance', 0) == 0 and typ not in ('arrive', 'depart')):
                continue
            raw.append(s)
    out, idx = [], 0
    for s in raw:
        lon, lat = s['maneuver']['location']
        idx = _nearest_forward(geometry, idx, lon, lat)
        out.append(_step(osrm_instruction(s), osrm_road(s), s.get('distance', 0), s.get('duration', 0),
                         osrm_maneuver(s), geometry[idx], [idx, idx]))
    for a, b in zip(out, out[1:]):
        a['span'][1] = b['span'][0]
    return out


def _nearest_forward(geometry, start, lon, lat, window=4000):
    best, best_d = start, float('inf')
    for i in range(start, min(len(geometry), start + window)):
        x, y = geometry[i]
        d = (x - lon) ** 2 + (y - lat) ** 2
        if d < best_d:
            best, best_d = i, d
            if d < 1e-12:
                break
    return best


def _step(text, road, dist_m, dur_s, mtype, lonlat, span):
    return {'instruction': text, 'road_name': road, 'distance_mi': round(dist_m / M_PER_MI, 2),
            'duration_s': round(dur_s), 'maneuver_type': mtype,
            'location': [round(lonlat[1], 5), round(lonlat[0], 5)], 'span': span}
