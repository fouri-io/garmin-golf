# Garmin Golf Data Project — Specification & POC Plan

A personal project to liberate, store, and analyze my own Garmin golf data (CT10
club sensors + Garmin watch + Garmin Golf app), since Garmin Connect's native
analysis and export options are limited.

## 1. Background & motivation

I capture a rich golf dataset through the Garmin ecosystem — CT10 club sensors
feed the watch, which syncs through the Garmin Golf app up to Garmin's cloud
(connect.garmin.com). The data collection is excellent; the **analysis and export
are weak**. There's no clean way to get scores or shot-by-shot data out for use in
Excel or custom tooling, and the web portal doesn't show the per-hole shot maps
that the mobile app does.

I'm an engineer. This is solvable, and this document is the plan to solve it.

## 2. Guiding principles

- **Own the raw data.** Persist every raw API response to disk *before* parsing.
  The data is the asset; parsing is disposable and re-runnable.
- **Defensive by default.** The data source is an *unofficial* (reverse-engineered)
  set of Garmin Connect endpoints. They have broken before and will again. Isolate
  the API layer so a breakage is a contained problem, not a data-loss event.
- **Analysis-first.** The point is to answer questions Garmin won't (club
  dispersion, strokes gained, shot maps). Every phase should move toward that.
- **Incremental.** Prove the data is reachable and useful (Phase 0) before building
  anything durable on top of it.

## 3. Scope

**In scope (across the life of the project)**

- Pull scorecard summaries, per-hole detail, and shot-by-shot data from Garmin
  Connect using my own login.
- A local, durable store of both raw and normalized data.
- Exploratory analysis in pandas / Excel.
- Shot-map visualization, overlaying georeferenced shots on satellite imagery.

**Out of scope (deliberately)**

- **Direct watch or sensor interface.** The CT10 → watch link is proprietary; no
  realistic payoff. The data ends up in the cloud in a far more usable form anyway.
- **Garmin's proprietary course vector maps.** The hole geometry the app draws is
  licensed data, available only through Garmin's paid, partner-only Golf Premium
  API. We will *not* try to extract it; shot maps will use satellite tiles instead
  (see Phase 3).
- **Writing/uploading anything back to Garmin.** Read-only, personal use.

## 4. PHASE 0 — Proof of Concept (immediate goal)

**Objective:** Authenticate with my own credentials, pull score and shot data, and
produce a clear inventory of *what fields actually exist and are populated* — so I
can design the real project from facts, not guesses.

This is the only phase with full detail. It is intentionally small.

### 4.1 Success criteria

- [ ] Authenticated session established, with token caching so I'm not logging in
      every run.
- [ ] Retrieved a list of recent scorecards (summary level).
- [ ] Retrieved full detail for one scorecard (per-hole data).
- [ ] Retrieved shot-by-shot data for that scorecard, and confirmed whether **club
      identity per shot** (from the CT10s) is present.
- [ ] Every raw response saved as JSON under `data/raw/`.
- [ ] A generated **data dictionary**: for each field — name, JSON path, type, an
      example value, and the % of records where it's populated.
- [ ] One hole's shots converted to decimal lat/lon and plotted as a scatter,
      visually sanity-checked against the real hole on a satellite map.

### 4.2 POC task list

1. **Environment + library introspection.** Create the venv, install deps, and
   *discover the golf method names and signatures* rather than assuming them. The
   library's golf endpoints were added/fixed recently, so confirm the exact method
   names from `demo.py` (the "🍿 Golf" menu) or the source.
2. **Auth + token cache + MFA.** Log in via env-var or `getpass` credentials; reuse
   the cached token store on subsequent runs; handle a possible MFA prompt
   interactively.
3. **Pull scorecard summaries.** Get the list of recent rounds; save raw JSON; note
   the scorecard ID field — it's the key for the next calls.
4. **Pull one scorecard's detail + shots.** Using an ID from step 3, pull per-hole
   detail and shot-by-shot; save both raw.
5. **Field inventory script.** Recursively flatten the saved JSON and emit the data
   dictionary described in the success criteria.
6. **Coordinate conversion.** Convert shot positions to decimal degrees and verify
   against a known point (see §7 note on encoding).
7. **Quick visual.** matplotlib scatter of one hole's shots, tee → green.

### 4.3 Deliverables

- `data/raw/*.json` — the saved responses.
- `data_dictionary.csv` (or `.md`) — the field inventory.
- `poc.ipynb` or `poc.py` — the runnable demonstration.

### 4.4 Starter snippet (verify method names in task 1)

```python
import os, json, getpass
from garminconnect import Garmin

# --- auth ---
email = os.environ.get("GARMIN_EMAIL") or input("Garmin email: ")
password = os.environ.get("GARMIN_PASSWORD") or getpass.getpass("Garmin password: ")

# The library caches tokens under ~/.garminconnect/ — reuse if present.
api = Garmin(email, password)
api.login()  # may trigger an MFA prompt depending on account settings

# --- discover the golf methods (do this FIRST) ---
golf_methods = [m for m in dir(api) if "golf" in m.lower() or "scorecard" in m.lower()]
print("Candidate golf methods:", golf_methods)

# Save EVERY response raw before doing anything else:
def dump(obj, name):
    os.makedirs("data/raw", exist_ok=True)
    with open(f"data/raw/{name}.json", "w") as f:
        json.dump(obj, f, indent=2)
```

Dependency set: `pip install garminconnect curl_cffi ua-generator` (the latter two
are required by recent versions).

## 5. Tech stack

**POC:** Python 3.11+, `garminconnect` (+ `curl_cffi`, `ua-generator`), `pandas`,
`python-dotenv`/`getpass` for credentials, `matplotlib` for sanity plots. Built and
driven with Claude Code.

**Later phases (anticipated):** DuckDB or SQLite + Parquet for storage; Streamlit or
a Leaflet/MapLibre front-end for shot-map visualization.

## 6. Credentials & security

- **Never hardcode or commit credentials.** Use a `.env` file that is gitignored, or
  interactive `getpass`.
- The library persists a token store (under `~/.garminconnect/`); reuse it so each
  run doesn't re-authenticate. Token format changed in recent versions — a fresh
  login may be required after an upgrade.
- The account may enforce **MFA**; the library supports the flow — handle it
  interactively during the POC.
- This is read-only, personal-use access to my own account data.

## 7. Provisional data model (to be REPLACED by the POC's findings)

This is a guess to be confirmed — the data dictionary from Phase 0 is the source of
truth.

| Level | Expected fields (provisional) |
| --- | --- |
| Scorecard summary | scorecard id, date/time, course name + id, total strokes, holes played |
| Scorecard detail | per hole: par, strokes, putts, fairway hit, GIR |
| Shot record | scorecard id, hole #, shot #, **club type (CT10)**, latitude, longitude, distance |

**Coordinate encoding note:** Garmin stores positions in a semicircle-style integer
encoding, not plain decimal degrees. The standard conversion is
`degrees = semicircles × (180 / 2^31)`. The exact golf-export format has caused
community confusion, so convert one shot and verify it lands on the correct hole on
a satellite map before trusting the whole dataset.

## 8. Suggested repo structure

```
garmin-golf/
├── README.md
├── .env.example          # GARMIN_EMAIL=, GARMIN_PASSWORD=  (real .env is gitignored)
├── .gitignore            # ignores .env, data/, ~/.garminconnect tokens
├── pyproject.toml        # or requirements.txt
├── src/
│   ├── garmin_client.py  # THE isolated API layer — all unofficial calls live here
│   ├── pull.py           # orchestrates pulls, always dumps raw first
│   ├── parse.py          # raw JSON -> normalized DataFrames
│   └── geo.py            # semicircle -> decimal conversion, helpers
├── data/
│   ├── raw/              # untouched API responses (the asset — never delete)
│   └── processed/        # parsed parquet/csv
└── notebooks/
    └── poc.ipynb
```

## 9. Architecture / data flow

```
Garmin Connect (cloud)
        │   garmin_client.py  (the ONLY module that touches unofficial endpoints)
        ▼
   raw JSON  ──►   data/raw/   (persisted immediately, before any parsing)
        │   parse.py
        ▼
 normalized DataFrames  ──►   data/processed/  (parquet/sqlite)
        │
        ▼
   analysis & visualization
```

The single most important rule: **raw response hits disk before parsing.** A
server-side change can never cost data already retrieved.

## 10. Risks & constraints

- **Unofficial endpoints (ToS gray area + breakage risk).** Mitigate by isolating
  all API access in `garmin_client.py`, pinning the library version, and caching raw
  responses. There is precedent for these endpoints breaking and later being patched.
- **Rate limiting.** Be gentle — add small delays, avoid tight loops over all
  history at once, especially during the POC.
- **Course geometry is not available.** Confirmed: Garmin's hole vector maps are
  behind the paid partner API. Shot maps will use satellite tiles (Phase 3);
  optional stylized vector polygons would come from a third-party course-data API
  (e.g. Golfbert), matched to courses by name + shot coordinates.

## 11. Future phases (sketch — refine after Phase 0)

- **Phase 1 — Durable sync.** Incremental "pull only new rounds" job; raw +
  normalized storage; idempotent re-runs.
- **Phase 2 — Analysis layer.** Club distance distributions, dispersion,
  strokes-gained vs a baseline, trend tracking. Excel/CSV export that's actually
  pleasant to use.
- **Phase 3 — Shot maps.** Interactive hole-by-hole shot maps on satellite imagery
  (Leaflet/MapLibre + Esri World Imagery), auto-zoomed to each hole's shot bounding
  box.
- **Phase 4 (optional) — Vector course overlay.** Stylized green/fairway/hazard
  polygons via a third-party course-geodata API, for the "app-like" look.

## 12. Open questions for the POC to answer

1. Exact golf method names and signatures in the current library version?
2. Does shot-by-shot data include **club identity per shot** (the CT10 value)?
3. Confirmed coordinate format and conversion?
4. How far back does history reach, and is pagination required to get it all?
5. Which fields are reliably populated vs. sparse/empty?
6. What's the relationship/key between summary, detail, and shot records?
