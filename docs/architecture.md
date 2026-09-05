# Architecture — pipeline, modules, data flow

## The pipeline
```
Garmin Connect (unofficial endpoints)
   │  src/garmin_client.py   ← the ONLY module that touches Garmin
   ▼
src/pull.py  ──► data/raw/*.json                 (verbatim, committed — the asset)
You           ──► data/annotations/<stem>.md      (post-round narrative, committed)
src/annotate.py ─► data/annotations/<stem>.tags.json  (confirmed shot/hole tags)
   │  src/ingest.py   (raw + annotations + config → canonical, sha-gated per round)
   ▼
data/turn.duckdb   ← the spine (gitignored, fully rebuildable from committed files)
  canon.*   facts only (round/hole/shot with Garmin shot_id, clubs, SG baseline)
  annot.*   narrative + shot/hole context (never overwrites facts or SG)
  derived.* recomputable: geometry, per-shot SG, flags/recon views, metrics
   │  src/derive.py  (Python: geometry via geo.py, SG via sg_core.py)
   ▼
src/export_rounds.py ──► data/processed/rounds/<stem>.{json,md}   (round docs, schema v2)
src/analyze.py       ──► club_stats.{json,md}     (DB query)
src/progress.py      ──► progress.{json,md}       (DB query; 5 windows + priority metrics)
   │  src/coach.py (optional — LLM report; prompt includes narrative + tags)
   ▼
data/processed/coach/<stem>.md
   │  src/site.py
   ▼
site/index.html               (one responsive self-contained PWA)

src/update.py orchestrates all of the above (+ optional publish/deploy).
```

## The three layers (the load-bearing idea)

> **Store facts permanently. Derive interpretations temporarily.**

- **Raw** — committed files: Garmin JSON (`data/raw/`), the player's narrative and
  confirmed tags (`data/annotations/`), config. Every write in the system originates
  in one of these files; the database never holds unique state.
- **Canonical** (`canon.*`, `annot.*`) — a faithful projection of the raw files.
  Deterministic unit conversion only (semicircles→degrees, holePars→per-hole par).
  Garmin's stable `shot_id` is the shot primary key.
- **Derived** (`derived.*`) — everything interpretive, recomputable at will: shot
  geometry, phantom/confidence flags, reconciliation, GIR/scrambling, SG, putting
  bands, the priority metrics. Change a definition → edit SQL or `derive.py` →
  `python -m src.db rebuild`.

`data/turn.duckdb` is a **durable materialized index**: it persists between runs and
ingests incrementally (per-round sha check in `canon.ingest_meta`), but it is
gitignored because it is reproducible — git durability lives with the raw files.

## Modules (`src/`)
| Module | Responsibility |
|---|---|
| `garmin_client.py` | Isolated Garmin Connect access (login + token cache + MFA). The only place unofficial endpoints live. |
| `pull.py` | Orchestrate pulls; raw hits disk before anything else. Dated summary snapshots under `data/raw/summaries/`. |
| `db.py` | Connect/bootstrap (runs `sql/schema/*.sql` in order), `rebuild`, `status`. |
| `ingest.py` | Raw JSON + annotations + config → `canon.*`/`annot.*`. Idempotent, incremental, transactional per round. |
| `derive.py` | Python-written derived tables: shot geometry, per-shot SG, putting expectations. |
| `sg_core.py` | Pure SG math (baseline interpolation, categorization, per-shot SG). |
| `geo.py` | Semicircle→decimal coords, haversine, shot-direction geometry. |
| `annotate.py` | Narrative scaffold → LLM tag proposal → validate/confirm loop. |
| `export_rounds.py` | DB → round documents (schema v2, faithful superset + annotations). |
| `analyze.py` | Cross-round `club_stats` (per physical clubId; excludes phantom/suspect/non-stock shots). |
| `progress.py` | Dashboard data: 5 windows (this/5/10/20/all), SG, baselines, fine putting bands, priority metrics. |
| `site.py` | Static site generator → `site/index.html` (data inlined, no fetch). |
| `coach.py` | AI round report (Anthropic/OpenAI) + the living golfer spec + the player's own notes. |
| `update.py` | One-command pipeline (+ `--rebuild`/`--publish`/`--push`/`--coach`). |
| `constants.py` | Single home for SG categories, quality gates, unit constants. |
| `config.py` | Loaders for `config/*.json`. |
| `putting.py` | Fine putting bands over round-document holes (mirrors `derived.putting_bands`). |
| `introspect.py` | List Garmin golf API methods (no creds/network). |

`sql/schema/*.sql` — executed in filename order on every connect; tables are
`IF NOT EXISTS`, views are `CREATE OR REPLACE` (definition changes deploy with code).
`tools/parity.py` — self-consistency gate: exported docs vs the DB.

## Storage
- `data/raw/` — untouched Garmin responses. **The asset; never edited. Committed.**
- `data/annotations/` — narrative `.md` + confirmed `.tags.json` (committed);
  `.tags.proposed.json` LLM drafts are gitignored/disposable.
- `data/turn.duckdb` — the spine; gitignored; `python -m src.db rebuild` recreates it.
- `data/processed/` — exports (round docs, aggregates, coach reports). Versioned,
  regenerable; never hand-edited.
- `site/index.html` — generated dashboard (versioned).
- `config/` — configuration + `golfer_profile.md` (versioned, hand-edited).

**The one inviolable rule:** raw response hits disk *before* any parsing, so a
server-side change can never cost data already retrieved. Everything downstream is
disposable and re-runnable from the committed files.

## Deploy
`site/index.html` is copied to `~/dev/colbyward.io/golf/index.html` (configurable via
`config/analysis.json` → `publish.targetDir`). That repo auto-deploys to S3 +
CloudFront via a GitHub Action on push. A CloudFront Function rewrites `/golf/` →
`/golf/index.html`. The page is `noindex` (unlisted). Recommended split for any future
cloud automation: **pull at home** (Garmin rate-limits datacenter IPs), **compute in
the cloud** (pure-compute ingest/derive/export/site).

## Commands
See the repo `README.md` "Commands reference". The one-liner: `python -m src.update
--push`. After schema/loader changes: `python -m src.update --rebuild`.
