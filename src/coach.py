"""AI coach — a brief, personalized round report via the Anthropic API.

Grounded in the living golfer spec (config/golfer_profile.md) + auto-generated current
form/trend (from progress.json) + the round just played. Degrades gracefully: if there's
no ANTHROPIC_API_KEY (or the anthropic package isn't installed), it skips without breaking
the pipeline.

    python -m src.coach           # report on the most recent round

Output: data/processed/coach/<round_stem>.md (+ latest.md), and context.md (the
assembled state, for transparency).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

from .constants import POLLUTION_DELTA, SG_LABELS
from .putting import putt_buckets

PROFILE = Path("config/golfer_profile.md")
PROGRESS = Path("data/processed/progress.json")
ROUNDS_DIR = Path("data/processed/rounds")
OUT_DIR = Path("data/processed/coach")
DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-8"
DEFAULT_OPENAI_MODEL = "gpt-4o"

SYSTEM = (
    "You are this golfer's personal coach AND a master golf data analyst. You know "
    "Strokes Gained cold. You are concise, specific, and honest — you never pad. You "
    "frame everything through the player's own philosophy: build the golfer not the "
    "round; eliminate penalties and doubles; play dispersion; the worst bucket explains "
    "the score.\n\n"
    "DATA-QUALITY RULES YOU MUST RESPECT:\n"
    "- The SCORECARD is truth: each hole's `putts` value, strokes, penalties, and the "
    "round totals are authoritative. The per-shot list is GPS sensor data and is "
    "IMPERFECT.\n"
    "- PUTTS: NEVER count putt shots in the shot list to claim an 'N-putt hole'. The "
    "sensor often records phantom/extra putts (e.g. a practice putt struck after holing "
    "out). Use ONLY the hole's `putts` field and the round putt total. If the shot list "
    "shows more putts than the hole's `putts`, the extras are NOT real — ignore them and "
    "do not mention a 'six-putt' etc. that the scorecard doesn't support.\n"
    "- PHANTOM FULL SWINGS: the sensor also over-records full shots (practice swings, "
    "range balls, a club re-gripped). If you are told the round is OVER-RECORDED, the "
    "shot list contains strokes that never happened, so the per-shot SG buckets for "
    "that round are UNRELIABLE — do not name a worst bucket from them, never say a "
    "hole 'needed extra swings' because the list shows them, and do not build practice "
    "advice on them. Lean on the authoritative stats instead: score, putts, penalties, "
    "fairways, GIR, up-and-downs.\n"
    "- LEVELING: judge how the round compares to the player using SCORE OVER COURSE "
    "RATING per 18 (provided), NOT over par. Par != rating, and he plays easier-rated "
    "tees. A round whose over-rating/18 is BELOW his average is a GOOD round; near his "
    "'potential' is very good. Use the numbers provided — do not invent extrapolations.\n"
    "- SG reliability: off-the-tee and full-approach SG are reliable; putting and "
    "inside-50 (short-game) SG are GPS-approximate (directional, not exact); the absolute "
    "SG total runs a few strokes hot — trust the RANKING of buckets over absolute numbers. "
    "Negative SG vs scratch is normal.\n"
    "- PUTTING BY DISTANCE: you are given putting bucketed by first-putt distance "
    "(authoritative counts). Judge putting by DISTANCE BAND, not by raw 3-putt count: a "
    "3-putt from 30+ ft is roughly expected and is NOT a fault; the real leak is weak "
    "conversion inside ~20 ft (high avg putts / low make%). Distance is GPS to green "
    "CENTER, so a ball on a green edge reads SHORTER than reality — do not over-penalize "
    "long lag, and treat the 0–10 ft bucket as unreliable.\n"
    "- WEDGES VARY BY DESIGN: the player hits his wedges (PW/GW/50/54/58) DIFFERENT "
    "distances by shot demand on purpose. NEVER cite a spread of wedge/54° yardages (e.g. "
    "'21y, 27y, 15y') as 'inconsistent' or 'unstable contact' — that is intentional "
    "shot-making. Judge the short game on PROXIMITY / up-and-down / the Inside-50 & "
    "scoring-zone SG, not on yardage uniformity.\n"
    "- LEAD WITH WHAT HE CARES ABOUT: his #1 priority is the SCORING ZONE (SG 0–100, "
    "100yd & in). You are given this round's SG 0–100 vs his average — if it beat his "
    "average, SAY SO up front as real progress; if it lagged, that's the headline leak. "
    "Tie practice advice to his stated 2026 Q-plan priorities in the profile, in order.\n"
    "- COURSE MEMORY: the course-history ledger is deterministic data across all his "
    "tracked rounds there. Use it for hole-specific coaching (his trap holes, holes the "
    "card rates easy but he bleeds on, holes he has conquered). If told it is his FIRST "
    "tracked round at a course, you have NO history there — never imply otherwise.\n"
    "- CONTINUITY: when a previous report is provided, you are a coach with a memory — "
    "verify whether your last prescription showed up in this round's numbers before "
    "issuing new advice. Changing advice every round with no follow-through reads as noise.\n"
    "- TIER COMPARISON: the vs-target-handicap gaps are from a MODELED tier baseline "
    "(clearly labeled). Use them to size opportunities ('this bucket is what separates "
    "you from a 15') but always call the tier modeled, never measured.\n"
    "- BENCHMARK READ: the benchmark block compares his MEASURED stats to published "
    "population tables (Broadie, Golfmetrics). The brackets group golfers by what they "
    "SCORE on a standard-rated course — the block levels his easier-tee scores before "
    "assigning his bracket, and its header names his bracket and the next level; use "
    "THOSE score ranges, never assume them. Unlike the modeled tier, this is real "
    "measured data — state comparisons plainly and concretely ('your 40-yard pitches "
    "finish 41 ft away; players who shoot what you shoot leave 24 ft'). Respect the n= "
    "sample counts; never call the brackets handicaps.\n"
    "- PLAIN WORDS ONLY: never let dataset shorthand reach the player. No 'Am1'/'Am2'/"
    "'Am3' (say 'players who shoot 84-97' / 'your bracket' / 'the next level'), no "
    "'pens' (say 'penalties'), no 'FRL', no internal metric keys. If a term needs a "
    "legend to decode, rewrite it.\n"
    "- FOCUS ADHERENCE: when the previous report's next-round focus bullets are provided "
    "separately, grade EACH one in the Trend read — followed, partly, or not — from this "
    "round's numbers, before adding anything new.\n"
    "- ESCALATION CHAINS: the escalation block is built from the player's OWN confirmed "
    "hole tags. 'Compounded' means one bad shot became several through the follow-up "
    "decision; 'preventable escalation' is his own admission the blow-up was avoidable. "
    "These are decision leaks, not swing leaks — coach the decision.\n"
    "- DOUBLES ANATOMY: the doubles list is authoritative. His #1 scoring lever is "
    "converting doubles+ to bogeys — when doubles were absent or fewer, celebrate that "
    "explicitly before anything else."
)

PROMPT = """Write a BRIEF round report for the player. Use these sections, short and tight:

**Overall** — 2-3 sentences: how the round went vs their level/trend.
**What cost strokes** — the 1-2 biggest leaks this round (worst SG bucket(s) + the doubles
anatomy), with the "why". Name the specific holes where the score got away.
**Course read** — ONLY if course history is provided: 2-3 sentences connecting this round to
their hole-by-hole pattern at this course (their trap holes, card-vs-you inversions, hole
trends). If it was their first tracked round at the course, say so and note what to log for
next time instead.
**Putting by distance** — long-lag 3-putts (≈ expected) vs weak short/mid conversion (the
fixable part), by band; never judge on raw 3-putt count.
**Trend read** — improving / flat / slipping vs recent form. If previous focus bullets are
provided, OPEN this section by grading each one against this round's evidence
("last time: X — this round says ..."); otherwise check the previous report's prescription.
**Benchmark read** — REQUIRED whenever the published-benchmark block is present (omit the
section only when there is no block; never drop it for length): 2-4 sentences with
TWO reference points on every comparison, because he is climbing, not holding: his own
bracket (is he keeping pace with players who shoot what he shoots) AND the next level up
(the target). Lead with the block's climb read: what to close first (behind his own
bracket) vs what to push to next-level numbers (already ahead of his bracket). Quote the
numbers (leaves in feet, green %, awful shots) and name brackets in plain words with score
ranges, never Am1/Am2 shorthand. Measured population data — no hedging about models.
**Next-round focus** — exactly 1-3 bullets. Each must cite a number from the data provided
(course ledger, benchmark read, doubles anatomy, escalation chains, or putting bands). No
generic advice. These bullets are tracked and graded in your next report — make each one
checkable against data.

Keep it under ~450 words. No fluff. Speak to them directly. Every listed section that has
data provided must appear — trim sentences, never sections.

=== PLAYER PROFILE ===
{profile}

=== CURRENT FORM & TREND (auto-generated) ===
{state}

=== PUTTING BY FIRST-PUTT DISTANCE (authoritative counts) ===
{putting}
{insights}{course}{tier}{benchmark}{anatomy}{escalation}{prev_report}{prev_focus}
=== THE ROUND JUST PLAYED ===
{round_md}
{annotations}"""

ANNOTATIONS_HEADER = """
=== PLAYER'S OWN POST-ROUND NOTES (first-hand context — weight these heavily) ===
The player wrote these notes and confirmed the shot tags. A shot tagged
recovery/punch/layup was deliberate trouble management, NOT a bad swing — judge the
DECISION and whether it restored normal golf, and never treat its distance as a
stock yardage.
"""


INSIGHTS_MD = Path("data/processed/insights.md")


def _rid_from_stem(stem: str) -> int:
    return int(stem.rsplit("_", 1)[1])


def course_ledger(con, course_global_id: int) -> list[dict]:
    """Per-hole ledger across every 18-hole-scored visit to a course (deterministic).
    Testable core of the coach's course memory."""
    rows = con.execute("""
        SELECT h.hole_number, any_value(h.par), any_value(h.stroke_index), count(*),
               round(avg(h.strokes - h.par), 2),
               round(100.0*count(*) FILTER (WHERE hf.double_plus)/count(*)),
               coalesce(sum(h.penalties), 0)
        FROM canon.hole h
        JOIN derived.hole_facts hf ON hf.round_id=h.round_id AND hf.hole_number=h.hole_number
        JOIN canon.round r ON r.round_id=h.round_id
        WHERE r.course_global_id = ? AND h.strokes IS NOT NULL
        GROUP BY h.hole_number ORDER BY h.hole_number""", [course_global_id]).fetchall()
    keys = ["hole", "par", "si", "plays", "avgOver", "dblPct", "pens"]
    return [dict(zip(keys, r)) for r in rows]


def _hole_trends(con, course_global_id: int) -> list[str]:
    """Holes clearly improving/worsening across visits (first half vs second half)."""
    rows = con.execute("""
        WITH plays AS (
          SELECT h.hole_number, h.strokes - h.par AS over,
                 row_number() OVER (PARTITION BY h.hole_number ORDER BY r.start_time) AS k,
                 count(*) OVER (PARTITION BY h.hole_number) AS n
          FROM canon.hole h JOIN canon.round r USING (round_id)
          WHERE r.course_global_id = ? AND h.strokes IS NOT NULL)
        SELECT hole_number,
               round(avg(over) FILTER (WHERE k <= n/2), 2) AS early,
               round(avg(over) FILTER (WHERE k > n/2), 2)  AS late, any_value(n)
        FROM plays WHERE n >= 6 GROUP BY hole_number""", [course_global_id]).fetchall()
    out = []
    for hole, early, late, n in rows:
        if early is None or late is None:
            continue
        d = late - early
        if d <= -0.6:
            out.append(f"H{hole}: improving ({early:+.1f} early visits -> {late:+.1f} recent)")
        elif d >= 0.6:
            out.append(f"H{hole}: worsening ({early:+.1f} early visits -> {late:+.1f} recent)")
    return out


def _course_block(stem: str) -> str:
    from .db import connect
    con = connect()
    row = con.execute("""
        SELECT course_global_id, course_name, start_time FROM canon.round
        WHERE round_id = ?""", [_rid_from_stem(stem)]).fetchone()
    if not row or row[0] is None:
        return ""
    cgid, cname, start = row
    prior = con.execute("""
        SELECT count(*) FROM canon.round
        WHERE course_global_id = ? AND start_time < ?""", [cgid, start]).fetchone()[0]
    if prior == 0:
        return (f"\n=== COURSE CONTEXT ===\nFIRST TRACKED ROUND AT {cname}. You have no "
                "history here — do NOT claim hole-specific patterns at this course. "
                "Coach in scouting mode: judge decisions and process, and suggest what "
                "to note for next time.\n")
    ledger = course_ledger(con, cgid)
    if not ledger:
        return ""
    hardest = sorted(ledger, key=lambda x: -(x["avgOver"] or 0))[:5]
    easiest = min(ledger, key=lambda x: x["avgOver"] or 0)
    # SI inversions: your rank differs sharply from the card's difficulty rank
    ranked = sorted(ledger, key=lambda x: -(x["avgOver"] or 0))
    n = len(ranked)
    inversions = []
    for yr, hrow in enumerate(ranked, 1):
        if hrow["si"] is None:
            continue
        if yr <= 5 and hrow["si"] >= n - 5:
            inversions.append(f"H{hrow['hole']} is the card's #{hrow['si']} handicap "
                              f"(easy) but YOUR #{yr} hardest ({hrow['avgOver']:+.2f})")
        if yr >= n - 4 and hrow["si"] <= 5:
            inversions.append(f"H{hrow['hole']} is the card's #{hrow['si']} handicap "
                              f"(hard) but you handle it ({hrow['avgOver']:+.2f})")
    lines = [f"\n=== YOUR HISTORY AT {cname.upper()} (deterministic, "
             f"{prior + 1} tracked rounds) ==="]
    lines.append("Your hardest holes: " + " · ".join(
        f"H{h['hole']} (par {h['par']}, SI {h['si']}): {h['avgOver']:+.2f}, "
        f"{h['dblPct']:.0f}% doubles, {h['pens']} penalties" for h in hardest))
    lines.append(f"Your best hole: H{easiest['hole']} ({easiest['avgOver']:+.2f} avg).")
    for iv in inversions[:3]:
        lines.append("Card-vs-you: " + iv)
    trends = _hole_trends(con, cgid)
    if trends:
        lines.append("Hole trends: " + " · ".join(trends[:4]))
    return "\n".join(lines) + "\n"


def _insights_block() -> str:
    if not INSIGHTS_MD.exists():
        return ""
    txt = INSIGHTS_MD.read_text()[:2600]
    return "\n=== SEASON INSIGHTS BRIEF (deterministic — trends, cone, priorities) ===\n" + txt


BENCHMARKS_MD = Path("data/processed/benchmarks.md")
FOCUS_JSON = OUT_DIR / "focus.json"


def _benchmark_block() -> str:
    """Measured-vs-published comparison (src/benchmarks.py output, source-cited).
    Fed whole: a truncated block once cost the report its entire Benchmark read —
    the climb summary lives at the bottom."""
    if not BENCHMARKS_MD.exists():
        return ""
    return "\n" + BENCHMARKS_MD.read_text()[:4500]


def extract_focus(report: str) -> list[str]:
    """The next-round focus bullets from a written report (for adherence tracking)."""
    bullets, in_focus = [], False
    for line in report.splitlines():
        s = line.strip()
        if "next-round focus" in s.lower():
            in_focus = True
            continue
        if in_focus:
            if s.startswith(("-", "*", "•")):
                bullets.append(s.lstrip("-*• ").strip())
            elif s and bullets:      # a new section/paragraph after the bullets ends it
                break
    return bullets


def _load_focus() -> dict:
    if FOCUS_JSON.exists():
        return json.loads(FOCUS_JSON.read_text())
    return {"rounds": {}}


def _save_focus(stem: str, report: str) -> None:
    """Persist this report's focus bullets so the next report (and the site) can hold
    the player — and the coach — to them."""
    bullets = extract_focus(report)
    if not bullets:
        return
    doc = _load_focus()
    doc["rounds"][stem] = {"date": stem[:10].replace("_", "-"), "bullets": bullets}
    FOCUS_JSON.parent.mkdir(parents=True, exist_ok=True)
    FOCUS_JSON.write_text(json.dumps(doc, indent=2))


def _prev_focus_block(stem: str) -> str:
    """The focus bullets from the most recent report BEFORE this round, verbatim —
    the prev-report excerpt is truncated and can lose them."""
    rounds = _load_focus().get("rounds", {})
    prior = sorted(k for k in rounds if k < stem)
    if not prior:
        return ""
    prev = rounds[prior[-1]]
    lines = [f"\n=== YOUR PREVIOUS NEXT-ROUND FOCUS (from the {prev['date']} report — "
             "grade adherence on each) ==="]
    lines += [f"  - {b}" for b in prev["bullets"]]
    return "\n".join(lines) + "\n"


def _escalation_block(stem: str) -> str:
    """Escalation chains from the player's own confirmed hole tags: this round's
    tagged blow-up causes + the season pattern across all annotated rounds."""
    from .db import connect
    con = connect()
    rid = _rid_from_stem(stem)
    this_rd = con.execute("""
        SELECT hole_number, double_class, preventable_escalation, note
        FROM annot.hole_context
        WHERE round_id = ? AND (double_class IS NOT NULL OR preventable_escalation)
        ORDER BY hole_number""", [rid]).fetchall()
    season = con.execute("""
        SELECT double_class, count(*), count(*) FILTER (WHERE preventable_escalation)
        FROM annot.hole_context WHERE double_class IS NOT NULL
        GROUP BY double_class ORDER BY count(*) DESC""").fetchall()
    n_ann = con.execute("SELECT count(DISTINCT round_id) FROM annot.hole_context").fetchone()[0]
    if not this_rd and not season:
        return ""
    lines = ["\n=== ESCALATION CHAINS (from your own confirmed hole tags) ==="]
    for hole, dc, prev_esc, note in this_rd:
        bits = [dc or "escalation"] + (["PREVENTABLE by his own admission"] if prev_esc else [])
        if note:
            bits.append(note)
        lines.append(f"  This round H{hole}: " + " — ".join(bits))
    if season:
        parts = [f"{dc} {n}" + (f" ({p} preventable)" if p else "")
                 for dc, n, p in season]
        lines.append(f"  Season, across {n_ann} annotated round{'s' if n_ann != 1 else ''} "
                     "— doubles by cause: " + ", ".join(parts) + ".")
    return "\n".join(lines) + "\n"


def _prev_report_block(stem: str) -> str:
    prior = sorted(f for f in OUT_DIR.glob("*.md")
                   if f.stem not in ("context", "latest") and f.stem < stem)
    if not prior:
        return ""
    f = prior[-1]
    return (f"\n=== YOUR PREVIOUS REPORT ({f.stem[:10].replace('_', '-')}) — for continuity ===\n"
            + f.read_text()[:1500])


def _double_anatomy(stem: str) -> str:
    rj = ROUNDS_DIR / f"{stem}.json"
    if not rj.exists():
        return ""
    doc = json.loads(rj.read_text())
    rows = []
    for h in doc["holes"]:
        if (h.get("scoreToPar") or 0) < 2:
            continue
        causes = []
        if h.get("penalties"):
            causes.append(f"{h['penalties']} penalty")
        if (h.get("putts") or 0) >= 3:
            causes.append(f"{h['putts']} putts")
        if not h.get("gir") and not causes:
            causes.append("missed green, no up-and-down")
        rows.append(f"  H{h['number']} (par {h['par']}): {h['strokes']} "
                    f"({h['scoreToPar']:+d}) — {', '.join(causes) or 'grind'}")
    if not rows:
        return "\n=== DOUBLES ANATOMY ===\nNo doubles-or-worse this round — say so, it matters.\n"
    return ("\n=== DOUBLES ANATOMY (authoritative; where the blow-ups were) ===\n"
            + "\n".join(rows) + "\n")


def _tier_block(progress: dict) -> str:
    """Deltas vs the MODELED target-handicap tier (existing app baseline convention)."""
    bl = (progress.get("baselines") or {})
    tgt = next(((k, v) for k, v in bl.items() if k.startswith("target")), None)
    sg10 = ((progress.get("sg") or {}).get("last10") or {}).get("byCategory")
    if not tgt or not sg10:
        return ""
    name, tv = tgt
    gaps = sorted(((cat, round(sg10[cat] - tv["byCategory"].get(cat, 0), 1))
                   for cat in sg10), key=lambda x: x[1])
    lines = [f"\n=== VS A MODELED {name.replace('target', '')}-HANDICAP (labeled model, "
             "not measured data) ==="]
    for cat, gap in gaps[:3]:
        if gap < -0.3:
            lines.append(f"  {SG_LABELS[cat]}: {gap:+.1f} strokes/18 behind that tier "
                         "(last 10 clean rounds)")
    ahead = [f"{SG_LABELS[c]} ({g:+.1f})" for c, g in gaps if g > 0.3]
    if ahead:
        lines.append("  Already at/above tier: " + ", ".join(ahead))
    return "\n".join(lines) + "\n" if len(lines) > 1 else ""


def _latest_stem() -> str | None:
    files = sorted(ROUNDS_DIR.glob("*.md"))  # YYYY_MM_DD_ names sort chronologically
    return files[-1].stem if files else None


def _round_md(stem: str) -> str | None:
    f = ROUNDS_DIR / f"{stem}.md"
    return f.read_text() if f.exists() else None


def _fmt(v) -> str:
    return f"{v:+.1f}" if isinstance(v, (int, float)) else "—"


def state_summary(progress: dict) -> str:
    """Compact current-form + trend context from progress.json."""
    sc, sg, au = progress["scoring"], progress["sg"], progress["authoritative"]
    last5, allt = sg.get("last5"), sg.get("allTime")
    lines = [
        f"Scoring level: +{sc['averageOverRating18']}/18 over rating "
        f"(potential +{sc['potentialOverRating18']} ~ handicap {sc['garminHandicap']}; "
        f"break-90 target +{sc['break90OverRating']}).",
        f"Penalties {au['last5']['penalties18']}/18 · doubles+ {au['last5']['doubles18']}/18 · "
        f"putts {au['last5']['putts18']:.0f}/18 · 3-putts {au['last5']['threePutts18']}/18 (last 5).",
        "",
        "Strokes Gained vs scratch, per 18 (Last 5 = current form, with trend vs all-time):",
    ]
    if last5 and allt:
        for k, lbl in SG_LABELS.items():
            cur, base = last5["byCategory"][k], allt["byCategory"][k]
            d = cur - base
            arrow = "improving" if d > 0.5 else "slipping" if d < -0.5 else "flat"
            lines.append(f"  - {lbl}: {_fmt(cur)} ({arrow} vs all-time {_fmt(base)})")
        lines.append(f"  - SG 0-100 (leverage): {_fmt(last5['sg0to100'])}  · "
                     f"total {_fmt(last5['total'])}")
    lines += _process_lines(progress)
    return "\n".join(lines)


def _process_lines(progress: dict) -> list[str]:
    """Process-layer metrics from post-round annotations, when any rounds are annotated.
    These explain HOW strokes were lost (tee-state, recovery discipline, real approach
    skill) — weight them, but respect the small samples the coverage counts show."""
    pm = (progress.get("priorityMetrics") or {}).get("allTime") or {}
    rows = [("cleanSecondShotPct", "Clean second-shot % (after par-4/5 tee balls)"),
            ("recoveryOneShotPct", "One-shot recovery success %"),
            ("normalApproachGirPct", "Normal-approach GIR % (stock swings only)")]
    out = []
    for key, lbl in rows:
        c = pm.get(key) or {}
        if c.get("value") is not None:
            out.append(f"  - {lbl}: {c['value']}% "
                       f"(n={c['nObs']} across {c['nRounds']} annotated round"
                       f"{'s' if c['nRounds'] != 1 else ''})")
    if out:
        out.insert(0, "")
        out.insert(1, "Process metrics (from the player's own post-round annotations — "
                      "small samples, treat as directional):")
    return out


def _fmt_buckets(buckets: list[dict]) -> str:
    out = []
    for b in buckets:
        if b["n"]:
            out.append(f"  - {b['label']}: {b['n']} first putts, avg {b['avg']:.2f} putts, "
                       f"make {b['makePct']}%")
        else:
            out.append(f"  - {b['label']}: none")
    return "\n".join(out)


def putting_summary(stem: str, progress: dict) -> str:
    """This round's putting bucketed by first-putt distance, plus all-time for context."""
    lines = ["Authoritative putt counts bucketed by first-putt distance. Distance is GPS to "
             "green CENTER (edge-of-green putts read short); the 0–3 ft band is unreliable.", ""]
    rjson = ROUNDS_DIR / f"{stem}.json"
    if rjson.exists():
        doc = json.loads(rjson.read_text())
        lines += ["This round:", _fmt_buckets(putt_buckets(doc["holes"])), ""]
    allt = (progress.get("putting") or {}).get("allTime")
    if allt:
        lines += ["All-time (context):", _fmt_buckets(allt), ""]
    lines.append("Read this by band: 3-putts from 30+ ft are ~expected; a real putting leak "
                 "shows as high avg putts or low make% inside ~20 ft.")
    return "\n".join(lines)


def build_context(stem: str, progress: dict | None = None) -> dict:
    """Assemble the coach prompt. `progress` overrides the on-disk file — used by the
    backfill to hand each old round the state of the game as of that round."""
    profile = PROFILE.read_text() if PROFILE.exists() else "(no profile on file)"
    progress = progress if progress is not None else json.loads(PROGRESS.read_text())
    state = state_summary(progress)
    putting = putting_summary(stem, progress)
    ts = progress.get("timeSeries") or []
    rdate = stem[:10].replace("_", "-")
    rentry = next((r for r in ts if r["date"] == rdate), ts[-1] if ts else None)
    if rentry:
        scg, o = progress["scoring"], rentry["overRating18"]
        verdict = ("a strong round (near your best)" if o <= scg["potentialOverRating18"] + 2
                   else "better than your average" if o < scg["averageOverRating18"] - 1
                   else "a tougher day than usual" if o > scg["averageOverRating18"] + 2
                   else "about your average")
        state += (f"\n\nTHIS ROUND vs your level: it was +{o}/18 over rating. Your average "
                  f"is +{scg['averageOverRating18']}, potential +{scg['potentialOverRating18']} "
                  f"(lower = better). So this was {verdict}. Use over-rating, NOT over-par.")
    rj = ROUNDS_DIR / f"{stem}.json"
    if rj.exists():
        rd = json.loads(rj.read_text())
        rec = rd.get("reconciliation") or {}
        if (rec.get("shotCountDelta") or 0) > POLLUTION_DELTA:
            state += (
                f"\n\n!! DATA QUALITY — THIS ROUND IS OVER-RECORDED: the sensor logged "
                f"{rec['recordedShots']} shots against a scorecard of {rd['score']['strokes']} "
                f"strokes (+{rec['shotCountDelta']}), worst on holes {rec.get('suspectHoles')}. "
                f"Those extra strokes DID NOT HAPPEN, so this round's per-shot SG buckets are "
                f"junk — do NOT name a worst bucket or build practice advice from them, and do "
                f"not describe holes as needing extra swings. Judge the round from the "
                f"authoritative stats (score, putts, penalties, fairways, GIR) and say plainly "
                f"that the shot-level detail was unreliable.")
        holes = rd["score"].get("holesCompleted") or 18
        tr = rd["strokesGained"].get("sg0to100", 0) * 18 / holes
        sgw = progress.get("sg") or {}
        avg = (sgw.get("allTime") or {}).get("sg0to100")
        l5 = (sgw.get("last5") or {}).get("sg0to100")
        if avg is not None:
            state += (f"\n\nSCORING ZONE (SG 0–100, 100yd & in, no putts — his #1 priority): "
                      f"this round {tr:+.1f}/18 vs your average {avg:+.1f}"
                      + (f" (last 5 {l5:+.1f})" if l5 is not None else "")
                      + ". Toward 0 = better. A big beat here is exactly the progress he's "
                      "chasing — lead with it.")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "context.md").write_text(state + "\n\n=== PUTTING BY DISTANCE ===\n" + putting)
    return {"profile": profile, "state": state, "putting": putting,
            "stem": stem, "round_md": _round_md(stem) or "",
            "annotations": _annotations_block(stem),
            "insights": _insights_block(),
            "course": _course_block(stem),
            "tier": _tier_block(progress),
            "benchmark": _benchmark_block(),
            "anatomy": _double_anatomy(stem),
            "escalation": _escalation_block(stem),
            "prev_report": _prev_report_block(stem),
            "prev_focus": _prev_focus_block(stem)}


def _annotations_block(stem: str) -> str:
    """The player's narrative + confirmed tags for the prompt, when they exist."""
    ann_dir = Path("data/annotations")
    narrative = ann_dir / f"{stem}.md"
    tags_file = ann_dir / f"{stem}.tags.json"
    if not narrative.exists() and not tags_file.exists():
        return ""
    parts = [ANNOTATIONS_HEADER]
    if narrative.exists():
        parts.append(narrative.read_text().strip())
    if tags_file.exists():
        tags = json.loads(tags_file.read_text())
        lines = []
        for t in tags.get("shots", []):
            ev = f" — {t['evaluation']}" if t.get("evaluation") else ""
            note = f" ({t['note']})" if t.get("note") else ""
            lines.append(f"  - H{t.get('hole')}: {t.get('intent')}{ev}{note}")
        for t in tags.get("holes", []):
            bits = [b for b in (
                f"after-tee {t['postTeeState']}" if t.get("postTeeState") else None,
                f"double: {t['doubleClass']}" if t.get("doubleClass") else None,
                "preventable escalation" if t.get("preventableEscalation") else None,
            ) if b]
            if bits:
                lines.append(f"  - H{t['hole']}: " + ", ".join(bits))
        if lines:
            parts.append("Confirmed shot/hole tags:\n" + "\n".join(lines))
    return "\n\n".join(parts) + "\n"


def _pick_provider() -> tuple[str, str] | None:
    """(provider, key) from .env. Anthropic if an sk-ant key is present; else OpenAI
    (incl. an OpenAI-style key mistakenly placed in ANTHROPIC_API_KEY). override=True so
    the .env value beats an empty shell var (Claude Code exports one)."""
    load_dotenv(override=True)
    ak = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    ok = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if ak.startswith("sk-ant"):
        return ("anthropic", ak)
    if ak.startswith("sk-") and not ok:        # an OpenAI key pasted into the Anthropic slot
        ok = ak
    return ("openai", ok) if ok else None


def _anthropic(key: str, model: str | None) -> "callable":  # noqa: F821
    import anthropic
    client = anthropic.Anthropic(api_key=key)
    mdl = model or os.environ.get("CLAUDE_MODEL", DEFAULT_ANTHROPIC_MODEL)

    def call(system, prompt):
        msg = client.messages.create(model=mdl, max_tokens=1600, system=system,
                                     messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    return call


def _openai(key: str, model: str | None) -> "callable":  # noqa: F821
    import openai
    client = openai.OpenAI(api_key=key)
    mdl = model or os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)

    def call(system, prompt):
        r = client.chat.completions.create(model=mdl, max_tokens=1600, messages=[
            {"role": "system", "content": system}, {"role": "user", "content": prompt}])
        return (r.choices[0].message.content or "").strip()
    return call


def coach_round(stem: str | None = None, model: str | None = None,
                as_of: bool = False) -> Path | None:
    prov = _pick_provider()
    if not prov:
        print("  coach skipped — set ANTHROPIC_API_KEY=sk-ant-… or OPENAI_API_KEY=sk-… in .env")
        return None
    provider, key = prov
    stem = stem or _latest_stem()
    if not stem:
        print("  coach skipped — no round to review")
        return None
    # as_of: judge the round against the game as it stood THEN. Without this a
    # regenerated May report quotes August averages and reads as if the coach could
    # see the future.
    view = None
    if as_of:
        from . import progress as _progress
        view = _progress.build(through_scorecard_id=int(stem.split("_")[-1]), write=False)
    ctx = build_context(stem, view)
    try:
        call = (_anthropic if provider == "anthropic" else _openai)(key, model)
        report = call(SYSTEM, PROMPT.format(**ctx))
    except ImportError:
        print(f"  coach skipped — `pip install {provider}`")
        return None
    except Exception as e:  # noqa: BLE001 — coaching must never break the pipeline
        print(f"  coach skipped — {provider} error: {type(e).__name__}: {str(e)[:140]}")
        return None
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{ctx['stem']}.md"
    out.write_text(report)
    (OUT_DIR / "latest.md").write_text(report)
    _save_focus(ctx["stem"], report)
    print(f"  coach report ({provider}) -> {out}")
    return out


def coach_recent(n: int = 5, model: str | None = None) -> list[Path]:
    """Generate reports for the n most recent rounds (oldest→newest, so latest.md is the newest)."""
    stems = [f.stem for f in sorted(ROUNDS_DIR.glob("*.md"))][-n:]
    done = []
    for stem in stems:
        r = coach_round(stem, model)
        if r:
            done.append(r)
    return done


def backfill(stems: list[str] | None = None, model: str | None = None) -> list[Path]:
    """Regenerate reports oldest->newest, each with as-of-that-round context.

    Needed after any change to the SG model: an old report keeps whatever the numbers
    said when it was written, so its practice advice can point at a bucket the corrected
    data no longer blames.
    """
    every = [f.stem for f in sorted(ROUNDS_DIR.glob("*.json"))]
    todo = sorted(stems) if stems else every
    done = []
    for i, stem in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {stem}", flush=True)
        r = coach_round(stem, model, as_of=True)
        if r:
            done.append(r)
    # latest.md is the dashboard's "current" report — restore it to the newest round,
    # whatever subset we just regenerated.
    newest = OUT_DIR / f"{every[-1]}.md"
    if every and newest.exists():
        (OUT_DIR / "latest.md").write_text(newest.read_text())
    print(f"backfilled {len(done)}/{len(todo)} reports")
    return done


def missing_stems() -> list[str]:
    """Rounds with no coach report yet."""
    return [f.stem for f in sorted(ROUNDS_DIR.glob("*.json"))
            if not (OUT_DIR / f"{f.stem}.md").exists()]


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m src.coach")
    ap.add_argument("--backfill", action="store_true",
                    help="regenerate ALL round reports with as-of-that-round context")
    ap.add_argument("--missing", action="store_true",
                    help="generate reports only for rounds that have none")
    ap.add_argument("--stems", nargs="*", help="specific round stems to (re)generate")
    ap.add_argument("--model", help="override the coach model")
    a = ap.parse_args()
    if a.backfill or a.missing or a.stems:
        backfill(a.stems or (missing_stems() if a.missing else None), a.model)
    else:
        coach_round(model=a.model)


if __name__ == "__main__":
    main()
