"""The single progress dashboard — one file to view after every round.

Three horizons, read side by side:
  - This round  : your latest round (the immediate review)
  - Last 5      : current form (rolling, smooths one-round noise)
  - All-time    : baseline since the analysis cutoff

How to read across: This-vs-Last5 tells you whether a round was above or below your
form (signal vs noise); Last5-vs-All tells you whether you're trending up.

Authoritative metrics (score-vs-rating, putts, penalties, doubles) use every round in
the window. Strokes Gained uses only CLEAN rounds (over-recorded rounds excluded —
their shot data is phantom). Putting SG is count-based; other SG buckets are GPS-based.

Usage:  python -m src.progress
"""

from __future__ import annotations

import json
from pathlib import Path

from .analyze import SG_CATS, SG_LABELS, SG_SHORT, load_rounds
from .config import analysis_start_date

OUT_JSON = Path("data/processed/progress.json")
OUT_MD = Path("data/processed/progress.md")
RECENT_N = 5                 # "current form" window (rounds)
POLLUTION_DELTA = 3          # shotCountDelta above this = over-recorded -> excluded from SG
SCRATCH_PUTTS_18 = 30
GARMIN_HANDICAP = 23.6
BREAK_90_OVER_RATING = 22    # ~ shooting 89 on the player's ~67-rated tees


def _holes(d: dict) -> int:
    return d["score"]["holesCompleted"] or 18


def _is_clean(d: dict) -> bool:
    return d["reconciliation"]["shotCountDelta"] <= POLLUTION_DELTA


def _over_rating18(d: dict) -> float | None:
    r = d["round"].get("teeBoxRating")
    return round((d["score"]["strokes"] - r) * 18 / _holes(d), 1) if r is not None else None


def _sg_window(rounds: list[dict]) -> dict | None:
    """Per-18 SG by bucket over the CLEAN rounds in a window (None if none clean)."""
    clean = [d for d in rounds if _is_clean(d)]
    holes = sum(_holes(d) for d in clean)
    if not holes:
        return None
    by = {cat: round(sum(d["strokesGained"]["byCategory"][cat] for d in clean) / holes * 18, 1)
          for cat in SG_CATS}
    sg0 = round(sum(d["strokesGained"].get("sg0to100", 0) for d in clean) / holes * 18, 1)
    return {"byCategory": by, "total": round(sum(by.values()), 1), "sg0to100": sg0,
            "cleanRounds": len(clean)}


def _auth_window(rounds: list[dict]) -> dict:
    """Authoritative per-18 metrics (no GPS) over ALL rounds in a window."""
    holes = sum(_holes(d) for d in rounds)
    rated = [d for d in rounds if d["round"].get("teeBoxRating")]
    rated_holes = sum(_holes(d) for d in rated)
    sgp = [d["strokesGained"]["putting"] for d in rounds]
    return {
        "overRating18": round(sum(d["score"]["strokes"] - d["round"]["teeBoxRating"]
                                  for d in rated) / rated_holes * 18, 1) if rated_holes else None,
        "putts18": round(sum(p["totalPutts"] for p in sgp) / holes * 18, 1),
        "threePutts18": round(sum(p["threePutts"] for p in sgp) / holes * 18, 1),
        "penalties18": round(sum(d["strokesGained"]["penaltyStrokes"] for d in rounds)
                             / holes * 18, 1),
        "doubles18": round(sum(d["strokesGained"].get("doublesOrWorse", 0) for d in rounds)
                           / holes * 18, 1),
    }


def build() -> dict:
    rounds = sorted(load_rounds(analysis_start_date()), key=lambda d: d["round"]["date"])
    horizons = {
        "thisRound": [rounds[-1]] if rounds else [],
        "last5": rounds[-RECENT_N:],
        "allTime": rounds,
    }
    sg = {k: _sg_window(v) for k, v in horizons.items()}
    auth = {k: _auth_window(v) for k, v in horizons.items()}

    # Scoring "potential" = better half of rounds (≈ what a handicap measures).
    over_vals = sorted(v for v in (_over_rating18(d) for d in rounds) if v is not None)
    half = max(1, len(over_vals) // 2)

    series = [{
        "date": d["round"]["date"][:10], "course": d["course"]["name"],
        "score": d["score"]["strokes"], "holes": _holes(d),
        "overRating18": _over_rating18(d),
        "per18": {cat: round(d["strokesGained"]["byCategory"][cat] * 18 / _holes(d), 1)
                  for cat in SG_CATS},
        "clean": _is_clean(d),
    } for d in rounds]

    doc = {
        "generatedFromRounds": len(rounds),
        "since": analysis_start_date(),
        "thisRoundDate": rounds[-1]["round"]["date"][:10] if rounds else None,
        "thisRoundClean": _is_clean(rounds[-1]) if rounds else None,
        "scoring": {
            "averageOverRating18": auth["allTime"]["overRating18"],
            "potentialOverRating18": round(sum(over_vals[:half]) / half, 1) if over_vals else None,
            "bestOverRating18": over_vals[0] if over_vals else None,
            "garminHandicap": GARMIN_HANDICAP,
            "break90OverRating": BREAK_90_OVER_RATING,
        },
        "sg": sg,
        "authoritative": auth,
        "timeSeries": series,
    }
    OUT_JSON.write_text(json.dumps(doc, indent=2))
    OUT_MD.write_text(render_markdown(doc))
    return doc


def _row(label: str, this, last5, alltime, fmt="{:+.1f}") -> str:
    def cell(v):
        return fmt.format(v) if isinstance(v, (int, float)) else "—"
    return f"| {label} | {cell(this)} | {cell(last5)} | {cell(alltime)} |"


def render_markdown(doc: dict) -> str:
    sc, sg, au = doc["scoring"], doc["sg"], doc["authoritative"]
    this_sg = sg["thisRound"]
    flag = "" if doc["thisRoundClean"] else " ⚠ (over-recorded — its SG is unreliable)"
    lines = [
        "# Golf Progress Dashboard",
        f"_From {doc['generatedFromRounds']} rounds since {doc['since']}. "
        f"Latest round: {doc['thisRoundDate']}{flag}. Re-run `python -m src.progress` "
        "after each round._",
        "",
        "> **Reading the signs:** two different conventions. Section 1 (score vs rating) is "
        "\"over par\" style — **+ = strokes OVER scratch, lower is better**. Section 3 "
        "(Strokes Gained) is analytics style — **− = strokes LOST to scratch, toward 0 is "
        "better**. They're mirror images: +29 over ≈ −29 gained = \"~30 strokes from a pro.\"",
        "",
        "## 1 · Scoring level — strokes OVER scratch (lower is better, 0 = scratch)",
        f"**Average +{sc['averageOverRating18']}/18** · Potential (better half ≈ handicap) "
        f"**+{sc['potentialOverRating18']}** · best +{sc['bestOverRating18']} · "
        f"Garmin handicap {sc['garminHandicap']} · **Break-90 ≈ +{sc['break90OverRating']}**.",
        f"_Average − potential = ~{round(sc['averageOverRating18'] - sc['potentialOverRating18'])}"
        " strokes of volatility (your blow-up tax — fewer doubles closes it)._",
        "",
        "## 2 · Review first (authoritative — count these before anything else)",
        "| Metric /18 | This round | Last 5 | All-time |",
        "|---|--:|--:|--:|",
        _row("Score vs rating", au["thisRound"]["overRating18"], au["last5"]["overRating18"],
             au["allTime"]["overRating18"], "+{:.1f}"),
        _row("Penalties", au["thisRound"]["penalties18"], au["last5"]["penalties18"],
             au["allTime"]["penalties18"], "{:.1f}"),
        _row("Doubles+", au["thisRound"]["doubles18"], au["last5"]["doubles18"],
             au["allTime"]["doubles18"], "{:.1f}"),
        _row("Putts (3-putts)", au["thisRound"]["putts18"], au["last5"]["putts18"],
             au["allTime"]["putts18"], "{:.0f}"),
        "",
        "## 3 · Strokes Gained vs scratch — negative = strokes LOST (toward 0 is better)",
        f"**SG 0–100, your leverage number:** This round "
        f"{_fmt(this_sg, 'sg0to100')} · Last 5 {_fmt(sg['last5'], 'sg0to100')} · "
        f"All-time {_fmt(sg['allTime'], 'sg0to100')}  _(100yd-and-in, no putts — where scores move)_",
        "",
        "| Bucket | This round | Last 5 | All-time |",
        "|---|--:|--:|--:|",
    ]
    for cat in SG_CATS:
        lines.append(_row(
            SG_LABELS[cat],
            this_sg["byCategory"][cat] if this_sg else None,
            sg["last5"]["byCategory"][cat] if sg["last5"] else None,
            sg["allTime"]["byCategory"][cat] if sg["allTime"] else None,
        ))
    lines.append(_row("**Total**", this_sg["total"] if this_sg else None,
                      sg["last5"]["total"] if sg["last5"] else None,
                      sg["allTime"]["total"] if sg["allTime"] else None))
    lines += [
        "",
        "_Read across: **This vs Last 5** = was this round above/below your form (signal vs "
        "noise). **Last 5 vs All-time** = are you trending up. Putting is count-based "
        "(authoritative putts); other buckets are GPS-based; the absolute total runs a few "
        "strokes hot — trust the ranking._",
        "",
        "## 4 · Per-round history",
        "_vsRtg = score over rating per 18 (authoritative). SG per 18; ⚠ = over-recorded, "
        "excluded from SG windows._",
        f"| Date | Course | Score | H | vsRtg | {' | '.join(SG_SHORT[c] for c in SG_CATS)} | |",
        f"|---|---|--:|--:|--:|{'|'.join(['--:'] * len(SG_CATS))}|:--|",
    ]
    for r in doc["timeSeries"]:
        p = r["per18"]
        ovr = f"+{r['overRating18']}" if r["overRating18"] is not None else "—"
        cells = " | ".join(f"{p[cat]:+.1f}" for cat in SG_CATS)
        flg = "" if r["clean"] else " ⚠"
        lines.append(f"| {r['date']} | {r['course'][:18]} | {r['score']} | {r['holes']} | "
                     f"{ovr} | {cells} |{flg} |")
    return "\n".join(lines)


def _fmt(window: dict | None, key: str) -> str:
    return f"{window[key]:+.1f}" if window else "—"


def main() -> None:
    doc = build()
    print(f"Wrote {OUT_JSON} and {OUT_MD}")
    sg = doc["sg"]
    print(f"  This round SG total {_fmt(sg['thisRound'], 'total')}, "
          f"Last 5 {_fmt(sg['last5'], 'total')}, All-time {_fmt(sg['allTime'], 'total')}")


if __name__ == "__main__":
    main()
