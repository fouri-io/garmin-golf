"""Cross-round analysis — per-club distance distributions for the LLM coach.

Reads the DuckDB spine (canon facts + derived flags). Builds a `club_stats`
artifact: for each club, how far you actually hit it (median, typical range, max,
dispersion) across the clean, current-bag rounds.

Cleaning rules (so the numbers are trustworthy):
  - Only rounds on/after config/analysis.json:analysisStartDate (current sensor/bag).
  - Drop unknown-club shots (clubId 0 — auto-detected, no CT10 tag).
  - Drop shots on suspect holes (sensor over-recorded — derived.hole_recon).
  - Drop phantom shots (between-hole transit logged as a stroke — derived.shot_flags).
  - For distance, use full-ish shots only: exclude putts and chips (partials deflate
    a club's full-swing distance). The Putter therefore shows a shot count, no distance.

Usage:
    python -m src.analyze
"""

from __future__ import annotations

import json
import statistics as st
from collections import defaultdict
from pathlib import Path

from .config import analysis_start_date
from .constants import SG_CATS, SG_LABELS, SG_SHORT  # noqa: F401 — re-exported for consumers

OUT_JSON = Path("data/processed/club_stats.json")
OUT_MD = Path("data/processed/club_stats.md")

DISTANCE_EXCLUDE_TYPES = {"PUTT", "CHIP"}  # partials/short game — not full-swing distance
PUTTER_CLUBTYPE_ID = 23  # never a full-swing distance club
LOW_CONFIDENCE_N = 4
DISPERSION_MIN_N = 5     # approach shots needed before a miss-bias read is shown


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def build_club_stats() -> dict:
    from .db import connect
    since = analysis_start_date()
    con = connect()
    n_rounds, courses = con.execute(
        "SELECT count(*), list(DISTINCT course_name ORDER BY course_name) "
        "FROM canon.round WHERE round_date >= ?", [since]).fetchone()
    shots = con.execute("""
        SELECT s.club_id, s.club_type_id, s.shot_type, g.yards,
               coalesce(c.name, ct.name, 'unknown') AS club_name,
               coalesce(c.retired, FALSE)           AS retired,
               f.phantom, hr.suspect, ec.exclude_from_stock
        FROM canon.shot s
        JOIN canon.round r USING (round_id)
        LEFT JOIN canon.club c ON c.club_id = s.club_id
        LEFT JOIN canon.club_type ct ON ct.club_type_id = s.club_type_id
        LEFT JOIN derived.shot_geom g ON g.shot_id = s.shot_id
        JOIN derived.shot_flags f ON f.shot_id = s.shot_id
        JOIN derived.hole_recon hr
          ON hr.round_id = s.round_id AND hr.hole_number = s.hole_number
        JOIN derived.shot_effective_context ec ON ec.shot_id = s.shot_id
        WHERE r.round_date >= ?
        ORDER BY s.round_id, s.hole_number, s.shot_order
        """, [since]).fetchall()

    # Aggregate by physical clubId (so the wedges stay separate), labeled by resolved name.
    per_club: dict[int, dict] = defaultdict(
        lambda: {"all": 0, "dist": [], "clubTypeId": None, "name": None})
    suspect_excluded = 0
    phantom_excluded = 0
    stock_excluded = 0
    for (club_id, club_type_id, shot_type, yards, name, retired,
         phantom, suspect, non_stock) in shots:
        if name.startswith("unknown") or club_id == 0 or retired:
            continue
        if phantom:              # between-hole transit, not a stroke
            phantom_excluded += 1
            continue
        if suspect:
            suspect_excluded += 1
            continue
        info = per_club[club_id]
        info["clubTypeId"] = club_type_id
        info["name"] = name
        info["all"] += 1
        if non_stock:            # annotated punch/layup/recovery — not a stock swing
            stock_excluded += 1
            continue
        if (shot_type not in DISTANCE_EXCLUDE_TYPES and yards is not None
                and club_type_id != PUTTER_CLUBTYPE_ID):
            info["dist"].append(yards)

    # Approach dispersion per club: only shots where the pin IS the target line
    # (long/mid/inside50 — never tee shots), same trust filters as distances, and
    # never a tagged non-stock swing. Side/short-long come from shot geometry.
    disp_rows = con.execute("""
        SELECT s.club_id, g.miss_side, g.miss_range, g.lateral_yds
        FROM canon.shot s
        JOIN canon.round r USING (round_id)
        JOIN derived.shot_sg sg ON sg.shot_id = s.shot_id
        JOIN derived.shot_geom g ON g.shot_id = s.shot_id
        JOIN derived.shot_flags f ON f.shot_id = s.shot_id
        JOIN derived.hole_recon hr
          ON hr.round_id = s.round_id AND hr.hole_number = s.hole_number
        JOIN derived.shot_effective_context ec ON ec.shot_id = s.shot_id
        WHERE r.round_date >= ? AND NOT f.phantom AND NOT hr.suspect
          AND NOT ec.exclude_from_stock AND s.shot_type != 'PUTT'
          AND coalesce(s.club_type_id, 0) != ?
          AND sg.sg_category IN ('longApproach', 'midApproach', 'inside50')
          AND g.miss_side IS NOT NULL
        """, [since, PUTTER_CLUBTYPE_ID]).fetchall()
    disp: dict[int, dict] = defaultdict(lambda: {"n": 0, "left": 0, "straight": 0,
                                                 "right": 0, "short": 0, "long": 0,
                                                 "lat": []})
    for club_id, side, rng, lat in disp_rows:
        d = disp[club_id]
        d["n"] += 1
        d[side] += 1
        if rng in ("short", "long"):
            d[rng] += 1
        if lat is not None:
            d["lat"].append(lat)

    def _dispersion(club_id: int) -> dict | None:
        d = disp.get(club_id)
        if not d or d["n"] < DISPERSION_MIN_N:
            return None
        n = d["n"]
        return {
            "approachShots": n,
            "leftPct": round(100 * d["left"] / n),
            "straightPct": round(100 * d["straight"] / n),
            "rightPct": round(100 * d["right"] / n),
            "shortPct": round(100 * d["short"] / n),
            "longPct": round(100 * d["long"] / n),
            "medianLateralYds": round(st.median(d["lat"]), 1) if d["lat"] else None,
        }

    clubs = []
    for club_id, info in per_club.items():
        vals = sorted(info["dist"])
        clubs.append({
            "club": info["name"],
            "clubId": club_id,
            "clubTypeId": info["clubTypeId"],
            "shots": info["all"],
            "distanceShots": len(vals),
            "medianYds": round(st.median(vals)) if vals else None,
            "meanYds": round(st.mean(vals)) if vals else None,
            "p25Yds": round(_percentile(vals, 0.25)) if vals else None,
            "p75Yds": round(_percentile(vals, 0.75)) if vals else None,
            "maxYds": round(max(vals)) if vals else None,
            "stdevYds": round(st.pstdev(vals), 1) if len(vals) > 1 else None,
            "lowConfidence": len(vals) < LOW_CONFIDENCE_N,
            "dispersion": _dispersion(club_id),
        })
    # Longest median first; clubs without distance (putter) sink to the bottom.
    clubs.sort(key=lambda c: (c["medianYds"] is None, -(c["medianYds"] or 0)))

    doc = {
        "generatedFrom": {
            "rounds": n_rounds,
            "analysisStartDate": since,
            "courses": courses or [],
            "suspectHoleShotsExcluded": suspect_excluded,
            "phantomShotsExcluded": phantom_excluded,
            "annotatedShotsExcluded": stock_excluded,   # non-stock swings (punch/layup/...)
        },
        "clubs": clubs,
        "note": (
            "Distances are per-shot travel (yds) for full-ish shots (putts & chips "
            "excluded). Unknown-club and suspect-hole shots dropped. Small samples are "
            "flagged lowConfidence — these firm up as more rounds are added."
        ),
    }
    OUT_JSON.write_text(json.dumps(doc, indent=2))
    OUT_MD.write_text(render_markdown(doc))
    return doc


def render_markdown(doc: dict) -> str:
    g = doc["generatedFrom"]
    lines = [
        f"# Club distances — {g['rounds']} rounds since {g['analysisStartDate']}",
        f"Courses: {', '.join(g['courses'])}",
        f"_Full-swing shots only (putts & chips excluded); unknown-club and "
        f"suspect-hole shots dropped ({g['suspectHoleShotsExcluded']} suspect, "
        f"{g['phantomShotsExcluded']} phantom)._",
        "",
        "| Club | n | Median | Typical (p25–p75) | Max |",
        "|---|--:|--:|:-:|--:|",
    ]
    for c in doc["clubs"]:
        if c["medianYds"] is None:
            lines.append(f"| {c['club']} | {c['shots']} | — | — | — |")
            continue
        conf = " ⚠︎" if c["lowConfidence"] else ""
        lines.append(
            f"| {c['club']}{conf} | {c['distanceShots']} | {c['medianYds']} | "
            f"{c['p25Yds']}–{c['p75Yds']} | {c['maxYds']} |"
        )
    lines += [
        "",
        f"⚠︎ = fewer than {LOW_CONFIDENCE_N} full-swing shots; low-confidence.",
        "_Median is the reliable 'stock' yardage. The wide p25–p75 spread reflects strike "
        "consistency — partial/mishit shots share each club and pull the low end down._",
    ]
    return "\n".join(lines)


def main() -> None:
    doc = build_club_stats()
    g = doc["generatedFrom"]
    print(f"Wrote {OUT_JSON} and {OUT_MD}")
    print(f"  {g['rounds']} rounds, {len(doc['clubs'])} clubs, "
          f"{g['suspectHoleShotsExcluded']} suspect-hole + "
          f"{g['phantomShotsExcluded']} phantom shots excluded")


if __name__ == "__main__":
    main()
