"""Pure Strokes Gained math — no file I/O beyond loading the baseline table, no
round-document coupling. Extracted from strokes_gained.py so the same interpolation
and categorization drive both the legacy per-round computation and the derived layer.

Per shot:  SG = E(before) - E(after) - 1   (a holed shot has E(after)=0).
"""

from __future__ import annotations

import json
from pathlib import Path

BASELINE_PATH = Path("config/sg_baseline.json")

# Garmin lie -> baseline through-green lie.
# "Unknown" is NOT a lie assessment: it means the endpoint fell outside the course
# cartography polygon (always paired with offMap=true, lieSource=CARTOGRAPHY). Mapping it
# to `recovery` — a stymied, punch-out-sideways lie whose curve is flat at ~3.5-4.0
# strokes regardless of distance — charged the shot that got there and refunded the next
# one, systematically draining offTee into the approach buckets. In practice these are
# mostly drives running past the end of the mapped corridor, so `fairway` is the fairer
# read; `recovery` needs evidence the shot layer never gives us.
LIE_MAP = {
    "TeeBox": "tee", "Fairway": "fairway", "Rough": "rough",
    "Bunker": "sand", "Unknown": "fairway",
}


def interp(table: dict[float, float], x: float) -> float:
    keys = sorted(table)
    if x <= keys[0]:
        return table[keys[0]]
    if x >= keys[-1]:
        return table[keys[-1]]
    lo = max(k for k in keys if k <= x)
    hi = min(k for k in keys if k >= x)
    if lo == hi:
        return table[lo]
    frac = (x - lo) / (hi - lo)
    return table[lo] + (table[hi] - table[lo]) * frac


class Baseline:
    def __init__(self, path: Path = BASELINE_PATH):
        raw = json.loads(path.read_text())
        self.tg = {lie: {float(k): v for k, v in tbl.items()}
                   for lie, tbl in raw["throughGreen"].items()}
        self.putt = {float(k): v for k, v in raw["putting"].items()}

    def expected(self, *, lie: str, dist_yds: float | None) -> float | None:
        """Expected strokes to hole out from a lie at a distance (yards; feet if green)."""
        if dist_yds is None:
            return None
        if lie == "Green":
            return interp(self.putt, dist_yds * 3.0)  # yards -> feet on the green
        tg_lie = LIE_MAP.get(lie, "fairway")
        return interp(self.tg[tg_lie], dist_yds)

    def expected_putts(self, dist_ft: float) -> float:
        """Expected putts to hole out from a distance on the green (feet)."""
        return interp(self.putt, dist_ft)


def categorize(shot: dict, par: int | None, cuts: dict) -> str:
    """Bucket by task: putting / offTee / longApproach / midApproach / inside50.

    Off-tee = par 4/5 tee shots (any club). Everything else through the green is
    bucketed by distance to the pin. Par-3 tee shots fall into the distance buckets.
    """
    if shot["from"] == "Green":
        return "putting"
    if shot["from"] == "TeeBox" and par and par >= 4:
        return "offTee"
    d = shot.get("distanceToPinBeforeYds")
    if d is None:
        return "midApproach"
    if d >= cuts["longApproachMinYds"]:
        return "longApproach"
    if d > cuts["insideMaxYds"]:
        return "midApproach"
    return "inside50"


def shot_sg(base: Baseline, *, from_lie: str, to_lie: str,
            dist_before_yds: float | None, dist_after_yds: float | None) -> float | None:
    """Per-shot tee-to-green SG, or None when either endpoint has no expectation."""
    e_before = base.expected(lie=from_lie, dist_yds=dist_before_yds)
    e_after = base.expected(lie=to_lie, dist_yds=dist_after_yds)
    if e_before is None or e_after is None:
        return None
    return e_before - e_after - 1.0
