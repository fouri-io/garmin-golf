"""The single progress dashboard — one file to view after every round.

Five horizons, read side by side:
  - This round  : your latest round (the immediate review)
  - Last 5      : current form (rolling, smooths one-round noise)
  - Last 10/20  : medium-term trend windows
  - All-time    : baseline since the analysis cutoff

How to read across: This-vs-Last5 tells you whether a round was above or below your
form (signal vs noise); Last5-vs-All tells you whether you're trending up.

All aggregation reads the DuckDB derived layer (canon facts + recomputable views);
this module only windows per-round rows and renders. Authoritative metrics
(score-vs-rating, putts, penalties, doubles) use every round in the window. Strokes
Gained uses only CLEAN rounds (over-recorded rounds excluded — their shot data is
phantom). Putting SG is count-based; other SG buckets are GPS-based.

Usage:  python -m src.progress
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import analysis_start_date, sg_target
from .constants import POLLUTION_DELTA, RECENT_N, SG_CATS, SG_LABELS, SG_SHORT

OUT_JSON = Path("data/processed/progress.json")
OUT_MD = Path("data/processed/progress.md")
SCRATCH_PUTTS_18 = 30
GARMIN_HANDICAP = 23.6
BREAK_90_OVER_RATING = 22    # ~ shooting 89 on the player's ~67-rated tees

# Dashboard putting bands (vNext fine bands; first-putt distance is GPS-derived, so
# the shortest band is the least reliable).
PUTT_BANDS = [("0–3 ft", "0-3"), ("3–6 ft", "3-6"), ("6–10 ft", "6-10"),
              ("10–20 ft", "10-20"), ("20–40 ft", "20-40"), ("40+ ft", "40+")]

_SG_COLS = {"offTee": "sg_off_tee", "longApproach": "sg_long_approach",
            "midApproach": "sg_mid_approach", "inside50": "sg_inside50",
            "putting": "sg_putting"}


def _load_rounds_from_db(con) -> list[dict]:
    """Per-round records shaped like the legacy round documents (only the fields the
    window math uses), built from canon + derived. Ordered by start time."""
    since = analysis_start_date()
    rows = con.execute("""
        SELECT r.round_id, r.start_time, r.course_name, r.tee_rating, r.tee_slope,
               r.total_strokes, r.total_putts, r.total_penalties, r.holes_completed,
               rr.shot_count_delta,
               sg.sg_off_tee, sg.sg_long_approach, sg.sg_mid_approach, sg.sg_inside50,
               sg.sg_putting, sg.sg_0_100,
               m.doubles_plus, m.three_putt_holes, m.scramble_opps, m.scramble_saves,
               m.putts_3_6, m.makes_3_6, m.putts_6_10, m.makes_6_10,
               m.long_first_putts, m.long_three_putts
        FROM canon.round r
        JOIN derived.round_recon rr USING (round_id)
        JOIN derived.round_sg sg USING (round_id)
        JOIN derived.round_metrics m USING (round_id)
        WHERE r.round_date >= ? AND r.source = 'garminconnect'
        ORDER BY r.start_time
        """, [since]).fetchall()
    bands = {}
    for rid, band, putts in con.execute("""
        SELECT round_id, band, putts FROM derived.putting_bands
        """).fetchall():
        bands.setdefault(rid, []).append((band, putts))
    ctx_cols = ["tee_states", "tee_clean", "tee_compromised", "tee_recovery",
                "recovery_attempts", "recovery_successes",
                "normal_approaches", "normal_approach_greens"]
    ctx = {r[0]: dict(zip(ctx_cols, r[1:])) for r in con.execute(
        f"SELECT round_id, {', '.join(ctx_cols)} FROM derived.round_context_metrics"
    ).fetchall()}

    records = []
    for (rid, start, course, rating, slope, strokes, putts, pens, holes, delta,
         ott, lng, mid, i50, sgp, sg0, dbl, tp3, opps, saves,
         p36, m36, p610, m610, plong, plong3) in rows:
        records.append({
            "scorecardId": rid,
            "round": {"date": start, "teeBoxRating": rating, "teeBoxSlope": slope},
            "course": {"name": course},
            "score": {"strokes": strokes, "holesCompleted": holes},
            "reconciliation": {"shotCountDelta": delta},
            "strokesGained": {
                # rounded per round to match the legacy round documents exactly
                "byCategory": {"offTee": round(ott, 2), "longApproach": round(lng, 2),
                               "midApproach": round(mid, 2), "inside50": round(i50, 2),
                               "putting": round(sgp, 2)},
                "sg0to100": round(sg0, 2),
                "penaltyStrokes": pens,
                "doublesOrWorse": dbl,
                "putting": {"totalPutts": putts, "threePutts": tp3},
            },
            "_metrics": {"scrambleOpps": opps, "scrambleSaves": saves,
                         "putts36": p36, "makes36": m36,
                         "putts610": p610, "makes610": m610,
                         "longFirstPutts": plong, "longThreePutts": plong3},
            "_bands": bands.get(rid, []),
            "_ctx": ctx.get(rid),   # None = round not annotated yet
        })
    return records


def _holes(d: dict) -> int:
    return d["score"]["holesCompleted"] or 18


def _is_clean(d: dict) -> bool:
    return d["reconciliation"]["shotCountDelta"] <= POLLUTION_DELTA


def _over_rating18(d: dict) -> float | None:
    r = d["round"].get("teeBoxRating")
    return round((d["score"]["strokes"] - r) * 18 / _holes(d), 1) if r is not None else None


def _diff18(d: dict) -> float | None:
    """Handicap differential, normalized to 18 holes: (score - rating) * 113/slope.
    Unlike over-rating, this credits course difficulty via slope (113 = neutral)."""
    r, s = d["round"].get("teeBoxRating"), d["round"].get("teeBoxSlope")
    if r is None or not s:
        return None
    return (d["score"]["strokes"] - r) * 113 / s * 18 / _holes(d)


def _handicap_index(rounds: list[dict]) -> float | None:
    """WHS-style index estimate: average of the lowest-N 18-hole differentials with the
    small-sample adjustment (no 0.96 — current WHS). Labeled an estimate in the UI."""
    diffs = sorted(v for v in (_diff18(d) for d in rounds) if v is not None)
    n = len(diffs)
    if n < 3:
        return None
    low = {3: 1, 4: 1, 5: 1, 6: 2, 7: 2, 8: 2, 9: 3, 10: 3, 11: 3, 12: 4, 13: 4,
           14: 4, 15: 5, 16: 5, 17: 6, 18: 6, 19: 7, 20: 8}
    adj = {3: -2.0, 4: -1.0, 6: -1.0}.get(n, 0.0)
    k = low.get(min(n, 20), 8)
    return round(sum(diffs[:k]) / k + adj, 1)


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
    diffs = [v for v in (_diff18(d) for d in rounds) if v is not None]
    return {
        "overRating18": round(sum(d["score"]["strokes"] - d["round"]["teeBoxRating"]
                                  for d in rated) / rated_holes * 18, 1) if rated_holes else None,
        "handicapDiff": round(sum(diffs) / len(diffs), 1) if diffs else None,
        "putts18": round(sum(p["totalPutts"] for p in sgp) / holes * 18, 1),
        "threePutts18": round(sum(p["threePutts"] for p in sgp) / holes * 18, 1),
        "penalties18": round(sum(d["strokesGained"]["penaltyStrokes"] for d in rounds)
                             / holes * 18, 1),
        "doubles18": round(sum(d["strokesGained"].get("doublesOrWorse", 0) for d in rounds)
                           / holes * 18, 1),
    }


def _putting_window(rounds: list[dict]) -> list[dict]:
    """Fine putting bands over a window: {label, n, avg, makePct} per band (same row
    shape the dashboard has always rendered, now at vNext granularity)."""
    out = []
    for label, key in PUTT_BANDS:
        putts = [p for d in rounds for b, p in d["_bands"] if b == key]
        n = len(putts)
        out.append({
            "label": label, "n": n,
            "avg": round(sum(putts) / n, 2) if n else None,
            "makePct": round(100 * sum(1 for p in putts if p == 1) / n) if n else None,
        })
    return out


def _cell(value, n_rounds: int, n_obs: int) -> dict:
    return {"value": value, "nRounds": n_rounds, "nObs": n_obs}


def _priority_window(rounds: list[dict]) -> dict:
    """The vNext priority metrics over a window. Annotation-dependent metrics compute
    only over the ANNOTATED rounds in the window (nRounds shows that coverage); with
    zero coverage the dashboard renders '—' rather than pretending."""
    n = len(rounds)
    holes = sum(_holes(d) for d in rounds)
    m = [d["_metrics"] for d in rounds]
    pens = sum(d["strokesGained"]["penaltyStrokes"] for d in rounds)
    dbls = sum(d["strokesGained"]["doublesOrWorse"] for d in rounds)
    opps = sum(x["scrambleOpps"] for x in m)
    saves = sum(x["scrambleSaves"] for x in m)
    p36, m36 = sum(x["putts36"] for x in m), sum(x["makes36"] for x in m)
    p610, m610 = sum(x["putts610"] for x in m), sum(x["makes610"] for x in m)
    plong, plong3 = sum(x["longFirstPutts"] for x in m), sum(x["longThreePutts"] for x in m)

    ann = [d["_ctx"] for d in rounds if d["_ctx"]]
    n_ann = len(ann)

    def asum(key):
        return sum(x[key] for x in ann)

    def pct(num, den):
        return round(100 * num / den) if den else None

    return {
        "penalties18": _cell(round(pens / holes * 18, 1) if holes else None, n, holes),
        "doubles18": _cell(round(dbls / holes * 18, 1) if holes else None, n, holes),
        "cleanSecondShotPct": _cell(pct(asum("tee_clean"), asum("tee_states")) if ann else None,
                                    n_ann, asum("tee_states") if ann else 0),
        "recoveryOneShotPct": _cell(
            pct(asum("recovery_successes"), asum("recovery_attempts")) if ann else None,
            n_ann, asum("recovery_attempts") if ann else 0),
        "normalApproachGirPct": _cell(
            pct(asum("normal_approach_greens"), asum("normal_approaches")) if ann else None,
            n_ann, asum("normal_approaches") if ann else 0),
        "upDownPct": _cell(pct(saves, opps), n, opps),
        "make3to6Pct": _cell(pct(m36, p36), n, p36),
        "make6to10Pct": _cell(pct(m610, p610), n, p610),
        "threePutt30PlusPct": _cell(pct(plong3, plong), n, plong),
    }


def _outcome_section(con) -> dict:
    """Layer-1 Outcome data: quarterly scorecard-objective trends per round scope.

    Scopes: 18-hole rounds (the headline), 9-hole rounds (their own per-9 trend),
    and everything normalized per 18. NO analysis-cutoff filter here — the Outcome
    layer is pure scorecard history, so pre-cutoff and backfilled rounds all count.
    Ratios are per-18 in every scope (the app-wide convention); avgScore is per
    round in h18/h9 and per-18-normalized in 'all'.
    """
    scopes = {
        "h18": {"label": "18-hole", "where": "r.holes_completed >= 18",
                "scoreBasis": "per round (18)", "goal": 90},
        "h9": {"label": "9-hole", "where": "r.holes_completed < 18",
               "scoreBasis": "per round (9)", "goal": 45},
        "all": {"label": "All (per-18)", "where": "TRUE",
                "scoreBasis": "per 18 (normalized)", "goal": 90},
    }
    out = {}
    for key, s in scopes.items():
        rounds = {r[0]: r for r in con.execute(f"""
            SELECT strftime(r.round_date, '%Y') || '-Q' ||
                   CAST((month(r.round_date) + 2) // 3 AS VARCHAR) AS q,
                   count(*),
                   round(avg(CASE WHEN ? = 'all'
                             THEN r.total_strokes * 18.0 / r.holes_completed
                             ELSE r.total_strokes END), 1),
                   round(avg((r.total_strokes - r.tee_rating) * 18.0 / r.holes_completed)
                         FILTER (WHERE r.tee_rating IS NOT NULL), 1)
            FROM canon.round r WHERE {s["where"]}
            GROUP BY q""", [key]).fetchall()}
        # Ratios normalize over RECORDED holes for nullable stats (penalties, putts,
        # GIR, fairways) — backfilled rounds can have '-' cells, and a partial column
        # must not deflate a rate. Score-based stats are always complete.
        holes = {r[0]: r for r in con.execute(f"""
            SELECT strftime(hf.round_date, '%Y') || '-Q' ||
                   CAST((month(hf.round_date) + 2) // 3 AS VARCHAR) AS q,
                   count(*),
                   round(18.0 * sum(hf.penalties)
                         / nullif(count(hf.penalties), 0), 1),
                   round(18.0 * count(*) FILTER (WHERE hf.double_plus) / count(*), 1),
                   round(18.0 * count(*) FILTER (WHERE hf.putts >= 3)
                         / nullif(count(hf.putts), 0), 1),
                   round(100.0 * count(*) FILTER (WHERE hf.gir)
                         / nullif(count(*) FILTER (WHERE hf.gir IS NOT NULL), 0)),
                   round(100.0 * count(*) FILTER (WHERE hf.fairway_outcome = 'HIT')
                         / nullif(count(*) FILTER (WHERE hf.fairway_outcome IS NOT NULL), 0)),
                   round(100.0 * count(*) FILTER (WHERE hf.score_to_par < 0) / count(*), 1),
                   round(100.0 * count(*) FILTER (WHERE hf.score_to_par = 0) / count(*), 1),
                   round(100.0 * count(*) FILTER (WHERE hf.score_to_par = 1) / count(*), 1),
                   round(100.0 * count(*) FILTER (WHERE hf.score_to_par >= 2) / count(*), 1)
            FROM derived.hole_facts hf
            JOIN canon.round r USING (round_id) WHERE {s["where"]}
            GROUP BY q""").fetchall()}
        quarters = []
        for q in sorted(rounds):
            _, n_rounds, avg_score, over_rating = rounds[q]
            h = holes.get(q)
            quarters.append({
                "q": q, "rounds": n_rounds, "holes": h[1] if h else 0,
                "avgScore": avg_score, "overRating18": over_rating,
                "pen18": h[2] if h else None, "dbl18": h[3] if h else None,
                "tp18": h[4] if h else None, "girPct": h[5] if h else None,
                "fwPct": h[6] if h else None,
                "mix": {"birdie": h[7], "par": h[8], "bogey": h[9], "double": h[10]}
                       if h else None,
                "thin": n_rounds < 3,
            })
        out[key] = {"label": s["label"], "scoreBasis": s["scoreBasis"],
                    "goal": s["goal"], "quarters": quarters}
    return out


def _baselines(all_time: dict | None) -> dict:
    """Comparison baselines as per-bucket SG offsets vs scratch. SG-vs-baseline = your
    SG-vs-scratch minus the baseline's. Scratch = 0; My-average = your season norm;
    Target-H = a modeled H-handicap (≈H strokes/18 over scratch, split by weights)."""
    tgt = sg_target()
    h, w = tgt["targetHandicap"], tgt["weights"]
    wsum = sum(w.values()) or 1
    target_by = {c: round(-h * w.get(c, 0) / wsum, 2) for c in SG_CATS}
    # 0-100 zone ≈ inside-50 fully + ~60% of mid-approach.
    sg0_share = (w.get("inside50", 0) + 0.6 * w.get("midApproach", 0)) / wsum
    avg_by = all_time["byCategory"] if all_time else dict.fromkeys(SG_CATS, 0.0)
    avg_sg0 = all_time["sg0to100"] if all_time else 0.0
    return {
        "scratch": {"label": "Scratch", "byCategory": dict.fromkeys(SG_CATS, 0.0),
                    "sg0to100": 0.0},
        "myAverage": {"label": "My average", "byCategory": avg_by, "sg0to100": avg_sg0},
        f"target{h}": {"label": f"Target {h}", "byCategory": target_by,
                       "sg0to100": round(-h * sg0_share, 2), "modeled": True},
    }


def build(through_scorecard_id: int | None = None, write: bool = True) -> dict:
    """Aggregate every window over the analysis set (read from the DuckDB spine).

    `through_scorecard_id` truncates the round list at that round, so a backfilled coach
    report sees the game AS IT STOOD THEN instead of being told about averages drawn from
    rounds that hadn't been played yet. `write=False` keeps that what-if view out of the
    real progress.json.
    """
    from .db import connect
    con = connect()
    rounds = _load_rounds_from_db(con)
    if through_scorecard_id is not None:
        idx = next((i for i, d in enumerate(rounds)
                    if d["scorecardId"] == through_scorecard_id), None)
        if idx is None:
            raise ValueError(f"round {through_scorecard_id} is not in the analysis set")
        rounds = rounds[:idx + 1]
    horizons = {
        "thisRound": [rounds[-1]] if rounds else [],
        "last5": rounds[-RECENT_N:],
        "last10": rounds[-10:],
        "last20": rounds[-20:],
        "allTime": rounds,
    }
    sg = {k: _sg_window(v) for k, v in horizons.items()}
    auth = {k: _auth_window(v) for k, v in horizons.items()}
    putting = {k: _putting_window(v) for k, v in horizons.items()}
    priority = {k: _priority_window(v) for k, v in horizons.items()}

    # Scoring "potential" = better half of rounds (≈ what a handicap measures).
    over_vals = sorted(v for v in (_over_rating18(d) for d in rounds) if v is not None)
    half = max(1, len(over_vals) // 2)

    baselines = _baselines(sg["allTime"])

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
        "baselines": baselines,
        "scoring": {
            "averageOverRating18": auth["allTime"]["overRating18"],
            "potentialOverRating18": round(sum(over_vals[:half]) / half, 1) if over_vals else None,
            "bestOverRating18": over_vals[0] if over_vals else None,
            "garminHandicap": GARMIN_HANDICAP,
            "break90OverRating": BREAK_90_OVER_RATING,
            "handicapIndexEst": _handicap_index(rounds),
        },
        "sg": sg,
        "authoritative": auth,
        "putting": putting,
        "priorityMetrics": priority,
        "outcome": _outcome_section(con),
        "timeSeries": series,
    }
    if write:
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
        _row("Putts", au["thisRound"]["putts18"], au["last5"]["putts18"],
             au["allTime"]["putts18"], "{:.0f}"),
        _row("3-putts", au["thisRound"]["threePutts18"], au["last5"]["threePutts18"],
             au["allTime"]["threePutts18"], "{:.1f}"),
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
