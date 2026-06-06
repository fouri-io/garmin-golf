# Architecture — pipeline, modules, data flow

## The pipeline
```
Garmin Connect (unofficial endpoints)
   │  src/garmin_client.py   ← the ONLY module that touches Garmin
   ▼
src/pull.py  ──► data/raw/*.json            (raw saved verbatim, before parsing)
   │  src/parse.py
   ▼
data/processed/rounds/<YYYY_MM_DD_id>.json+.md   (one self-contained round document)
   │  src/analyze.py            src/progress.py
   ▼                              ▼
club_stats.{json,md}          progress.{json,md}   (cross-round aggregates)
   │  src/site.py
   ▼
site/index.html               (one responsive self-contained PWA)
   │  src/coach.py (optional)
   ▼
data/processed/coach/<stem>.md  (AI round report)

src/update.py orchestrates all of the above (+ optional publish/deploy).
```

## Modules (`src/`)
| Module | Responsibility |
|---|---|
| `garmin_client.py` | Isolated Garmin Connect access (login + token cache + MFA, golf wrappers). The only place unofficial endpoints live. |
| `pull.py` | Orchestrate pulls; raw hits disk before parsing. `--all` pulls every real round (skips SIM + pre-cutoff). |
| `parse.py` | Raw → round document. Preserves every Garmin field; adds derived layer; computes Strokes Gained (via `strokes_gained.py`). |
| `strokes_gained.py` | Per-shot SG, distance buckets, count-based putting, the SG 0–100 metric. |
| `geo.py` | Semicircle→decimal coords, haversine, shot-direction geometry. |
| `analyze.py` | Cross-round `club_stats` (per physical clubId distances). Holds shared SG category constants. |
| `progress.py` | Cross-round dashboard data: scoring level, the 3 windows (this/last5/all), per-bucket SG, baselines, putting, time series. |
| `site.py` | Static site generator → `site/index.html` (data inlined, no fetch). |
| `coach.py` | AI round report via the Anthropic API + the living golfer spec. |
| `update.py` | One-command pipeline (+ `--publish`/`--push`/`--coach`). |
| `config.py` | Loaders for `config/*.json` (analysis cutoff, SG cuts, target handicap, publish target). |
| `introspect.py` | List Garmin golf API methods (no creds/network). |

## Data flow & storage (flat files, no DB)
- `data/raw/` — untouched Garmin responses. **The asset; never edited.** Gitignored.
- `data/processed/rounds/<YYYY_MM_DD_id>.{json,md}` — round documents (versioned).
- `data/processed/{progress,club_stats}.{json,md}` — aggregates (versioned).
- `data/processed/coach/` — AI reports (versioned).
- `site/index.html` — generated dashboard (versioned).
- `config/*.json`, `config/golfer_profile.md` — configuration (versioned).

**The one inviolable rule:** raw response hits disk *before* any parsing, so a
server-side change can never cost data already retrieved. Parsing is disposable and
re-runnable from raw.

## Storage seam (future S3)
Everything reads/writes the local filesystem under `data/` and `site/`. To move to
AWS, the clean boundary is a thin storage layer (`read_raw`/`write_processed`) that
can target local FS or S3 by config — a small refactor, not yet done.

## Deploy
`site/index.html` is copied to `~/dev/colbyward.io/golf/index.html` (configurable via
`config/analysis.json` → `publish.targetDir`). That repo auto-deploys to S3 +
CloudFront via a GitHub Action on push. A CloudFront Function rewrites `/golf/` →
`/golf/index.html`. The page is `noindex` (unlisted). Recommended split for any future
cloud automation: **pull at home** (Garmin rate-limits datacenter IPs), **compute in
the cloud** (pure-compute parse/analyze/progress/site).

## Commands
See the repo `README.md` "Commands reference". The one-liner: `python -m src.update
<id> --push`.
