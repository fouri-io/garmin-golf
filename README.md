# garmin-golf

Liberate, store, and analyze my own Garmin golf data (CT10 club sensors + Garmin
watch + Garmin Golf app). Garmin Connect's native analysis and export are weak;
this project pulls the raw data out for analysis in pandas / Excel and for shot-map
visualization.

See [SPEC.md](SPEC.md) for the full plan. **We are in Phase 0 (POC).**

## Guiding rules

- **Own the raw data.** Every raw API response is persisted to `data/raw/` *before*
  parsing. Parsing is disposable and re-runnable.
- **Defensive by default.** The Garmin endpoints are unofficial and breakable. All
  API access is isolated in `src/garmin_client.py`.
- **Read-only, personal use.** Never write back to Garmin. Never commit credentials.

## Setup

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # then fill in GARMIN_EMAIL / GARMIN_PASSWORD (or use getpass)
```

Dependency note: recent `garminconnect` versions also require `curl_cffi` and
`ua-generator` (pulled in automatically by the install above).

## After each round (the one-liner)

```bash
python -m src.update <scorecard_id> --push   # pull → parse → analyze → progress → site → deploy
```

`update` runs the whole pipeline. Variants:
- `python -m src.update` — just rebuild the dashboard from existing rounds
- `python -m src.update <id>` — pull + parse a new round, then rebuild
- `python -m src.update --all` — pull every real round
- `python -m src.update --reparse` — re-parse all tracked rounds (after a config/parser change)
- add `--publish` to copy `site/index.html` to `config.publish.targetDir`, or `--push` to also
  git commit+push that repo (auto-deploys to S3 via its Action)

The dashboard is the single output: open `site/index.html` (or the deployed URL).

## Commands reference

Every step is also runnable on its own (all run from the repo root, in the venv):

| Command | What it does |
|---|---|
| `python -m src.update <id> --push` | **The one-liner** — pull a new round, rebuild, deploy |
| `python -m src.update` | Rebuild dashboard from existing rounds |
| `python -m src.update --all` | Pull every real round, then rebuild |
| `python -m src.update --reparse` | Re-parse all tracked rounds (after a config change) |
| `python -m src.update --publish` / `--push` | Also copy to / deploy the publish target |
| `python -m src.pull <id>` | Pull one round's raw JSON (summary + detail + shots) |
| `python -m src.pull --all` | Pull every real round's raw (skips SIM + pre-cutoff) |
| `python -m src.parse <id>` | Parse one round's raw → `data/processed/rounds/<date>_<id>.json` + `.md` |
| `python -m src.analyze` | Build `club_stats.{json,md}` (per-club distances) |
| `python -m src.progress` | Build `progress.{json,md}` (the dashboard data) |
| `python -m src.site` | Generate the static site → `site/index.html` |
| `python -m src.introspect` | List the Garmin golf API methods (no creds, no network) |

Most-used config lives in `config/`:
- `config/clubs.json` — club identity (which `clubId` is which club)
- `config/analysis.json` — analysis cutoff date, SG distance cuts, target handicap,
  publish target
- `config/sg_baseline.json` — the scratch expected-strokes table

Outputs:
- `data/processed/progress.{json,md}` — the dashboard (what you read)
- `data/processed/club_stats.{json,md}` — club gapping
- `data/processed/rounds/<date>_<id>.{json,md}` — per-round detail
- `site/index.html` — the deployable dashboard

## Phase 0 task list (work one at a time)

1. **Library introspection** — discover the real golf method names (no creds needed):
   ```bash
   python -m src.introspect
   ```
2. **Auth + token cache + MFA** — `src/garmin_client.py:login()`.
3. **Pull scorecard summaries** — save raw, note the scorecard ID field.
4. **Pull one scorecard's detail + shots** — save both raw.
5. **Field inventory** — `src/parse.py` → `data_dictionary.csv`.
6. **Coordinate conversion** — `src/geo.py`, verify one shot against a map.
7. **Quick visual** — matplotlib scatter of one hole, tee → green.

## Layout

```
src/garmin_client.py  # THE isolated API layer — all unofficial calls live here
src/introspect.py     # task 1: discover golf method names (no network)
src/pull.py           # orchestrates pulls, always dumps raw first
src/parse.py          # raw JSON -> normalized DataFrames + data dictionary
src/geo.py            # semicircle -> decimal conversion, helpers
data/raw/             # untouched API responses (the asset — never delete)
data/processed/       # parsed parquet/csv
notebooks/poc.ipynb   # runnable demonstration
```
