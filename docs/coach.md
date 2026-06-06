# AI Coach + the living golfer spec

## Intent
At the end of an `update`, generate a **brief, personalized round report**: how the
round went overall, areas to improve, what it suggests about the trend, and practice
focus. The coach must be grounded in *this* golfer — goals, swing philosophy,
development priorities — not generic golf advice.

## The living golfer spec (the context that makes it personal)
Two parts:
1. **`config/golfer_profile.md`** — durable, user-owned profile: goals, equipment, swing
   philosophy/cues, development priorities, short-game identity, mental model. Seeded
   from the player's own coaching profile; edited by the player over time.
2. **Auto-generated state** — assembled at coach-time from `progress.json`: current form
   (scoring level, SG by bucket across windows), trends (recent vs all-time), the #1 leak,
   penalties/doubles, putts. Written to `data/processed/coach/context.md` for transparency.

The coach prompt = profile + auto state + the specific round (the round's markdown card).
This keeps the coach current as the game evolves, without the player re-explaining context.

## How it runs
- `src/coach.py` calls the **Anthropic API** (`anthropic` SDK). Key from `.env`
  (`ANTHROPIC_API_KEY`). If no key, it skips gracefully (pipeline never breaks).
- Triggered by `python -m src.update ... --coach` (and runs automatically in `--push`
  flows when a key is present). Generates a report for the most recent round.
- Output: `data/processed/coach/<round_stem>.md` (per-round, versioned) + a `latest.md`.

## Surfaced in the dashboard
A **Coach tab**: the latest report rendered, with older reports accessible. Pairs
naturally with the Trend view (the report references the trend; the charts show it).

## Design guardrails
- **Brief** — a few short sections, not an essay. Practice-focused, decision-quality lens
  (matches the player's "build the golfer, not the round" philosophy).
- **Honest** — the coach is told which numbers are authoritative vs GPS-approximate, and
  to weight accordingly (e.g., trust putt counts + score, treat short-game SG as directional).
- **Trend-aware** — explicitly reads recent-vs-baseline so it says "improving/flat/declining,"
  not just "today you…".
- **Cheap & local** — runs on the player's machine during `update`; one API call per round.
