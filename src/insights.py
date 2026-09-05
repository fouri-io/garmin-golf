"""Insights — the player-development intelligence layer (deterministic, no LLM).

Answers: how is my golf changing, why, and what should matter next?

Everything here is computed from the DuckDB spine + existing processed exports and
written to data/processed/insights.{json,md}. The signature output is the
Performance Cone: rolling ceiling (p20), median (p50) and floor (p80) of
score-vs-rating per 18, over every rated round from every source. Improvement =
the cone moving down; mastery = the cone narrowing.

Candidate insights are generated from fixed templates over measured deltas, scored
by magnitude x confidence x weight, and only the top slice is surfaced — insights,
not dashboards. Context rules follow the house hierarchy: annotation-dependent
metrics carry their coverage and degrade to "emerging signal", never fabricate.

Usage:  python -m src.insights
"""

from __future__ import annotations

import json
from pathlib import Path

from .constants import SG_LABELS

OUT_JSON = Path("data/processed/insights.json")
OUT_MD = Path("data/processed/insights.md")
PROGRESS = Path("data/processed/progress.json")
CLUB_STATS = Path("data/processed/club_stats.json")

CONE_WINDOW = 16          # rolling rounds per cone point
CONE_PROVISIONAL = 8      # dashed 'forming' cone from here; tails are biased narrow
CONE_MIN = CONE_WINDOW    # solid cone + all comparisons use full windows only
RECENT_N = 10             # "last N vs previous N" trend windows
MID_IRON_TYPE_IDS = {15, 16, 17, 18}   # 6i-9i: the mid-iron miss-pattern family


def _pct(vals: list[float], p: float) -> float:
    vals = sorted(vals)
    if len(vals) == 1:
        return vals[0]
    k = (len(vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(vals) - 1)
    return vals[f] + (vals[c] - vals[f]) * (k - f)


def cone_series(over18: list[float], window: int = CONE_WINDOW) -> list[dict]:
    """Rolling p20/p50/p80. Points exist from CONE_PROVISIONAL rounds but carry
    full=False until the window fills — sub-window percentiles systematically
    understate the tails, so provisional points render dashed and are never used
    for start/current comparisons."""
    out = []
    for i in range(len(over18)):
        lo = max(0, i - window + 1)
        w = over18[lo:i + 1]
        if len(w) < CONE_PROVISIONAL:
            continue
        out.append({"i": i, "p20": round(_pct(w, .2), 1), "p50": round(_pct(w, .5), 1),
                    "p80": round(_pct(w, .8), 1), "full": len(w) >= window})
    return out


def _conf(n: int) -> tuple[float, str]:
    """(score multiplier, label) from sample size."""
    if n >= 20:
        return 1.0, "High confidence"
    if n >= 10:
        return 0.8, "Moderate confidence"
    return 0.45, "Emerging signal"


def _cand(cat: str, text: str, magnitude: float, n: int, weight: float = 1.0) -> dict:
    mult, label = _conf(n)
    return {"cat": cat, "text": text, "confidence": label,
            "score": round(min(1.0, abs(magnitude)) * mult * weight * 100)}


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _load_rounds(con) -> list[dict]:
    """Per-round outcome metrics for every rated round, all sources, chronological."""
    rows = con.execute("""
        WITH hf AS (
          SELECT round_id,
                 count(*)                                             AS holes,
                 18.0*sum(penalties)/nullif(count(penalties),0)       AS pen18,
                 18.0*count(*) FILTER (WHERE double_plus)/count(*)    AS dbl18,
                 18.0*count(*) FILTER (WHERE putts>=3)
                     /nullif(count(putts),0)                          AS tp18,
                 100.0*count(*) FILTER (WHERE gir)
                     /nullif(count(*) FILTER (WHERE gir IS NOT NULL),0) AS gir_pct,
                 100.0*count(*) FILTER (WHERE score_to_par<=1)/count(*) AS bob_pct
          FROM derived.hole_facts GROUP BY round_id)
        SELECT r.round_date, (r.total_strokes-r.tee_rating)*18.0/r.holes_completed,
               r.source, hf.pen18, hf.dbl18, hf.tp18, hf.gir_pct, hf.bob_pct
        FROM canon.round r JOIN hf USING (round_id)
        WHERE r.tee_rating IS NOT NULL AND r.holes_completed > 0
        ORDER BY r.start_time""").fetchall()
    keys = ["date", "over18", "source", "pen18", "dbl18", "tp18", "girPct", "bobPct"]
    return [dict(zip(keys, [str(r[0])] + [round(v, 1) if isinstance(v, float) else v
                                          for v in r[1:]])) for r in rows]


def _trend(rounds: list[dict], key: str) -> dict | None:
    """last-10 vs previous-10 means for a per-round metric."""
    vals = [r[key] for r in rounds]
    if len([v for v in vals if v is not None]) < 2 * RECENT_N:
        return None
    now, prev = _mean(vals[-RECENT_N:]), _mean(vals[-2 * RECENT_N:-RECENT_N])
    if now is None or prev is None:
        return None
    return {"now": round(now, 1), "prev": round(prev, 1), "delta": round(now - prev, 1)}


def _mid_iron_miss(clubs: list[dict]) -> dict | None:
    tot = {"n": 0, "left": 0.0, "right": 0.0, "short": 0.0}
    for c in clubs:
        d = c.get("dispersion")
        if not d or c.get("clubTypeId") not in MID_IRON_TYPE_IDS:
            continue
        n = d["approachShots"]
        tot["n"] += n
        tot["left"] += d["leftPct"] * n / 100
        tot["right"] += d["rightPct"] * n / 100
        tot["short"] += d["shortPct"] * n / 100
    if tot["n"] < 20:
        return None
    return {"n": tot["n"],
            "leftPct": round(100 * tot["left"] / tot["n"]),
            "rightPct": round(100 * tot["right"] / tot["n"]),
            "shortPct": round(100 * tot["short"] / tot["n"])}


def build(write: bool = True) -> dict:
    from .db import connect
    con = connect()
    rounds = _load_rounds(con)
    progress = json.loads(PROGRESS.read_text()) if PROGRESS.exists() else {}
    club_doc = json.loads(CLUB_STATS.read_text()) if CLUB_STATS.exists() else {"clubs": []}

    over = [r["over18"] for r in rounds]
    series = cone_series(over)
    fulls = [p for p in series if p["full"]]
    cur = fulls[-1] if fulls else None
    first = fulls[0] if fulls else None

    current = start = None
    if cur and first:
        current = {"ceiling": cur["p20"], "median": cur["p50"], "floor": cur["p80"],
                   "gap": round(cur["p80"] - cur["p20"], 1), "date": rounds[cur["i"]]["date"]}
        start = {"ceiling": first["p20"], "median": first["p50"], "floor": first["p80"],
                 "gap": round(first["p80"] - first["p20"], 1), "date": rounds[first["i"]]["date"]}

    # ---- top-of-page summary (deterministic) ----
    summary = "Not enough rated rounds yet to judge the cone — keep playing."
    if current and start:
        f_imp = round(start["floor"] - current["floor"], 1)      # + = floor better
        c_imp = round(start["ceiling"] - current["ceiling"], 1)  # + = ceiling better
        g_chg = round(start["gap"] - current["gap"], 1)          # + = narrower
        driver = ("raising your floor" if f_imp > c_imp + 1.5 else
                  "raising your ceiling" if c_imp > f_imp + 1.5 else
                  "moving your whole game down together")
        gap_txt = (f"your round-to-round range has narrowed from {start['gap']:.0f} to "
                   f"{current['gap']:.0f} strokes" if g_chg >= 1 else
                   f"your round-to-round range has widened from {start['gap']:.0f} to "
                   f"{current['gap']:.0f} strokes" if g_chg <= -1 else
                   f"your round-to-round range is steady near {current['gap']:.0f} strokes")
        summary = (f"Your scoring has improved primarily by {driver}: bad rounds are "
                   f"{abs(f_imp):.0f} strokes {'better' if f_imp >= 0 else 'worse'} than when "
                   f"tracking began, your best golf is {abs(c_imp):.0f} strokes "
                   f"{'better' if c_imp >= 0 else 'worse'}, and {gap_txt}.")

    # ---- candidate insights ----
    cands: list[dict] = []
    n_rounds = len(rounds)
    if current and start:
        lt = round(start["median"] - current["median"], 1)
        if abs(lt) >= 2:
            cands.append(_cand("Development",
                f"Your typical scoring level has improved {lt:.0f} strokes per 18 since "
                f"tracking began ({start['median']:.0f} over rating → {current['median']:.0f}).",
                lt / 15, n_rounds, 1.3))
        if abs(start["floor"] - current["floor"]) >= 2:
            d = start["floor"] - current["floor"]
            cands.append(_cand("Development",
                f"Your scoring floor (bad-but-normal golf) has improved {d:.0f} strokes "
                f"— blow-up rounds now land near +{current['floor']:.0f} instead of "
                f"+{start['floor']:.0f}.", d / 10, n_rounds, 1.2))
        if abs(start["ceiling"] - current["ceiling"]) >= 2:
            d = start["ceiling"] - current["ceiling"]
            cands.append(_cand("Development",
                f"Your ceiling has improved {d:.0f} strokes — your best golf now runs about "
                f"+{current['ceiling']:.0f} vs rating.", d / 10, n_rounds, 1.1))
        if abs(start["gap"] - current["gap"]) >= 1.5:
            d = start["gap"] - current["gap"]
            word = "narrowed" if d > 0 else "widened"
            cands.append(_cand("Reliability",
                f"Your reliability gap has {word} from {start['gap']:.0f} to "
                f"{current['gap']:.0f} strokes — "
                f"{'your bad golf is becoming much less expensive' if d > 0 else 'form is getting streakier'}.",
                d / 8, n_rounds, 1.2))
        f_imp, c_imp = start["floor"] - current["floor"], start["ceiling"] - current["ceiling"]
        if f_imp > c_imp + 2:
            cands.append(_cand("Reliability",
                f"Most of your improvement is reliability, not peak performance: the floor "
                f"has moved {f_imp:.0f} strokes to the ceiling's {c_imp:.0f}. Fewer disasters, "
                f"similar best golf.", (f_imp - c_imp) / 8, n_rounds, 1.1))

    for key, label, unit, good_down, scale in (
            ("pen18", "Penalties", "per 18", True, 2.0),
            ("dbl18", "Doubles+", "per 18", True, 2.5),
            ("tp18", "3-putts", "per 18", True, 2.0)):
        t = _trend(rounds, key)
        if t and abs(t["delta"]) >= 0.5:
            better = (t["delta"] < 0) == good_down
            cands.append(_cand("Scoring structure",
                f"{label} are {'down' if t['delta'] < 0 else 'up'} from {t['prev']} to "
                f"{t['now']} {unit} over your last {RECENT_N} rounds"
                f"{' — one of the cleanest floor-raisers there is.' if better and key != 'tp18' else '.'}",
                t["delta"] / scale, 2 * RECENT_N, 1.0 if better else 1.1))
    t = _trend(rounds, "bobPct")
    if t and abs(t["delta"]) >= 4:
        cands.append(_cand("Scoring structure",
            f"Bogey-or-better holes have {'risen' if t['delta'] > 0 else 'fallen'} from "
            f"{t['prev']:.0f}% to {t['now']:.0f}% over your last {RECENT_N} rounds.",
            t["delta"] / 12, 2 * RECENT_N, 1.0))

    # club insights
    full_swing = [c for c in club_doc.get("clubs", []) if c.get("medianYds")]
    if full_swing:
        top = max(full_swing, key=lambda c: c["distanceShots"])
        cands.append(_cand("Clubs",
            f"Your on-course {top['club']} median is {top['medianYds']} yards over "
            f"{top['distanceShots']} stock swings (typical window "
            f"{top['p25Yds']}–{top['p75Yds']}). Trust the median, not the best strike.",
            0.5, top["distanceShots"], 0.9))
    miss = _mid_iron_miss(club_doc.get("clubs", []))
    if miss:
        side = "right" if miss["rightPct"] >= miss["leftPct"] else "left"
        side_pct = max(miss["rightPct"], miss["leftPct"])
        if side_pct >= 42 or miss["shortPct"] >= 60:
            cands.append(_cand("Miss pattern",
                f"Short-{side} is your dominant mid-iron miss: across {miss['n']} 6i–9i "
                f"approaches, {miss['shortPct']}% finish short and {side_pct}% miss {side}. "
                f"One more club and a start line adjustment attack both.",
                max(side_pct - 33, miss["shortPct"] - 50) / 30, miss["n"], 1.15))

    # process metrics (annotation-driven) — honest about coverage
    pm = (progress.get("priorityMetrics") or {}).get("allTime") or {}
    for key, label in (("cleanSecondShotPct", "Clean second-shot rate"),
                       ("recoveryOneShotPct", "One-shot recovery success"),
                       ("normalApproachGirPct", "Normal-approach GIR")):
        c = pm.get(key) or {}
        if c.get("value") is not None:
            cands.append(_cand("Process",
                f"{label} is {c['value']}% across {c['nRounds']} annotated round"
                f"{'s' if c['nRounds'] != 1 else ''} (n={c['nObs']}) — annotate more rounds "
                f"to make this trendable.", 0.5, c["nRounds"], 0.7))

    cands.sort(key=lambda x: -x["score"])
    insights = cands[:6]

    # ---- floor drivers: last 10 vs previous 10 ----
    drivers = []
    for key, label, good_down, flat in (("pen18", "Penalties /18", True, 0.4),
                                        ("dbl18", "Doubles+ /18", True, 0.5),
                                        ("tp18", "3-putts /18", True, 0.4),
                                        ("girPct", "GIR %", False, 3.0),
                                        ("bobPct", "Bogey-or-better %", False, 3.0)):
        t = _trend(rounds, key)
        if not t:
            continue
        better = (t["delta"] < -flat) if good_down else (t["delta"] > flat)
        worse = (t["delta"] > flat) if good_down else (t["delta"] < -flat)
        drivers.append({"label": label, "prev": t["prev"], "now": t["now"],
                        "delta": t["delta"],
                        "verdict": "improving" if better else "worse" if worse else "flat"})

    # ---- priorities (1-3, evidence-linked) ----
    priorities = []
    if miss and (miss["shortPct"] >= 60 or max(miss["rightPct"], miss["leftPct"]) >= 42):
        side = "right" if miss["rightPct"] >= miss["leftPct"] else "left"
        gir_now = _trend(rounds, "girPct")
        priorities.append({
            "text": f"Approach distance + start line: take one more club and start it "
                    f"{'left' if side == 'right' else 'right'} of target on mid-irons.",
            "evidence": f"{miss['shortPct']}% of {miss['n']} mid-iron approaches finish short, "
                        f"{max(miss['rightPct'], miss['leftPct'])}% miss {side}; GIR "
                        f"{'is ' + str(gir_now['now']) + '%' if gir_now else 'remains low'}."})
    sg10 = ((progress.get("sg") or {}).get("last10") or {}).get("byCategory")
    if sg10:
        worst = min(sg10, key=lambda k: sg10[k])
        priorities.append({
            "text": f"Biggest strokes leak right now: {SG_LABELS[worst]}.",
            "evidence": f"{sg10[worst]:+.1f} strokes per 18 vs scratch over your last 10 "
                        f"clean rounds — the worst of your five SG buckets."})
    ann_rounds = max((int((pm.get(k) or {}).get("nRounds") or 0)
                      for k in ("cleanSecondShotPct", "recoveryOneShotPct",
                                "normalApproachGirPct")), default=0)
    if ann_rounds < 3:
        priorities.append({
            "text": "Annotate more rounds — the process layer is your differentiator and "
                    "it's running on minimal context.",
            "evidence": f"Clean-2nd-shot, recovery and normal-approach metrics currently "
                        f"cover {ann_rounds} annotated round{'s' if ann_rounds != 1 else ''}; "
                        f"3–5 makes them trendable."})
    priorities = priorities[:3]

    doc = {
        "generatedFromRounds": n_rounds,
        "basis": "score vs course rating, per 18 (all rated rounds, every source)",
        "window": CONE_WINDOW,
        "summary": summary,
        "current": current,
        "start": start,
        "cone": {
            "rounds": [{"date": r["date"], "v": r["over18"], "src": r["source"]}
                       for r in rounds],
            "points": [{"date": rounds[p["i"]]["date"], **{k: p[k] for k in
                        ("i", "p20", "p50", "p80", "full")}} for p in series],
        },
        "insights": insights,
        "floorDrivers": drivers,
        "priorities": priorities,
        "note": ("Deterministic: every sentence is generated from measured windows "
                 "(cone = rolling p20/p50/p80 of score vs rating; trends = last 10 vs "
                 "previous 10). Annotation-dependent metrics show their coverage."),
    }
    if write:
        OUT_JSON.write_text(json.dumps(doc, indent=2))
        OUT_MD.write_text(render_markdown(doc))
    return doc


def render_markdown(doc: dict) -> str:
    lines = ["# Insights — how is my golf changing?", "", doc["summary"], ""]
    if doc["current"]:
        c, s = doc["current"], doc["start"]
        lines += [f"Cone (rolling {doc['window']} rounds, {doc['basis']}):",
                  f"  ceiling {s['ceiling']} → {c['ceiling']} · median {s['median']} → "
                  f"{c['median']} · floor {s['floor']} → {c['floor']} · gap {s['gap']} → "
                  f"{c['gap']}", ""]
    lines.append("## What changed")
    for i in doc["insights"]:
        lines.append(f"- [{i['cat']} · {i['confidence']}] {i['text']}")
    lines.append("")
    lines.append("## Floor drivers (last 10 vs previous 10)")
    for d in doc["floorDrivers"]:
        lines.append(f"- {d['label']}: {d['prev']} → {d['now']} ({d['verdict']})")
    lines.append("")
    lines.append("## What to focus on")
    for i, p in enumerate(doc["priorities"], 1):
        lines.append(f"{i}. {p['text']}  _({p['evidence']})_")
    return "\n".join(lines) + "\n"


def main() -> None:
    doc = build()
    print(f"Wrote {OUT_JSON} and {OUT_MD}")
    print(f"  {doc['summary']}")


if __name__ == "__main__":
    main()
