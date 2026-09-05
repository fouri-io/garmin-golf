"""Single home for cross-module constants.

These were previously duplicated across analyze.py / coach.py / progress.py / parse.py;
any module that needs one imports it from here so a tuning change lands everywhere at once.
"""

from __future__ import annotations

# --- Strokes Gained buckets (order matters: display order) ---
SG_CATS = ["offTee", "longApproach", "midApproach", "inside50", "putting"]
SG_LABELS = {"offTee": "Off-the-Tee", "longApproach": "Long approach (150+)",
             "midApproach": "Mid approach (50–150)", "inside50": "Inside 50",
             "putting": "Putting"}
SG_SHORT = {"offTee": "OTT", "longApproach": "Long", "midApproach": "Mid",
            "inside50": "In50", "putting": "Putt"}

# --- Data-quality gates ---
POLLUTION_DELTA = 3            # shotCountDelta above this = over-recorded; shot layer untrusted
MAX_PLAUSIBLE_SHOT_YDS = 400   # no golf shot travels this far
MAX_PLAUSIBLE_HOLE_YDS = 700   # a start point further than this from the pin isn't on the hole

# --- Windows / geometry ---
RECENT_N = 5                   # "current form" window (rounds)
GREENSIDE_YDS = 50.0           # within this of the pin counts as a greenside up-and-down chance
METERS_TO_YARDS = 1.09361
