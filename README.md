# The Turn (garmin-golf)

Liberate, store, and analyze my own Garmin golf data (CT10 club sensors + Garmin
watch + Garmin Golf app) — and turn it into a longitudinal analytics system that
explains not just *what* I scored, but *how and why* the score happened.

Docs live in [`docs/`](docs/README.md) (start with `overview.md` → `architecture.md`).
Design decisions are ADRs in [`docs/decisions.md`](docs/decisions.md).

## Guiding rules

- **Own the raw data.** Every raw API response is persisted to `data/raw/` *before*
  parsing, and committed. Everything downstream rebuilds from committed files.
- **Store facts permanently, derive interpretations temporarily.** Facts live in the
  canonical layer (`data/turn.duckdb`, rebuildable); analytics are recomputable views.
- **Context never overwrites facts.** Post-round notes and shot tags enrich analysis
  (and clean the club stats) but never change SG or the scorecard.
- **Defensive by default.** The Garmin endpoints are unofficial and breakable. All
  API access is isolated in `src/garmin_client.py`.
- **Read-only, personal use.** Never write back to Garmin. Never commit credentials.

## Setup

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # then fill in GARMIN_EMAIL / GARMIN_PASSWORD (or use getpass)
python -m src.db rebuild   # build data/turn.duckdb from the committed raw files
```

## After each round

```bash
python -m src.update --push        # sync new rounds → db → analyze → coach → site → deploy
python -m src.annotate             # then: write post-round notes for the latest round
python -m src.annotate <id> --structure   # LLM proposes shot/hole tags from your notes
python -m src.annotate <id> --confirm     # review, validate, promote to .tags.json
```

Annotations feed the process metrics (clean second-shot %, one-shot recovery %,
normal-approach GIR %) and the coach's context — the more rounds annotated, the
better the "why" gets.

## Commands reference

| Command | What it does |
|---|---|
| `python -m src.update --push` | **The one-liner** — sync, rebuild, coach, deploy, verify |
| `python -m src.update` | Incremental sync (pull only new rounds) + rebuild |
| `python -m src.update --no-pull` | Rebuild only, no network (offline) |
| `python -m src.update <id>` | Pull just one specific round |
| `python -m src.update --all` | Force re-pull every real round (ignore cache) |
| `python -m src.update --rebuild` | Drop + rebuild the DB, re-derive, re-export all rounds |
| `python -m src.db rebuild` / `status` | Rebuild / inspect `data/turn.duckdb` |
| `python -m src.ingest [--force]` | Raw + annotations + config → canonical tables |
| `python -m src.derive` | Recompute derived tables (geometry, SG, putting) |
| `python -m src.export_rounds [id]` | DB → round documents (schema v2) |
| `python -m src.annotate [id] [--structure/--confirm]` | The annotation flow |
| `python -m src.analyze` | Build `club_stats.{json,md}` (per-club distances) |
| `python -m src.progress` | Build `progress.{json,md}` (the dashboard data) |
| `python -m src.site` | Generate the static site → `site/index.html` |
| `python -m tools.parity` | Self-consistency gate: exported docs vs the DB |
| `pytest` (`-m slow` for parity) | The test suite |

Config lives in `config/`: `clubs.json` (club identity), `analysis.json` (cutoff, SG
cuts, target handicap, publish target), `sg_baseline.json` (scratch expected-strokes
table), `golfer_profile.md` (the living spec the AI coach reads).

Data:
- `data/raw/` — verbatim Garmin JSON (committed; the asset)
- `data/annotations/` — post-round narrative + confirmed tags (committed)
- `data/turn.duckdb` — canonical + derived layers (gitignored, rebuildable)
- `data/processed/` — exports: round docs, `progress`, `club_stats`, coach reports
- `site/index.html` — the deployable dashboard (open locally or at the deployed URL)
