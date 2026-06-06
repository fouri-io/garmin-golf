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
    "the score. Data-quality rules you MUST respect: score, putt counts, penalties, and "
    "score-vs-rating are authoritative; off-the-tee and full-approach SG are reliable; "
    "putting and inside-50 (short-game) SG are GPS-approximate, so read them as "
    "directional, not exact; the absolute SG total runs a few strokes hot, so trust the "
    "RANKING of buckets over the absolute numbers. Negative SG vs scratch is normal."
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


def _latest_round() -> tuple[str, str] | None:
    files = sorted(ROUNDS_DIR.glob("*.md"))  # YYYY_MM_DD_ names sort chronologically
    return (files[-1].stem, files[-1].read_text()) if files else None


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


def build_context() -> dict:
    profile = PROFILE.read_text() if PROFILE.exists() else "(no profile on file)"
    progress = json.loads(PROGRESS.read_text())
    state = state_summary(progress)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "context.md").write_text(state)
    rnd = _latest_round()
    return {"profile": profile, "state": state,
            "stem": rnd[0] if rnd else None, "round_md": rnd[1] if rnd else ""}


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


def coach_round(model: str | None = None) -> Path | None:
    prov = _pick_provider()
    if not prov:
        print("  coach skipped — set ANTHROPIC_API_KEY=sk-ant-… or OPENAI_API_KEY=sk-… in .env")
        return None
    provider, key = prov
    ctx = build_context()
    if not ctx["stem"]:
        print("  coach skipped — no round to review")
        return None
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


def main() -> None:
    coach_round()


if __name__ == "__main__":
    main()
