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
