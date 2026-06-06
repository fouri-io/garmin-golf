"""Strokes Gained — where strokes are won/lost vs a baseline (Broadie-style).

Per shot:  SG = E(before) - E(after) - 1   (a holed shot has E(after)=0).
Each shot is categorized Off-the-Tee / Approach / Around-the-Green / Putting, and
summed per round.

Honest limits (surfaced in the output):
  - Baseline is SCRATCH (PGA Tour), so an amateur's SG is negative across the board;
    the signal is the RELATIVE split — which category bleeds the most.
  - Putting SG is GPS-noisy (green-scale distances), so it's the least reliable bucket.
  - The shot layer under/over-records, and penalties have no shot position, so the
    per-shot category sums don't fully reconcile to the hole total; the gap is reported
    as `unattributed` (penalties + un-sensed shots).
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import scoring_zone_max_yds

BASELINE_PATH = Path("config/sg_baseline.json")

# Garmin lie -> baseline through-green lie
_LIE_MAP = {
    "TeeBox": "tee", "Fairway": "fairway", "Rough": "rough",
    "Bunker": "sand", "Unknown": "recovery",
}


def _interp(table: dict[float, float], x: float) -> float:
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
            return _interp(self.putt, dist_yds * 3.0)  # yards -> feet on the green
        tg_lie = _LIE_MAP.get(lie, "fairway")
        return _interp(self.tg[tg_lie], dist_yds)


def categorize(shot: dict, par: int | None, scoring_zone_max: float) -> str:
    """Bucket by task: putting / offTee / shortGame (wedge zone) / approach (full)."""
    if shot["from"] == "Green":
        return "putting"
    if shot["from"] == "TeeBox" and par and par >= 4:
        return "offTee"
    d = shot.get("distanceToPinBeforeYds")
    if d is not None and d <= scoring_zone_max:
        return "shortGame"     # AW/50/54/58 wedge & pitch zone
    return "approach"          # full irons/woods into greens


def compute(holes: list[dict], base: Baseline | None = None) -> dict:
    """Annotate each shot with sgCategory + strokesGained (in place) and return a
    round-level Strokes Gained summary."""
    base = base or Baseline()
    scoring_zone = scoring_zone_max_yds()
    by_cat = {"offTee": 0.0, "approach": 0.0, "shortGame": 0.0, "putting": 0.0}
    categorized = 0
    penalty_strokes = 0

    for h in holes:
        shots = h["shots"]
        par = h["par"]
        penalty_strokes += h.get("penalties") or 0

        for i, s in enumerate(shots):
            cat = categorize(s, par, scoring_zone)
            s["sgCategory"] = cat
            e_before = base.expected(lie=s["from"], dist_yds=s.get("distanceToPinBeforeYds"))
            # A shot that ends on the green as the hole's last recorded shot = holed out.
            is_last = i == len(shots) - 1
            if is_last and s["to"] == "Green":
                e_after = 0.0
            else:
                e_after = base.expected(lie=s["to"], dist_yds=s.get("distanceRemainingYds"))
            if e_before is None or e_after is None:
                s["strokesGained"] = None
                continue
            sg = e_before - e_after - 1.0
            s["strokesGained"] = round(sg, 3)
            by_cat[cat] += sg
            categorized += 1

    by_cat = {k: round(v, 2) for k, v in by_cat.items()}
    return {
        "baseline": "PGA Tour (scratch), approximate",
        "totalRecordedVsScratch": round(sum(by_cat.values()), 2),  # over recorded shots only
        "byCategory": by_cat,
        "categorizedShots": categorized,
        "penaltyStrokes": penalty_strokes,    # ~ -1 each, not in the category totals
        "note": (
            "Per-shot SG over RECORDED shots only — penalties (no shot position, ~-1 each) "
            "and un-sensed shots are NOT included. Negative is normal vs a scratch baseline; "
            "read the category split. Putting is GPS-noisy (least reliable bucket)."
        ),
    }
