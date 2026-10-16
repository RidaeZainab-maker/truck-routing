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
SCORES = {'Low': 0, 'Moderate': 1, 'High': 2, 'Severe': 3, 'No Travel': 4}


def classify_checkpoint(weather, load_weight_lb):
    """Return {'level': str, 'score': int, 'reasons': [str]}.

    TODO: implement using the table above.
    """
    raise NotImplementedError
