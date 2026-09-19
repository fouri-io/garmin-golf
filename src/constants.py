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

# --- Approach Ladder / Green Zone (cuts live in config/analysis.json -> approachLadder) ---
PUTTER_CLUB_TYPE_ID = 23       # Garmin clubTypeId for the putter; catches the fringe putts
                               # shot_type='PUTT' misses (Garmin only marks green putts)
GREEN_ZONE_LABEL = "Green Zone %"
LEAVE_CLASSES = ["greenPutted", "fringePutted", "chipped", "pitch", "long"]
LEAVE_CLASS_LABELS = {
    "greenPutted":  "On the green, putting",
    "fringePutted": "Fringe or apron, putting",
    "chipped":      "Inside 15 yards, chipping",
    "pitch":        "15-25 yards out",
    "long":         "25+ yards out",
}
