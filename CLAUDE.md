Project Overview

Project: The Turn (garmin-golf)
Purpose: Turn my Garmin golf data into a longitudinal analytics system + AI coach that explains how and why scores happen — and what will lower the next plateau.
Owner: Colby Ward
Status: Active development (single user: me; may go multi-tenant later)

This file is the thin routing layer. The durable design memory is `docs/`
(read `docs/architecture.md` first; `docs/decisions.md` holds 18 ADRs — check it
BEFORE proposing architecture changes).

----------
Architecture & Structure

    garmin-golf/
    ├── CLAUDE.md              ← You are here
    ├── docs/                  ← Design memory: architecture, data model, ADRs, roadmap
    ├── src/                   ← Python 3.11 pipeline (flat package)
    ├── sql/schema/            ← DuckDB DDL, run in filename order by src/db.py
    ├── tools/parity.py        ← Self-consistency gate (docs vs DB)
    ├── tests/                 ← pytest (fixtures in tests/fixtures/raw/)
    ├── config/                ← Tunables + golfer_profile.md (living spec, hand-edited)
    ├── data/raw/              ← Verbatim Garmin JSON — IMMUTABLE, committed
    ├── data/annotations/      ← My post-round notes (.md) + confirmed tags (.tags.json)
    ├── data/turn.duckdb       ← canon/annot/derived layers — gitignored, rebuildable
    ├── data/processed/        ← Exports (round docs, progress, club_stats, coach)
    └── site/index.html        ← Generated single-file PWA dashboard

Layers: raw files (facts, committed) → canon.*/annot.* (canonical projection) →
derived.* (recomputable analytics) → exports/site. Every write originates in a
committed file; the DB never holds unique state.

----------
Key Commands

    # Everyday sync + deploy (costs an LLM call + publishes — ask first)
    python -m src.update --push

    # Rebuild everything offline (no network, no LLM)
    python -m src.update --no-pull

    # After schema/loader changes: drop DB, re-ingest, re-derive, re-export
    python -m src.update --rebuild

    # Annotation flow (post-round)
    python -m src.annotate [id]              # scaffold narrative
    python -m src.annotate <id> --structure  # LLM proposes tags (costs an LLM call)
    python -m src.annotate <id> --confirm    # validate + promote

    # Test / lint / parity
    pytest                    # unit + fixture tests
    pytest -m slow            # full parity gate vs real data
    ruff check src tests tools

----------
Tech Stack & Conventions
| Layer     | Technology | Notes |
| --------- | ---------- | ----- |
| Language  | Python 3.11 | flat src/ package, no framework |
| Database  | DuckDB     | data/turn.duckdb; plain ordered SQL files, no dbt/migrations |
| API       | garminconnect (unofficial) | isolated in src/garmin_client.py only |
| LLM       | Anthropic (fallback OpenAI) | coach + annotation structuring; keys in .env |
| Site      | hand-rolled single-file HTML/JS | data inlined; no build step |
| CI/CD     | none here  | deploy = push to colbyward.io repo → GitHub Action → S3 |

Code conventions:
- ruff, line-length 100. Match existing comment density and voice.
- Shared constants live in src/constants.py — never re-duplicate SG labels etc.
- Schema changes: edit sql/schema/*.sql (+ bump LOADER_VERSION in ingest.py if the
  loader's meaning changes), then `python -m src.update --rebuild`. No ALTER migrations.
- Tests use the hand-built 2-hole fixture round (tests/fixtures/raw/, id 999000111).

----------
Working Rules

🟢 Always Do (autopilot)
- Run `pytest` and `ruff check` before presenting changes
- Run `python -m tools.parity` after touching ingest/derive/export
- Keep new analytics in the derived layer (SQL views or derive.py) — never bake
  interpretations into canon or the raw files

🟡 Ask First (consequences)
- `python -m src.update --push` (publishes to colbyward.io) and anything else that
  deploys or costs money (coach runs, annotation --structure = LLM calls)
- Changing config/sg_baseline.json or the SG bucket definitions (rewrites history's
  interpretation — fine, but flag it)
- git push of any kind

🔴 Never Do (hard lines)
- Never edit data/raw/ — it is the immutable asset
- Never edit data/annotations/*.md narratives — they are my words
- Never hand-edit data/processed/, site/index.html, or data/turn.duckdb — all
  regenerable outputs; fix the source or the pipeline instead
- Never write back to Garmin; never commit credentials (.env)
- Context/annotations must never alter SG or authoritative scores (ADR #17)

----------
Verification Standards

Code changes:
[ ] pytest green (add tests for new logic; fixture round covers loader/view changes)
[ ] tools/parity clean when ingest/derive/export touched
[ ] `python -m src.update --no-pull` runs end-to-end; git diff on data/processed is
    either empty or explainable
[ ] ruff clean

Data questions:
[ ] Prefer querying data/turn.duckdb (duckdb CLI or Python) over parsing JSON
[ ] Authoritative hierarchy (ADR #3): scorecard counts > narrative > shot layer > GPS

----------
Context I Want Claude to Know

My role: I'm the only user AND the golfer. I iterate on this after rounds.
Working style: build it for me first, multi-tenant maybe later; prefer trustworthy
data + recomputable analytics over ceremony; small phases with verification gates.
Common tasks: new derived metrics, annotation taxonomy evolution, dashboard cards,
coach prompt tuning, post-round sync issues.

Anti-patterns to avoid:
- Don't add heavyweight deps (dbt, ORMs, pandas pipelines) — plain SQL + stdlib won
- Don't "correct" scores from shot data — the scorecard is truth (ADR #3)
- Don't let per-round noise into trend claims — respect window sizes and coverage
  badges (n= counts) on annotation-dependent metrics

Known Quirks
- Garmin revises rounds server-side after the fact (club edits, GPS refinements) —
  a re-pull can legitimately change a round; the sha-gated ingest picks it up
- The shots endpoint 400s on multi-hole requests (one hole per call, 1.5s pause)
- 9-hole rounds played as 18 reuse holes 1–9 (par/stroke-index wrap by modulo)
- Putting distances are GPS-to-green-center; the 0–3 ft band is unreliable
