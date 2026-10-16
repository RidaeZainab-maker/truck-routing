"""Pick the best route."""


def summarize_route(checkpoints, interval_miles):
    """Return {severe_miles, high_miles, avg_score} for a route.

    TODO: each checkpoint represents ~interval_miles of road.
    """
    raise NotImplementedError


def recommend(routes):
    """Return index of best route.

    Ranking (tie-break in order):
      1. fewest Severe miles
      2. fewest High miles
      3. lowest average risk score
      4. shortest duration
    TODO: hint - sorted(..., key=lambda r: (a, b, c, d)).
    """
    raise NotImplementedError
