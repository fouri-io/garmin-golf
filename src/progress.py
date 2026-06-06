"""Progress tracker — Strokes Gained over time vs a FIXED scratch ruler.

The point (per the player): the trend is the product, not the season average. A
fixed baseline never moves, so -38 -> -24 -> ... is comparable across months and
swing changes. Outputs:
  - current form = last WINDOW clean rounds (holes-weighted, per 18)
  - delta vs the player's starting window (how far you've come)
  - per-category trend arrows (least-squares slope over all clean rounds)
  - a per-round history (all rounds; over-recorded ones flagged + excluded from form)

'Clean' = not over-recorded (shotCountDelta <= POLLUTION_DELTA). Under-recording is
normal (un-sensed short shots) and kept; over-recording is phantom sensor noise.

Usage:  python -m src.progress
"""

from __future__ import annotations

import json
from pathlib import Path

from .analyze import SG_CATS, SG_LABELS, SG_SHORT, load_rounds
from .config import analysis_start_date

OUT_JSON = Path("data/processed/progress.json")
OUT_MD = Path("data/processed/progress.md")
WINDOW = 3
POLLUTION_DELTA = 3          # shotCountDelta above this = over-recorded -> exclude from form
TREND_FLAT = 0.4             # |slope per round| below this reads as flat


def _per18(d: dict) -> dict:
    holes = d["score"]["holesCompleted"] or 18
    c = d["strokesGained"]["byCategory"]
    return {k: round(c[k] * 18 / holes, 1) for k in SG_CATS}


def _over_rating18(d: dict) -> float | None:
    """Score over course rating, normalized to 18 holes (authoritative — no GPS)."""
    r = d["round"].get("teeBoxRating")
    if r is None:
        return None
    holes = d["score"]["holesCompleted"] or 18
    return round((d["score"]["strokes"] - r) * 18 / holes, 1)


def _is_clean(d: dict) -> bool:
    return d["reconciliation"]["shotCountDelta"] <= POLLUTION_DELTA


def _agg_per18(rounds: list[dict]) -> dict:
    """Holes-weighted per-18 SG over a set of rounds."""
    totals = dict.fromkeys(SG_CATS, 0.0)
    holes = 0
    for d in rounds:
        holes += d["score"]["holesCompleted"] or 18
        c = d["strokesGained"]["byCategory"]
        for k in SG_CATS:
            totals[k] += c[k]
    return {k: round(totals[k] / holes * 18, 1) for k in SG_CATS} if holes else {}


def _slope(ys: list[float]) -> float:
    """Least-squares slope of ys over its index (positive = SG improving over time)."""
    n = len(ys)
    if n < 2:
        return 0.0
    mx = (n - 1) / 2
    my = sum(ys) / n
    num = sum((i - mx) * (y - my) for i, y in enumerate(ys))
    den = sum((i - mx) ** 2 for i in range(n))
    return num / den if den else 0.0


def build() -> dict:
    rounds = sorted(load_rounds(analysis_start_date()), key=lambda d: d["round"]["date"])
    clean = [d for d in rounds if _is_clean(d)]

    current = clean[-WINDOW:]
    start = clean[:WINDOW]
    cur = _agg_per18(current)
    st = _agg_per18(start)
    delta = {k: round(cur[k] - st[k], 1) for k in SG_CATS}

    # Authoritative putting (from the scorecard — no GPS), per 18 over the current window.
    cur_holes = sum(d["score"]["holesCompleted"] or 18 for d in current) or 1
    putting_auth = {
        "puttsPer18": round(sum(d["strokesGained"]["putting"]["totalPutts"]
                                for d in current) / cur_holes * 18, 1),
        "threePuttsPer18": round(sum(d["strokesGained"]["putting"]["threePutts"]
                                     for d in current) / cur_holes * 18, 1),
        "scratchPuttsPer18": 30,
    }

    trend = {}
    for k in SG_CATS:
        s = _slope([_per18(d)[k] for d in clean])
        arrow = "↑" if s > TREND_FLAT else ("↓" if s < -TREND_FLAT else "→")
        trend[k] = {"slopePerRound": round(s, 2), "arrow": arrow}

    series = [{
        "date": d["round"]["date"][:10], "course": d["course"]["name"],
        "score": d["score"]["strokes"], "holes": d["score"]["holesCompleted"],
        "overRating18": _over_rating18(d),
        "per18": _per18(d), "total": round(sum(_per18(d).values()), 1),
        "clean": _is_clean(d),
    } for d in rounds]

    # Score-over-rating: AUTHORITATIVE (score - course rating, no GPS). Uses ALL rounds
    # since a round's score is valid regardless of sensor pollution.
    rated = [d for d in rounds if d["round"].get("teeBoxRating")]
    raw_sum = sum(d["score"]["strokes"] - d["round"]["teeBoxRating"] for d in rated)
    holes_sum = sum(d["score"]["holesCompleted"] or 18 for d in rated)
    over_vals = sorted(_over_rating18(d) for d in rated)
    half = max(1, len(over_vals) // 2)
    scoring = {
        "averageOverRating18": round(raw_sum / holes_sum * 18, 1) if holes_sum else None,
        "potentialOverRating18": round(sum(over_vals[:half]) / half, 1),  # better half ~ handicap
        "bestOverRating18": over_vals[0] if over_vals else None,
        "garminHandicap": 23.6,
        "note": "Authoritative: score - course rating (no GPS). Potential = avg of the "
                "better half of rounds, which is what a handicap measures.",
    }

    doc = {
        "baseline": "PGA Tour (scratch), fixed ruler",
        "window": WINDOW,
        "cleanRounds": len(clean),
        "currentForm": {
            "per18": cur, "total": round(sum(cur.values()), 1),
            "sg0to100Per18": round(sum(d["strokesGained"].get("sg0to100", 0)
                                       for d in current) / cur_holes * 18, 1),
            "penaltiesPer18": round(sum(d["strokesGained"]["penaltyStrokes"]
                                        for d in current) / cur_holes * 18, 1),
            "doublesPer18": round(sum(d["strokesGained"].get("doublesOrWorse", 0)
                                      for d in current) / cur_holes * 18, 1),
            "rounds": [d["round"]["date"][:10] for d in current]},
        "startForm": {"per18": st, "total": round(sum(st.values()), 1),
                      "rounds": [d["round"]["date"][:10] for d in start]},
        "deltaFromStart": {**delta, "total": round(sum(delta.values()), 1)},
        "puttingAuthoritative": putting_auth,
        "scoring": scoring,
        "trend": trend,
        "timeSeries": series,
        "note": (
            f"Current form = last {WINDOW} clean rounds, per 18 vs a fixed scratch ruler. "
            "Δ = improvement since your starting window (+ = better). Trend = slope over all "
            f"clean rounds. Only {len(clean)} clean rounds so far — directional, firms up with "
            "more play. Putting & short game are GPS/under-record limited."
        ),
    }
    OUT_JSON.write_text(json.dumps(doc, indent=2))
    OUT_MD.write_text(render_markdown(doc))
    return doc


def render_markdown(doc: dict) -> str:
    cf, df, tr = doc["currentForm"], doc["deltaFromStart"], doc["trend"]
    pa = doc["puttingAuthoritative"]
    sco = doc["scoring"]
    lines = [
        "# Progress",
        "",
        "## Scoring level (authoritative — score vs course rating, no GPS)",
        f"**Average: +{sco['averageOverRating18']}/18 over rating** "
        f"(scratch = the rating). Potential (better half ≈ handicap): "
        f"**+{sco['potentialOverRating18']}** · best round +{sco['bestOverRating18']} · "
        f"Garmin handicap {sco['garminHandicap']}.",
        f"_The gap between average (+{sco['averageOverRating18']}) and potential "
        f"(+{sco['potentialOverRating18']}) is your volatility — closing it = fewer "
        f"blow-up rounds. Break 90 on these tees ≈ +22._",
        "",
        "## Strokes Gained vs scratch (fixed ruler)",
        f"**Current form** (last {doc['window']} clean rounds: "
        f"{', '.join(cf['rounds'])}) — total **{cf['total']:+.1f}/18**.",
        f"**SG 0–100 (leverage): {cf['sg0to100Per18']:+.1f}/18** · "
        f"penalties {cf['penaltiesPer18']}/18 · doubles+ {cf['doublesPer18']}/18 "
        f"(review these first).",
        f"Since your start ({', '.join(doc['startForm']['rounds'])}): "
        f"**{df['total']:+.1f} strokes/round** "
        f"({'better' if df['total'] > 0 else 'worse'}).",
        f"Putting (authoritative): **{pa['puttsPer18']} putts/18** "
        f"({pa['threePuttsPer18']} three-putts) vs scratch ~{pa['scratchPuttsPer18']} — "
        f"a clear leak; the GPS-based putting SG is not trusted, this count is.",
        "",
        "| Category | Now /18 | Δ from start | Trend |",
        "|---|--:|--:|:-:|",
    ]
    for k in SG_CATS:
        d = df[k]
        lines.append(f"| {SG_LABELS[k]} | {cf['per18'][k]:+.1f} | {d:+.1f} | {tr[k]['arrow']} |")
    lines.append(f"| **Total** | **{cf['total']:+.1f}** | **{df['total']:+.1f}** | |")
    lines += [
        "",
        f"_Δ + = improvement. Trend ↑ = SG rising (improving) over all {doc['cleanRounds']} "
        "clean rounds, → flat, ↓ declining._",
        "",
        "## Per-round history",
        "_vsRtg = score over course rating per 18 (authoritative). SG columns per 18._",
        f"| Date | Course | Score | H | vsRtg | {' | '.join(SG_SHORT[c] for c in SG_CATS)} "
        "| SGtot | |",
        f"|---|---|--:|--:|--:|{'|'.join(['--:'] * len(SG_CATS))}|--:|:--|",
    ]
    for r in doc["timeSeries"]:
        p = r["per18"]
        flag = "" if r["clean"] else " ⚠ excl"
        ovr = f"+{r['overRating18']}" if r["overRating18"] is not None else "—"
        cells = " | ".join(f"{p[cat]:+.1f}" for cat in SG_CATS)
        lines.append(
            f"| {r['date']} | {r['course'][:18]} | {r['score']} | {r['holes']} | {ovr} | "
            f"{cells} | {r['total']:+.1f} |{flag} |"
        )
    lines += ["", "_All values per-18. ⚠ excl = over-recorded round, excluded from current "
              "form/trend. As you log rounds, re-run `python -m src.progress`._"]
    return "\n".join(lines)


def main() -> None:
    doc = build()
    print(f"Wrote {OUT_JSON} and {OUT_MD}")
    cf = doc["currentForm"]
    print(f"  current form {cf['total']:+.1f}/18 (last {doc['window']} clean), "
          f"Δ from start {doc['deltaFromStart']['total']:+.1f}")


if __name__ == "__main__":
    main()
