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

from .config import sg_distance_cuts

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

    def expected_putts(self, dist_ft: float) -> float:
        """Expected putts to hole out from a distance on the green (feet)."""
        return _interp(self.putt, dist_ft)


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


def compute(holes: list[dict], base: Baseline | None = None) -> dict:
    """Annotate each shot with sgCategory + strokesGained (in place) and return a
    round-level Strokes Gained summary."""
    base = base or Baseline()
    cuts = sg_distance_cuts()
    by_cat = {"offTee": 0.0, "longApproach": 0.0, "midApproach": 0.0,
              "inside50": 0.0, "putting": 0.0}
    categorized = 0
    penalty_strokes = 0
    doubles = 0
    sg_0_100 = 0.0          # leverage metric: all non-putt shots from headlineMaxYds and in
    # Putting is computed from AUTHORITATIVE putt counts, not GPS shot positions.
    total_putts = three_putts = putts_covered = holes_putt_measured = 0

    for h in holes:
        shots = h["shots"]
        par = h["par"]
        penalty_strokes += h.get("penalties") or 0
        if (h.get("scoreToPar") or 0) >= 2:
            doubles += 1
        putts = h.get("putts") or 0
        total_putts += putts
        three_putts += 1 if putts >= 3 else 0

        # Tee-to-green: per-shot SG. Putts are handled below from counts, not here.
        for s in shots:
            cat = categorize(s, par, cuts)
            s["sgCategory"] = cat
            if cat == "putting":
                s["strokesGained"] = None  # measured at hole level from putt counts
                continue
            e_before = base.expected(lie=s["from"], dist_yds=s.get("distanceToPinBeforeYds"))
            # End on the green -> expected PUTTS from there (no bogus holing credit).
            e_after = base.expected(lie=s["to"], dist_yds=s.get("distanceRemainingYds"))
            if e_before is None or e_after is None:
                s["strokesGained"] = None
                continue
            sg = e_before - e_after - 1.0
            s["strokesGained"] = round(sg, 3)
            by_cat[cat] += sg
            categorized += 1
            d = s.get("distanceToPinBeforeYds")
            if cat != "offTee" and d is not None and d <= cuts["headlineMaxYds"]:
                sg_0_100 += sg

        # Putting SG = expected putts (from first-putt distance) - actual putts. Uses the
        # authoritative count, so 3-putts are penalized correctly. Only where we have a
        # first-putt distance (hole reached the green with a recorded putt).
        fpd = h.get("firstPuttDistanceFt")
        if putts and fpd is not None:
            by_cat["putting"] += base.expected_putts(fpd) - putts
            putts_covered += putts
            holes_putt_measured += 1

    by_cat = {k: round(v, 2) for k, v in by_cat.items()}
    return {
        "baseline": "PGA Tour (scratch), approximate",
        "totalRecordedVsScratch": round(sum(by_cat.values()), 2),
        "byCategory": by_cat,
        "sg0to100": round(sg_0_100, 2),       # headline leverage metric (excludes putts & tee)
        "categorizedShots": categorized,
        "penaltyStrokes": penalty_strokes,    # ~ -1 each, not in the category totals
        "doublesOrWorse": doubles,            # authoritative — count first in review
        "putting": {                          # authoritative, from the scorecard
            "totalPutts": total_putts,
            "threePutts": three_putts,
            "sgFromCounts": by_cat["putting"],
            "holesMeasured": holes_putt_measured,
            "puttsCovered": putts_covered,    # putts the SG could place (have a 1st-putt dist)
        },
        "note": (
            "Tee-to-green SG is per-shot over recorded shots (penalties & un-sensed shots "
            "excluded). Buckets are distance-based (offTee = par4/5 tee; long 150+, mid "
            "50-150, inside-50). sg0to100 is the leverage metric (100yd-and-in, no putts). "
            "Putting is count-based (3-putts penalized; totalPutts/threePutts authoritative)."
        ),
    }
