# Overview — goals, scope, the player

## Why this exists
Garmin's CT10 club sensors + watch + Golf app capture a rich dataset, but Garmin
Connect's native analysis and export are weak — no clean scores/shot export, and the
web portal hides the per-hole shot maps the mobile app shows. This project pulls the
data out and does the analysis Garmin won't.

## Goals (in priority order)
1. **Own the raw data** — every Garmin response saved verbatim before parsing.
2. **Honest analysis** — flag data-quality issues (GPS noise, sensor over/under-record,
   modeled vs measured) instead of presenting everything as gospel.
3. **Answer "why"** — Strokes Gained, leak ranking, per-round shot detail, trends —
   so practice attacks the highest-return problem.
4. **Frictionless** — one command to update + deploy; a mobile dashboard to glance at.
5. **An AI coach** — turn the numbers into a brief, personalized round review.

## The player it's built for
A serious improving golfer (started July 2025), goal path: consistent mid-90s →
**break 90 (2026)** → durable low-80s. Philosophy: *eliminate penalties and doubles,
play dispersion, no hero shots, build the golfer not the round.* Bag: Callaway Rogue
ST Max OS irons, Driver / 5W / Ping G430 4H, Vokey SM10 wedges (50/54/58), TP5x.
Primary practice course: Harvey Penick Golf Campus. Plays easier-rated tees, so
"break 90" ≈ **+22 over course rating** (not +18).

The full living profile lives in `config/golfer_profile.md` (used by the AI coach).

## Scope
**In scope:** pulling scorecards/holes/shots, a durable local store, Strokes Gained &
club analysis, shot-map visualization on satellite imagery, an AI coach, a deployed
mobile dashboard.

**Out of scope:** direct watch/sensor interface; Garmin's licensed vector course maps
(use satellite tiles instead); writing anything back to Garmin (read-only).

## Status
Well past the original Phase-0 POC. Live, deployed, mobile dashboard with Strokes
Gained (custom distance buckets + selectable baselines), club gapping, per-round shot
detail, and satellite shot maps — auto-updated and deployed via one command. Trend
view and AI coach are the current build.
