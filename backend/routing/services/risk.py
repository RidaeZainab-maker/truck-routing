"""Risk classification for a checkpoint.

Threshold table (from the assessment brief):

| Condition | Low       | Moderate  | High      | Severe    | No Travel |
|-----------|-----------|-----------|-----------|-----------|-----------|
| Wind      | <25 mph   | 25-34     | 35-44     | 45-54     | >=55 mph  |
| Rain      | <0.10 in/hr | 0.10-0.25 | 0.25-0.50 | 0.50-1.00 | >1.00   |
| Snow      | <0.5 in/hr | 0.5-1.0  | 1.0-2.0   | 2.0-3.0   | >3.0      |

Load rules (from the brief):
  - >=55 mph wind -> No Travel for any load
  - 45-54 mph wind + load >30,000 lb -> No Travel
  - 35-44 mph wind + load >40,000 lb -> Severe
Final checkpoint level = worst of wind / rain / snow levels (after load rules).
"""

LEVELS = ['Low', 'Moderate', 'High', 'Severe', 'No Travel']
SCORES = {'Low': 1, 'Moderate': 2, 'High': 3, 'Severe': 4, 'No Travel': 5}  # 1-5 scale


def classify_checkpoint(weather, load_weight_lb):
    """Return {'level': str, 'score': int, 'reasons': [str]}.

    """
    wind = max(weather.get('wind_mph') or 0, 0)
    rain = weather.get('rain_in_hr') or 0
    snow = weather.get('snow_in_hr') or 0
    load = load_weight_lb or 0

    # Lower edge of Moderate, High, Severe, No Travel for each condition.
    # Edges are inclusive (25 mph is Moderate), except the top rain/snow
    # band, which the brief writes as strictly "> 1.00" / "> 3.0".
    wind_lvl = _band(wind, [25, 35, 45, 55])
    rain_lvl = _band(rain, [0.10, 0.25, 0.50], no_travel_above=1.00)
    snow_lvl = _band(snow, [0.5, 1.0, 2.0], no_travel_above=3.0)

    reasons = []
    # Load rules: heavy trucks are more stable but harder to control when they do slide;
    # the brief makes high wind stricter for heavy loads.
    if 45 <= wind < 55 and load > 30000:
        wind_lvl = 'No Travel'
        reasons.append(f'{wind:.0f} mph wind with {load:,.0f} lb load')
    elif 35 <= wind < 45 and load > 40000:
        wind_lvl = _worse(wind_lvl, 'Severe')
        reasons.append(f'{wind:.0f} mph wind with {load:,.0f} lb load')

    for name, lvl, val, unit in [('Wind', wind_lvl, wind, 'mph'),
                                 ('Rain', rain_lvl, rain, 'in/hr'),
                                 ('Snow', snow_lvl, snow, 'in/hr')]:
        if lvl != 'Low':
            reasons.append(f'{name} {val:g} {unit} -> {lvl}')

    level = max([wind_lvl, rain_lvl, snow_lvl], key=SCORES.get)
    return {'level': level, 'score': SCORES[level], 'reasons': reasons}


def _band(value, edges, no_travel_above=None):
    """Map a value onto Low..No Travel using lower-edge thresholds."""
    if no_travel_above is not None and value > no_travel_above:
        return 'No Travel'
    level = 'Low'
    for edge, name in zip(edges, LEVELS[1:]):
        if value >= edge:
            level = name
    return level


def _worse(a, b):
    return a if SCORES[a] >= SCORES[b] else b
