# garmin-golf · documentation

This `docs/` folder is the durable memory of the project — its intent, design, and
decisions — so the context survives even if the chat/session that built it is lost.

## What this project is
A personal system that **liberates Garmin golf data, analyzes it (Strokes Gained,
club gapping, shot maps), and serves it as a deployed mobile dashboard** — with an
AI coach layered on top. Built from reverse-engineered Garmin Connect endpoints
because Garmin's own analysis/export is weak.

The guiding ethos: **own the raw data, be honest about data quality, and make the
analysis answer "why did a score happen," not just "what was the score."**

## Read these in order
1. [overview.md](overview.md) — goals, scope, the player it's built for
2. [architecture.md](architecture.md) — the pipeline, modules, data flow, deploy
3. [data-model.md](data-model.md) — raw responses → the round document schema
4. [strokes-gained.md](strokes-gained.md) — the SG methodology and what to trust
5. [dashboard.md](dashboard.md) — the generated site (tabs, windows, baselines, maps)
6. [coach.md](coach.md) — the AI coach + the living golfer spec
7. [decisions.md](decisions.md) — key design decisions and their rationale
8. [roadmap.md](roadmap.md) — planned features + research notes (incl. DIY hardware)

## One-paragraph mental model
`pull` fetches raw JSON from Garmin (saved verbatim — the asset). `parse` turns one
round's raw into a self-contained **round document** (score + shots + Strokes Gained,
every Garmin field preserved + a derived layer). `analyze` and `progress` aggregate
across rounds. `site` renders a responsive PWA. `update` runs the whole chain and can
deploy it. `coach` writes an AI round report. Everything is flat files + JSON; the
dashboard is one self-contained HTML file hosted at `colbyward.io/golf/`.
