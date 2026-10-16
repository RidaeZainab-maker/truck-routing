"""Risk classification for a checkpoint.

Threshold table (TODO: confirm exact numbers against the assessment brief):

| Level    | Wind / gust (mph)     | Rain (in/hr) | Snow (in/hr) |
|----------|-----------------------|--------------|--------------|
| Low      | < 20                  | < 0.1        | 0            |
| Moderate | 20-30                 | 0.1-0.3      | < 0.5        |
| High     | 30-45                 | 0.3-0.5      | 0.5-1        |
| Severe   | > 45                  | > 0.5        | > 1          |

Load rules (TODO: confirm):
  - Light loads (e.g. < 20,000 lb) are more wind-sensitive -> bump wind risk one level.
  - Heavy loads (e.g. > 70,000 lb) are more sensitive to snow/ice -> bump snow risk one level.
Final checkpoint level = worst of wind / rain / snow levels.
"""

LEVELS = ['Low', 'Moderate', 'High', 'Severe']
SCORES = {'Low': 0, 'Moderate': 1, 'High': 2, 'Severe': 3}


def classify_checkpoint(weather, load_weight_lb):
    """Return {'level': str, 'score': int, 'reasons': [str]}.

    TODO: implement using the table above.
    """
    raise NotImplementedError
