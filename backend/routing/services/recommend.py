"""Pick the best route."""
from .risk import SCORES


def summarize_route(checkpoints, interval_miles=None):
    """Miles per risk level plus average score (1 = Low ... 5 = No Travel).

    Each stretch between two consecutive checkpoints counts as the worse of its two
    ends, using the real mile markers, so the level miles add up to the route length
    (the last stretch is usually shorter than the interval). `interval_miles` is kept
    for backward compatibility only.
    """
    keys = {'Low': 'low_miles', 'Moderate': 'moderate_miles', 'High': 'high_miles',
            'Severe': 'severe_miles', 'No Travel': 'no_travel_miles'}
    out = {k: 0.0 for k in keys.values()}
    if not checkpoints:
        return {**out, 'total_miles': 0.0, 'avg_score': 0}
    for a, b in zip(checkpoints, checkpoints[1:]):
        worst = max(a['risk']['level'], b['risk']['level'], key=SCORES.get)
        out[keys[worst]] += b['mile'] - a['mile']
    out = {k: round(v, 1) for k, v in out.items()}
    out['total_miles'] = round(checkpoints[-1]['mile'] - checkpoints[0]['mile'], 1)
    out['avg_score'] = round(sum(c['risk']['score'] for c in checkpoints) / len(checkpoints), 2)
    return out


def recommend(routes):
    """Return index of best route.

    Ranking (tie-break in order):
      1. fewest Severe miles
      2. fewest High miles
      3. lowest average risk score
      4. shortest duration
    Each route needs 'summary' (from summarize_route) and 'duration_s'.
    No Travel miles are ranked even before Severe miles, since they are worse.
    """
    def key(i):
        s, r = routes[i]['summary'], routes[i]
        # Last key: on an exact tie, a real truck route (ORS) beats an adjusted car route.
        return (s['no_travel_miles'], s['severe_miles'], s['high_miles'], s['avg_score'], r['duration_s'],
                r.get('provider') == 'osrm-car')
    return min(range(len(routes)), key=key) if routes else None
