"""Post-round annotation workflow — narrative in, confirmed structured tags out.

The narrative is first-class raw data: it explains WHY the score happened (recovery
punches, layups, compounded mistakes) without ever rewriting the deterministic shot
facts. Flow:

    python -m src.annotate                 # scaffold data/annotations/<stem>.md (latest round)
    python -m src.annotate <id>            # ...for a specific round
    python -m src.annotate <id> --structure  # LLM: narrative -> proposed tags (.tags.proposed.json)
    python -m src.annotate <id> --confirm    # validate + promote to <stem>.tags.json (committed)

The confirmed .tags.json (and the .md) are the durable assets; `ingest` loads them
into annot.* on every run. Re-running --structure after a taxonomy change regenerates
proposals from the untouched narrative — facts permanent, interpretations recomputable.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ANN_DIR = Path("data/annotations")
TAG_SCHEMA_VERSION = 1

INTENTS = {"normal", "recovery", "punch", "layup", "safety", "forced_carry", "other"}
EVALUATIONS = {"recovery_success", "recovery_fail", "good_decision_bad_execution",
               "bad_decision_good_outcome", "executed_well", "executed_poorly"}
POST_TEE_STATES = {"clean", "compromised", "recovery"}
DOUBLE_CLASSES = {"normal_execution", "compounded", "penalty_driven",
                  "short_game_driven", "putting_driven", "other"}


def _connect():
    from .db import connect
    return connect()


def _resolve_stem(con, arg: str | None) -> tuple[str, int]:
    """(stem, round_id) for an id or the latest round."""
    if arg and arg.isdigit():
        row = con.execute("SELECT round_date, round_id FROM canon.round WHERE round_id = ?",
                          [int(arg)]).fetchone()
    else:
        row = con.execute(
            "SELECT round_date, round_id FROM canon.round ORDER BY start_time DESC LIMIT 1"
        ).fetchone()
    if not row:
        raise SystemExit("no such round in the database — run `python -m src.ingest` first")
    date, rid = row
    return f"{str(date).replace('-', '_')}_{rid}", rid


def _round_context(con, rid: int) -> tuple[list[dict], list[dict]]:
    """(holes, shots) for prompts/scaffolds — shot_id included so tags can bind."""
    holes = [dict(zip(["hole", "par", "strokes", "putts", "penalties"], r))
             for r in con.execute("""
                 SELECT hole_number, par, strokes, putts, penalties
                 FROM canon.hole WHERE round_id = ? ORDER BY hole_number""", [rid]).fetchall()]
    shots = [dict(zip(["shotId", "hole", "order", "club", "type", "yards",
                       "fromLie", "toLie", "toPinBeforeYds"], r))
             for r in con.execute("""
                 SELECT s.shot_id, s.hole_number, s.shot_order,
                        coalesce(c.name, ct.name, 'unknown'), s.shot_type,
                        g.yards, s.start_lie, s.end_lie, g.to_pin_before_yds
                 FROM canon.shot s
                 LEFT JOIN canon.club c ON c.club_id = s.club_id
                 LEFT JOIN canon.club_type ct ON ct.club_type_id = s.club_type_id
                 LEFT JOIN derived.shot_geom g ON g.shot_id = s.shot_id
                 JOIN derived.shot_flags f ON f.shot_id = s.shot_id
                 WHERE s.round_id = ? AND NOT f.phantom
                 ORDER BY s.hole_number, s.shot_order""", [rid]).fetchall()]
    return holes, shots


def _shot_table(holes: list[dict], shots: list[dict]) -> str:
    lines = []
    for h in holes:
        lines.append(f"Hole {h['hole']} (par {h['par']}): {h['strokes']} strokes, "
                     f"{h['putts']} putts, {h['penalties']} penalties")
        for s in (x for x in shots if x["hole"] == h["hole"]):
            yd = f"{s['yards']:.0f}y" if s["yards"] is not None else "?"
            pin = (f", {s['toPinBeforeYds']:.0f}y to pin"
                   if s["toPinBeforeYds"] is not None else "")
            lines.append(f"  shotId={s['shotId']}  #{s['order']} {s['club']} {yd} "
                         f"{s['fromLie']}→{s['toLie']}{pin}")
    return "\n".join(lines)


def scaffold(con, stem: str, rid: int) -> Path:
    """Create the narrative file (if absent) with per-hole headers to jog memory."""
    ANN_DIR.mkdir(parents=True, exist_ok=True)
    path = ANN_DIR / f"{stem}.md"
    if path.exists():
        return path
    holes, shots = _round_context(con, rid)
    lines = [f"# Post-round notes — {stem}", "",
             "<!-- Write freely: what you were trying to do, recoveries, layups, lies,",
             "     decisions, fatigue. Mention holes/clubs so tags can bind to shots. -->", ""]
    for h in holes:
        to_par = h["strokes"] - h["par"] if h["strokes"] is not None else None
        tag = f" ({to_par:+d})" if to_par is not None else ""
        lines.append(f"## H{h['hole']} · par {h['par']} · {h['strokes']}{tag} · "
                     f"{h['putts']} putts" + (f" · {h['penalties']} pen" if h["penalties"] else ""))
        lines.append("")
    path.write_text("\n".join(lines))
    return path


STRUCTURE_SYSTEM = (
    "You convert a golfer's post-round narrative into structured shot-context tags. "
    "You are conservative: tag ONLY what the narrative supports; when you cannot "
    "confidently attach a note to a specific shotId, put it in `unmatched` with its "
    "hole number. Output STRICT JSON only — no markdown fences, no commentary."
)

STRUCTURE_PROMPT = """Round {rid}. Below are (1) the recorded shots with their stable shotIds,
(2) the player's narrative. Produce tags as JSON with this exact shape:

{{
  "tagSchemaVersion": {ver},
  "roundId": {rid},
  "shots": [
    {{"shotId": <int from the table>, "hole": <int>, "intent": <one of {intents}>,
      "evaluation": <one of {evals} or null>,
      "excludeFromStock": <bool — true for any non-normal swing (punch/layup/recovery),
        so it stays out of stock club-distance stats>,
      "note": "<short quote/paraphrase from the narrative>"}}
  ],
  "holes": [
    {{"hole": <int>, "postTeeState": <one of {tee} or null>,
      "doubleClass": <one of {dbl} or null>,
      "preventableEscalation": <bool or null>, "note": "<optional>"}}
  ],
  "unmatched": [
    {{"hole": <int>, "text": "<the narrative fragment>", "intent": <one of {intents}>}}
  ]
}}

Rules:
- Tag only shots the narrative actually describes; untagged shots on an annotated
  round are treated as normal automatically. Do NOT tag every shot.
- postTeeState (clean/compromised/recovery = the player's state AFTER the tee shot)
  for every par-4/par-5 hole you can judge from the narrative; null if unclear.
- doubleClass for every hole listed as double-or-worse below, if judgeable.
- Recovery/punch shots: set evaluation recovery_success only if the NEXT shot was
  normal golf again; recovery_fail if they stayed in trouble.

Double-or-worse holes: {doubles}

=== RECORDED SHOTS ===
{shot_table}

=== PLAYER NARRATIVE ===
{narrative}
"""


def _llm_call(system: str, prompt: str) -> str | None:
    from .coach import DEFAULT_ANTHROPIC_MODEL, DEFAULT_OPENAI_MODEL, _pick_provider
    prov = _pick_provider()
    if not prov:
        print("  no API key — write the tags file by hand or set ANTHROPIC_API_KEY in .env")
        return None
    provider, key = prov
    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        mdl = os.environ.get("CLAUDE_MODEL", DEFAULT_ANTHROPIC_MODEL)
        msg = client.messages.create(model=mdl, max_tokens=4000, system=system,
                                     messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    import openai
    client = openai.OpenAI(api_key=key)
    mdl = os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
    r = client.chat.completions.create(model=mdl, max_tokens=4000, messages=[
        {"role": "system", "content": system}, {"role": "user", "content": prompt}])
    return (r.choices[0].message.content or "").strip()


def structure(con, stem: str, rid: int) -> Path | None:
    """Narrative -> LLM -> .tags.proposed.json."""
    narrative_path = ANN_DIR / f"{stem}.md"
    if not narrative_path.exists():
        raise SystemExit(f"no narrative at {narrative_path} — run scaffold first and write it")
    holes, shots = _round_context(con, rid)
    doubles = [h["hole"] for h in holes
               if h["strokes"] is not None and h["par"] and h["strokes"] - h["par"] >= 2]
    prompt = STRUCTURE_PROMPT.format(
        rid=rid, ver=TAG_SCHEMA_VERSION,
        intents=sorted(INTENTS), evals=sorted(EVALUATIONS),
        tee=sorted(POST_TEE_STATES), dbl=sorted(DOUBLE_CLASSES),
        doubles=doubles or "none",
        shot_table=_shot_table(holes, shots),
        narrative=narrative_path.read_text(),
    )
    raw = _llm_call(STRUCTURE_SYSTEM, prompt)
    if raw is None:
        return None
    if raw.startswith("```"):
        raw = raw.strip("`").removeprefix("json").strip()
    try:
        tags = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SystemExit(f"LLM did not return valid JSON ({e}); raw output:\n{raw[:2000]}")
    out = ANN_DIR / f"{stem}.tags.proposed.json"
    out.write_text(json.dumps(tags, indent=2))
    problems = validate_tags(con, rid, tags)
    print(f"  proposed tags -> {out}")
    for p in problems:
        print(f"    ! {p}")
    print("  review/edit, then: python -m src.annotate", rid, "--confirm")
    return out


def validate_tags(con, rid: int, tags: dict) -> list[str]:
    """Structural problems (blockers) + coverage warnings for a tags document."""
    problems = []
    if tags.get("roundId") != rid:
        problems.append(f"roundId {tags.get('roundId')} != {rid}")
    shot_holes = dict(con.execute(
        "SELECT shot_id, hole_number FROM canon.shot WHERE round_id = ?", [rid]).fetchall())
    for t in tags.get("shots", []):
        sid = t.get("shotId")
        if sid not in shot_holes:
            problems.append(f"shotId {sid} not in round {rid}")
        elif t.get("hole") not in (None, shot_holes[sid]):
            problems.append(f"shotId {sid} is on hole {shot_holes[sid]}, tag says {t.get('hole')}")
        if t.get("intent") not in INTENTS:
            problems.append(f"shotId {sid}: bad intent {t.get('intent')!r}")
        if t.get("evaluation") not in EVALUATIONS | {None}:
            problems.append(f"shotId {sid}: bad evaluation {t.get('evaluation')!r}")
    hole_nums = {h for (h,) in con.execute(
        "SELECT hole_number FROM canon.hole WHERE round_id = ?", [rid]).fetchall()}
    for t in tags.get("holes", []):
        if t.get("hole") not in hole_nums:
            problems.append(f"hole {t.get('hole')} not in round")
        if t.get("postTeeState") not in POST_TEE_STATES | {None}:
            problems.append(f"hole {t.get('hole')}: bad postTeeState {t.get('postTeeState')!r}")
        if t.get("doubleClass") not in DOUBLE_CLASSES | {None}:
            problems.append(f"hole {t.get('hole')}: bad doubleClass {t.get('doubleClass')!r}")
    for t in tags.get("unmatched", []):
        if t.get("intent") not in INTENTS | {None}:
            problems.append(f"unmatched on hole {t.get('hole')}: bad intent {t.get('intent')!r}")
    doubles = {h for (h,) in con.execute("""
        SELECT hole_number FROM canon.hole
        WHERE round_id = ? AND strokes - par >= 2""", [rid]).fetchall()}
    classified = {t["hole"] for t in tags.get("holes", []) if t.get("doubleClass")}
    missing = doubles - classified
    if missing:
        problems.append(f"warning: double+ holes without doubleClass: {sorted(missing)}")
    return problems


def confirm(con, stem: str, rid: int) -> Path:
    """Validate the proposed (or hand-edited) tags and promote to .tags.json."""
    proposed = ANN_DIR / f"{stem}.tags.proposed.json"
    final = ANN_DIR / f"{stem}.tags.json"
    src = proposed if proposed.exists() else final
    if not src.exists():
        raise SystemExit(f"nothing to confirm — no {proposed.name} (run --structure) "
                         f"and no {final.name}")
    editor = os.environ.get("EDITOR")
    if editor and sys.stdin.isatty() and src == proposed:
        subprocess.call([editor, str(src)])
    tags = json.loads(src.read_text())
    problems = validate_tags(con, rid, tags)
    blockers = [p for p in problems if not p.startswith("warning:")]
    for p in problems:
        print(f"    ! {p}")
    if blockers:
        raise SystemExit(f"fix {len(blockers)} blocker(s) in {src}, then re-run --confirm")
    # default excludeFromStock: any non-normal swing stays out of stock club stats
    for t in tags.get("shots", []):
        t.setdefault("excludeFromStock", t.get("intent") != "normal")
    tags["tagSchemaVersion"] = tags.get("tagSchemaVersion", TAG_SCHEMA_VERSION)
    tags["confirmedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
    final.write_text(json.dumps(tags, indent=2))
    if proposed.exists():
        proposed.unlink()
    print(f"  confirmed -> {final} (loaded into the DB on next ingest/update)")
    return final


def main() -> None:
    args = [a for a in sys.argv[1:]]
    flags = {a for a in args if a.startswith("--")}
    ident = next((a for a in args if not a.startswith("--")), None)
    con = _connect()
    stem, rid = _resolve_stem(con, ident)
    if "--structure" in flags:
        structure(con, stem, rid)
    elif "--confirm" in flags:
        confirm(con, stem, rid)
        from .ingest import load_annotations
        load_annotations(con)
        print("  annotations reloaded into the DB")
    else:
        path = scaffold(con, stem, rid)
        print(f"  narrative -> {path}")
        editor = os.environ.get("EDITOR")
        if editor and sys.stdin.isatty():
            subprocess.call([editor, str(path)])
        print(f"  next: python -m src.annotate {rid} --structure")


if __name__ == "__main__":
    main()
