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

PROFILE = Path("config/golfer_profile.md")
PROGRESS = Path("data/processed/progress.json")
ROUNDS_DIR = Path("data/processed/rounds")
OUT_DIR = Path("data/processed/coach")
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"
DEFAULT_OPENAI_MODEL = "gpt-4o"

SG_LABELS = {"offTee": "Off-the-Tee", "longApproach": "Long approach (150+)",
             "midApproach": "Mid approach (50-150)", "inside50": "Inside 50",
             "putting": "Putting"}

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
    "- LEVELING: judge how the round compares to the player using SCORE OVER COURSE "
    "RATING per 18 (provided), NOT over par. Par != rating, and he plays easier-rated "
    "tees. A round whose over-rating/18 is BELOW his average is a GOOD round; near his "
    "'potential' is very good. Use the numbers provided — do not invent extrapolations.\n"
    "- SG reliability: off-the-tee and full-approach SG are reliable; putting and "
    "inside-50 (short-game) SG are GPS-approximate (directional, not exact); the absolute "
    "SG total runs a few strokes hot — trust the RANKING of buckets over absolute numbers. "
    "Negative SG vs scratch is normal."
)

PROMPT = """Write a BRIEF round report for the player. Use these sections, short and tight:

**Overall** — 2-3 sentences: how the round went vs their level/trend.
**What cost strokes** — the 1-2 biggest leaks this round (worst SG bucket(s) + penalties/doubles), with the "why".
**Trend read** — improving / flat / slipping vs their recent form, in the categories that matter.
**Practice focus** — 1-2 concrete things, tied to their stated priorities (short-game/54° calibration, driver dispersion, etc.).

Keep it under ~250 words. No fluff. Speak to them directly.

=== PLAYER PROFILE ===
{profile}

=== CURRENT FORM & TREND (auto-generated) ===
{state}

=== THE ROUND JUST PLAYED ===
{round_md}
"""


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
    return "\n".join(lines)


def build_context(stem: str) -> dict:
    profile = PROFILE.read_text() if PROFILE.exists() else "(no profile on file)"
    progress = json.loads(PROGRESS.read_text())
    state = state_summary(progress)
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
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "context.md").write_text(state)
    return {"profile": profile, "state": state, "stem": stem, "round_md": _round_md(stem) or ""}


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
        msg = client.messages.create(model=mdl, max_tokens=1100, system=system,
                                     messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    return call


def _openai(key: str, model: str | None) -> "callable":  # noqa: F821
    import openai
    client = openai.OpenAI(api_key=key)
    mdl = model or os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)

    def call(system, prompt):
        r = client.chat.completions.create(model=mdl, max_tokens=1100, messages=[
            {"role": "system", "content": system}, {"role": "user", "content": prompt}])
        return (r.choices[0].message.content or "").strip()
    return call


def coach_round(stem: str | None = None, model: str | None = None) -> Path | None:
    prov = _pick_provider()
    if not prov:
        print("  coach skipped — set ANTHROPIC_API_KEY=sk-ant-… or OPENAI_API_KEY=sk-… in .env")
        return None
    provider, key = prov
    stem = stem or _latest_stem()
    if not stem:
        print("  coach skipped — no round to review")
        return None
    ctx = build_context(stem)
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


def main() -> None:
    coach_round()


if __name__ == "__main__":
    main()
