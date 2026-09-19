# Dashboard — the generated site

`src/site.py` renders **one self-contained `site/index.html`** (all data inlined as a
JS object — no fetch, works from `file://`, drops into S3 unchanged). Mobile-first and
responsive. Leaflet is loaded from CDN for the maps (the only online-only part).

## Tabs (bottom nav)
- **Overview** *(was "Progress")* — current snapshot. Window selector (This round /
  Last 5 / All-time) drives the whole view. Scoring hero (over rating), the **SG 0–100
  leverage card** (3 horizons side by side), review tiles (putts/penalties/doubles/
  3-putts), #1-leak callout, and **SG vertical bars** colored vs the selected baseline.
- **Trend** — progress over time: line charts of SG total + per-category and
  score-vs-rating across rounds, with a direction read. (This is the real "are we
  improving" view; the Overview is a snapshot, not a trend.)
- **Rounds** — tappable list → per-round detail (score chips, per-round SG, hole-by-hole
  with every shot + a 🗺️ button per hole that jumps to that hole's map).
- **Clubs** — gapping chart (per physical club, median + p25–p75 + max).
- **Maps** — round dropdown → hole stepper (◀ ▶) → Leaflet + Esri satellite; shots
  colored by per-shot SG with always-visible club labels (Dr/7i/54°) and tap popups.
- **Coach** — the AI round report + (optionally) trend, see coach.md.

## Approach Ladder card (Insights tab)
- One card between the performance cone and "What changed": a horizontal heat strip of
  Green Zone % by yardage bin (60→170), cell width proportional to the bin's yardage
  span, an n= badge on every cell, and the payoff legend on one line under the strip.
  Tap a bin → anatomy: the 10-yard detail sub-strip, median leave, miss pattern, from-lie
  mix and per-club rows (n≥5), plus the "too few swings to rate" line for the rest.
- Deliberately DOM/flex, never SVG: the cone scales off `svg.parentNode.clientWidth`,
  which collapses below ~500px in headless Chrome. A flex strip measures nothing, so it
  renders identically at any width (narrow viewports scroll horizontally).
- Bins under the coverage floor render grey and say "too few to rate" — never a colour.
- **Green Zone % band** on the Overview tab, at the top of the Priority metrics card:
  label · scope · value · n · trend vs the previous window. It sits outside the
  five-column priority-metrics grid on purpose — that grid is ROUND windows, while every
  ladder stat is scoped to one DAYS window (see ADR #19).

## Controls
- **Window:** thisRound / last5 / allTime — authoritative metrics use all rounds in the
  window; SG uses only clean (non-over-recorded) rounds within it.
- **Baseline:** Scratch / My average / Target H — affects SG only (data-driven; built in
  `progress.py` → `baselines`).

## Sign legend (baked in)
"Over rating" = +is worse (lower better). "Strokes Gained" = −is lost (toward 0 better).
Mirror images; the page states this so the +/− never confuse.

## Generation & hosting
- `python -m src.site` → `site/index.html`.
- Published to `~/dev/colbyward.io/golf/index.html` (configurable), auto-deploys to S3 +
  CloudFront via that repo's Action. Clean URL via a CloudFront viewer-request Function.
- Live (unlisted, `noindex`): `https://colbyward.io/golf/`.
- Color: green = gained/better, red = lost/worse, amber ≈ even, grey = putt/neutral.
