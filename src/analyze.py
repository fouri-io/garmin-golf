"""Cross-round analysis — per-club distance distributions for the LLM coach.

Reads the processed round documents (the source of truth), not raw. Builds a
`club_stats` artifact: for each club, how far you actually hit it (median, typical
range, max, dispersion) across the clean, current-bag rounds.

Cleaning rules (so the numbers are trustworthy):
  - Only rounds on/after config/analysis.json:analysisStartDate (current sensor/bag).
  - Drop unknown-club shots (clubId 0 — auto-detected, no CT10 tag).
  - Drop shots on reconciliation.suspectHoles (sensor over-recorded — phantom shots).
  - For distance, use full-ish shots only: exclude putts and chips (partials deflate
    a club's full-swing distance). The Putter therefore shows a shot count, no distance.

Usage:
    python -m src.analyze
"""

from __future__ import annotations

import glob
import json
import statistics as st
from collections import defaultdict
from pathlib import Path

from .config import analysis_start_date

ROUNDS_DIR = Path("data/processed/rounds")
OUT_JSON = Path("data/processed/club_stats.json")
OUT_MD = Path("data/processed/club_stats.md")

DISTANCE_EXCLUDE_TYPES = {"PUTT", "CHIP"}  # partials/short game — not full-swing distance
PUTTER_CLUBTYPE_ID = 23  # never a full-swing distance club
LOW_CONFIDENCE_N = 4


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def load_rounds(since: str) -> list[dict]:
    rounds = []
    for f in sorted(glob.glob(str(ROUNDS_DIR / "*.json"))):
        d = json.load(open(f))
        if d["round"]["date"][:10] >= since:
            rounds.append(d)
    return rounds


def build_club_stats() -> dict:
    since = analysis_start_date()
    rounds = load_rounds(since)

    # Aggregate by physical clubId (so the wedges stay separate), labeled by resolved name.
    per_club: dict[int, dict] = defaultdict(
        lambda: {"all": 0, "dist": [], "clubTypeId": None, "name": None})
    suspect_excluded = 0
    for d in rounds:
        suspect = set(d["reconciliation"]["suspectHoles"])
        for h in d["holes"]:
            for s in h["shots"]:
                if s["club"].startswith("unknown") or s["clubId"] == 0 or s.get("clubRetired"):
                    continue
                if h["number"] in suspect:
                    suspect_excluded += 1
                    continue
                info = per_club[s["clubId"]]
                info["clubTypeId"] = s["clubTypeId"]
                info["name"] = s["club"]
                info["all"] += 1
                if (s["type"] not in DISTANCE_EXCLUDE_TYPES and s["yards"] is not None
                        and s["clubTypeId"] != PUTTER_CLUBTYPE_ID):
                    info["dist"].append(s["yards"])

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
        })
    # Longest median first; clubs without distance (putter) sink to the bottom.
    clubs.sort(key=lambda c: (c["medianYds"] is None, -(c["medianYds"] or 0)))

    doc = {
        "generatedFrom": {
            "rounds": len(rounds),
            "analysisStartDate": since,
            "courses": sorted({d["course"]["name"] for d in rounds}),
            "suspectHoleShotsExcluded": suspect_excluded,
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
        f"suspect-hole shots dropped ({g['suspectHoleShotsExcluded']} suspect shots)._",
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
          f"{g['suspectHoleShotsExcluded']} suspect-hole shots excluded")


if __name__ == "__main__":
    main()
