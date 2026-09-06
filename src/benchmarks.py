"""Benchmark read — YOUR measured skills vs published skill-group tables.

Deterministic (no LLM). Lays the player's DB-measured values against Broadie's
Golfmetrics per-group tables (config/benchmarks_broadie.json — real population data,
transcribed verbatim and source-cited). The groups are SCORE-RANGE groups (Am1 70-83,
Am2 84-97, Am3 98-120), so the comparison is "players who shoot what you shoot" vs
"players at the next level" — never a modeled handicap.

    python -m src.benchmarks

Output: data/processed/benchmarks.{json,md}. The md is what the coach prompt ingests;
the coach narrates, this module does all arithmetic.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

CFG = Path("config/benchmarks_broadie.json")
CLUB_STATS = Path("data/processed/club_stats.json")
OUT_JSON = Path("data/processed/benchmarks.json")
OUT_MD = Path("data/processed/benchmarks.md")

AM_GROUPS = ["Am1", "Am2", "Am3"]          # low → high scorers
BAND_MID_FT = {"0-3": 1.5, "3-6": 4.5, "6-10": 8.0, "10-20": 15.0, "20-40": 30.0}

# Real (non-phantom, non-Garmin-excluded) full swings; putts never qualify.
_REAL_SHOT = """FROM canon.shot s
    JOIN derived.shot_geom g USING (shot_id)
    JOIN derived.shot_flags f USING (shot_id)
    WHERE NOT f.phantom AND s.exclude_from_stats IS NOT TRUE AND s.shot_type <> 'PUTT'"""


def load_cfg() -> dict:
    return json.loads(CFG.read_text())


def user_group(avg_score: float, cfg: dict) -> str:
    """The Broadie amateur group whose score range holds this scoring average."""
    for g in AM_GROUPS:
        lo, hi = cfg["groupScoreRanges"][g]
        if avg_score <= hi:
            return g
    return "Am3"


def next_group(group: str) -> str | None:
    i = AM_GROUPS.index(group)
    return AM_GROUPS[i - 1] if i else None


def placement(value: float, groups: dict, better: str) -> str:
    """Where a measured value sits on the published Am3→Am2→Am1 ladder."""
    ladder = [(g, groups[g]) for g in ("Am3", "Am2", "Am1") if g in groups]
    sign = 1 if better == "higher" else -1
    ladder.sort(key=lambda x: sign * x[1])          # worst → best
    if sign * value < sign * ladder[0][1]:
        return f"below {ladder[0][0]}"
    for (g_lo, v_lo), (g_hi, v_hi) in zip(ladder, ladder[1:]):
        if sign * value < sign * v_hi:
            mid = (v_lo + v_hi) / 2
            near = g_lo if sign * value < sign * mid else g_hi
            return f"between {g_lo} and {g_hi} (nearer {near})"
    return f"at/above {ladder[-1][0]}"


def _pct_and_frl(con, lo: int, hi: int, lie: str) -> dict:
    """Green-hit % and median fraction-of-remaining-length for a distance bucket/lie."""
    n, greens, frl = con.execute(f"""
        SELECT count(*),
               count(*) FILTER (WHERE s.end_lie = 'Green'),
               round(100 * median(g.remaining_yds / g.to_pin_before_yds), 1)
        {_REAL_SHOT} AND g.to_pin_before_yds BETWEEN ? AND ? AND s.start_lie = ?""",
        [lo, hi, lie]).fetchone()
    return {"n": n, "greenPct": round(100 * greens / n) if n else None, "medianFrlPct": frl}


def _sand(con) -> dict:
    """Greenside sand (≤50y): save % is hole-level scorecard truth; FRL is per shot."""
    rows = con.execute(f"""
        SELECT DISTINCT s.round_id, s.hole_number {_REAL_SHOT}
          AND s.start_lie = 'Bunker' AND g.to_pin_before_yds <= 50""").fetchall()
    saves = n_holes = 0
    for rid, hn in rows:
        r = con.execute("""
            SELECT scramble_opportunity, scramble_save FROM derived.hole_facts
            WHERE round_id = ? AND hole_number = ?""", [rid, hn]).fetchone()
        if r and r[0]:
            n_holes += 1
            saves += bool(r[1])
    n_shots, frl = con.execute(f"""
        SELECT count(*), round(100 * median(g.remaining_yds / g.to_pin_before_yds), 1)
        {_REAL_SHOT} AND s.start_lie = 'Bunker' AND g.to_pin_before_yds <= 50""").fetchone()
    return {"nHoles": n_holes, "savePct": round(100 * saves / n_holes) if n_holes else None,
            "nShots": n_shots, "medianFrlPct": frl}


def _putting(con) -> dict:
    """50%-one-putt distance (interpolated across band midpoints) + avg 2-putt distance.
    The 0-3 ft band is GPS-unreliable, so interpolation starts at 3-6 ft."""
    rows = dict(con.execute("""
        SELECT band, round(100.0 * avg(CASE WHEN made_first THEN 1 ELSE 0 END))
        FROM derived.putting_bands WHERE first_putt_ft IS NOT NULL GROUP BY band""").fetchall())
    pts = [(BAND_MID_FT[b], rows[b]) for b in ("3-6", "6-10", "10-20", "20-40") if b in rows]
    one_putt_50 = None
    for (d0, m0), (d1, m1) in zip(pts, pts[1:]):
        if m0 >= 50 >= m1 and m0 != m1:
            one_putt_50 = round(d0 + (m0 - 50) * (d1 - d0) / (m0 - m1), 1)
            break
    if one_putt_50 is None and pts and pts[0][1] < 50:
        one_putt_50 = pts[0][0]          # below 50% even at 3-6 ft — floor at that midpoint
    two_putt = con.execute("""
        SELECT round(avg(first_putt_ft)), count(*) FROM derived.putting_bands
        WHERE putts = 2 AND first_putt_ft IS NOT NULL""").fetchone()
    n_first = con.execute("SELECT count(*) FROM derived.putting_bands "
                          "WHERE first_putt_ft IS NOT NULL").fetchone()[0]
    return {"onePutt50PctFt": one_putt_50, "avgTwoPuttFt": two_putt[0],
            "nTwoPutts": two_putt[1], "nFirstPutts": n_first,
            "makePctByBand": {b: rows.get(b) for b in ("3-6", "6-10", "10-20", "20-40")}}


def _awful(con) -> dict:
    """Awful shots (Broadie: shot value < -0.8, putts excluded) per 18 — clean rounds
    only, since an over-recorded round would count swings that never happened."""
    rows = con.execute("""
        SELECT s.round_id, any_value(r.holes_completed),
               count(*) FILTER (WHERE sg.strokes_gained < -0.8)
        FROM canon.shot s
        JOIN derived.shot_sg sg USING (shot_id)
        JOIN derived.shot_flags f USING (shot_id)
        JOIN derived.round_recon rr ON rr.round_id = s.round_id
        JOIN canon.round r ON r.round_id = s.round_id
        WHERE rr.clean AND NOT f.phantom AND sg.sg_category <> 'putting'
        GROUP BY s.round_id""").fetchall()
    if not rows:
        return {"perRound": None, "nRounds": 0}
    rates = [18 * awful / holes for _, holes, awful in rows if holes]
    return {"perRound": round(sum(rates) / len(rates), 1), "nRounds": len(rows)}


def _scoring_level(con, std_rating: float) -> tuple[float | None, float | None, int]:
    """(raw avg, rating-adjusted avg, n) over the last 10 regulation 18-hole rounds.

    Brackets are assigned on the ADJUSTED average: the benchmark population played
    ~standard-rated courses, so a raw average off tees rated ~67 flatters the player
    by the rating gap. Each round is leveled to a standard course first."""
    rows = con.execute("""
        SELECT total_strokes, tee_rating FROM canon.round
        WHERE holes_completed >= 18 AND total_strokes IS NOT NULL
        ORDER BY round_date DESC LIMIT 10""").fetchall()
    if not rows:
        return None, None, 0
    raw = sum(r[0] for r in rows) / len(rows)
    adj = sum(r[0] - (r[1] if r[1] is not None else std_rating) + std_rating
              for r in rows) / len(rows)
    return round(raw, 1), round(adj, 1), len(rows)


def _driver_p75() -> int | None:
    if not CLUB_STATS.exists():
        return None
    for c in json.loads(CLUB_STATS.read_text()).get("clubs", []):
        if c.get("club") == "Driver":
            return c.get("p75Yds")
    return None


def measure(con) -> dict:
    return {
        "approach100to150Fwy": _pct_and_frl(con, 100, 150, "Fairway"),
        "approach100to150Rough": _pct_and_frl(con, 100, 150, "Rough"),
        "short20to60Fwy": _pct_and_frl(con, 20, 60, "Fairway"),
        "short20to60Rough": _pct_and_frl(con, 20, 60, "Rough"),
        "sand": _sand(con),
        "putting": _putting(con),
        "awful": _awful(con),
    }


def _frl_ft(frl_pct: float | None, from_yds: int) -> int | None:
    """Median leave in feet for a shot from `from_yds` at that FRL%."""
    return round(frl_pct / 100 * from_yds * 3) if frl_pct is not None else None


def build_comparison(con) -> dict:
    cfg = load_cfg()
    raw, adj, n_sc = _scoring_level(con, cfg["standardCourseRating"])
    grp = user_group(adj, cfg) if adj else "Am2"
    nxt = next_group(grp)
    m = measure(con)
    t1, t2, t3, t4 = cfg["table1"], cfg["table2"], cfg["table3"], cfg["table4"]

    def metric(key, label, yours, n, groups, better, unit="%", note=None):
        d = {"key": key, "label": label, "yours": yours, "n": n, "unit": unit,
             "groups": {g: groups[g] for g in AM_GROUPS if g in groups}, "betterIs": better}
        if yours is not None:
            d["placement"] = placement(yours, d["groups"], better)
        if note:
            d["note"] = note
        return d

    metrics = [
        metric("green100to150Fwy", "Approach 100-150y (fairway lie): green hit %",
               m["approach100to150Fwy"]["greenPct"], m["approach100to150Fwy"]["n"],
               t2["green100to150FwyPct"], "higher"),
        metric("prox100to150Fwy", "Approach 100-150y (fairway): median leave, % of start",
               m["approach100to150Fwy"]["medianFrlPct"], m["approach100to150Fwy"]["n"],
               t2["medianFrl100to150FwyPct"], "lower", unit="% of start distance",
               note=f"from 125y that is a {_frl_ft(m['approach100to150Fwy']['medianFrlPct'], 125)}ft "
                    f"leave vs {_frl_ft(t2['medianFrl100to150FwyPct'][grp], 125)}ft (your bracket) "
                    f"and {_frl_ft(t2['medianFrl100to150FwyPct'][nxt or grp], 125)}ft (next level)"),
        metric("green100to150Rough", "Approach 100-150y (rough lie): green hit %",
               m["approach100to150Rough"]["greenPct"], m["approach100to150Rough"]["n"],
               t2["green100to150RoughPct"], "higher"),
        metric("green20to60Fwy", "Pitch 20-60y (fairway lie): on green %",
               m["short20to60Fwy"]["greenPct"], m["short20to60Fwy"]["n"],
               t2["green20to60FwyPct"], "higher"),
        metric("prox20to60Fwy", "Pitch 20-60y (fairway): median leave, % of start",
               m["short20to60Fwy"]["medianFrlPct"], m["short20to60Fwy"]["n"],
               t2["medianFrl20to60FwyPct"], "lower", unit="% of start distance",
               note=f"from 40y that is a {_frl_ft(m['short20to60Fwy']['medianFrlPct'], 40)}ft leave "
                    f"vs {_frl_ft(t2['medianFrl20to60FwyPct'][grp], 40)}ft (your bracket) and "
                    f"{_frl_ft(t2['medianFrl20to60FwyPct'][nxt or grp], 40)}ft (next level)"),
        metric("green20to60Rough", "Pitch 20-60y (rough lie): on green %",
               m["short20to60Rough"]["greenPct"], m["short20to60Rough"]["n"],
               t2["green20to60RoughPct"], "higher"),
        metric("sandSave", "Sand save % (greenside bunker, up-and-in)",
               m["sand"]["savePct"], m["sand"]["nHoles"], t1["sandSavePct"], "higher"),
        metric("onePutt50", "Distance you hole 50% of putts (ft)",
               m["putting"]["onePutt50PctFt"], m["putting"]["nFirstPutts"],
               t1["onePutt50PctDistanceFt"], "higher", unit="ft",
               note="GPS-to-green-center distances; directional, not exact"),
        metric("twoPuttDist", "Average 2-putt distance (ft)",
               m["putting"]["avgTwoPuttFt"], m["putting"]["nTwoPutts"],
               t1["avgTwoPuttDistanceFt"], "higher", unit="ft"),
        metric("driverP75", "Tee-shot distance, 75th percentile (yds)",
               _driver_p75(), None, t1["teeDistanceP75Yds"], "higher", unit="yds"),
        metric("awfulShots", "Awful shots per 18 (shot value < -0.8, no putts)",
               m["awful"]["perRound"], m["awful"]["nRounds"],
               t3["awfulShotsPerRound"], "lower", unit="/round",
               note=("clean rounds only; benchmark for your adjusted scoring level: "
                     f"A = 0.24*{adj} - 17.1 = {round(0.24 * adj - 17.1, 1)}" if adj else None)),
    ]

    step_up = None
    if nxt:
        step_up = {cat: round(t4[cat][nxt] - t4[cat][grp], 1)
                   for cat in ("longGame", "shortGame", "putting", "sandGame", "total")}

    return {"source": cfg["_source"], "generated": date.today().isoformat(),
            "avgScore18": raw, "adjScore18": adj,
            "standardCourseRating": cfg["standardCourseRating"], "nScoreRounds": n_sc,
            "yourGroup": grp, "yourGroupScoreRange": cfg["groupScoreRanges"][grp],
            "nextGroup": nxt,
            "nextGroupScoreRange": cfg["groupScoreRanges"].get(nxt) if nxt else None,
            "groupScoreRanges": {g: cfg["groupScoreRanges"][g] for g in AM_GROUPS},
            "stepUpStrokes": step_up, "metrics": metrics}


def _group_labels(doc: dict) -> dict:
    """Human names for the groups — the Am1/Am2/Am3 dataset shorthand must never
    reach the player. Everything downstream speaks in score brackets."""
    labels = {}
    for g, (lo, hi) in doc["groupScoreRanges"].items():
        if g == doc["yourGroup"]:
            labels[g] = "your bracket"
        elif g == doc["nextGroup"]:
            labels[g] = "next level"
        else:
            labels[g] = f"{lo}-{hi} bracket"
    return labels


def render_md(doc: dict) -> str:
    labels = _group_labels(doc)
    lo, hi = doc["yourGroupScoreRange"]
    head = (f"You average {doc['avgScore18']} raw (last {doc['nScoreRounds']} regulation "
            f"rounds), but on tees rated well below standard; leveled to a standard "
            f"course (rating {doc['standardCourseRating']:.0f}, like the benchmark "
            f"population's) that scoring plays as {doc['adjScore18']} — so your bracket "
            f"is {lo}-{hi} shooters.")
    if doc["nextGroup"]:
        nlo, nhi = doc["nextGroupScoreRange"]
        head += f" The next level is the {nlo}-{nhi} bracket."
    lines = [
        "=== BENCHMARK READ — you vs PUBLISHED skill brackets (measured population "
        "data, not a model) ===",
        f"Source: {doc['source']['citation']}",
        "Brackets group golfers by what they SCORE, so 'your bracket' = players who "
        "shoot what you shoot.",
        head,
        "",
    ]
    for mt in doc["metrics"]:
        if mt["yours"] is None:
            continue
        gs = " | ".join(f"{labels[g]} {mt['groups'][g]}" for g in ("Am3", "Am2", "Am1")
                        if g in mt["groups"])
        n = f", n={mt['n']}" if mt.get("n") else ""
        place = mt.get("placement", "?")
        for g, lbl in labels.items():
            place = place.replace(g, lbl)
        lines.append(f"- {mt['label']}: YOU {mt['yours']}{n} vs {gs} -> you sit {place}")
        if mt.get("note"):
            lines.append(f"    ({mt['note']})")
    if doc["stepUpStrokes"]:
        s = doc["stepUpStrokes"]
        lines += ["",
                  f"What separates your bracket from the next level, per Broadie's "
                  f"shot-value table (strokes per round, of {s['total']} total): long game "
                  f"{s['longGame']}, short game {s['shortGame']}, putting {s['putting']}, "
                  f"sand {s['sandGame']}.",
                  "Read: the long game is most of the gap for every amateur step-up — but "
                  "coach to the specific rows above where this player lags his own bracket."]
    return "\n".join(lines) + "\n"


def build(write: bool = True) -> dict:
    from .db import connect
    doc = build_comparison(connect())
    if write:
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(json.dumps(doc, indent=2))
        OUT_MD.write_text(render_md(doc))
        print(f"  benchmarks -> {OUT_MD}")
    return doc


def main() -> None:
    doc = build()
    print(render_md(doc))


if __name__ == "__main__":
    main()
