# Data model — raw → round document

## Raw (the asset)
Three Garmin golf endpoints (confirmed against `garminconnect` 0.3.5):
- `get_golf_summary(start, limit)` → list of recent scorecards
- `get_golf_scorecard(scorecardId)` → per-hole detail + course snapshot
- `get_golf_shot_data(scorecardId, hole_numbers)` → shot-by-shot **(one hole per call;
  the endpoint 400s on multi-hole requests, so `get_all_shots` loops holes 1–18)**

Saved verbatim to `data/raw/`:
- `golf_summary.json`
- `scorecard_<id>_detail.json`
- `scorecard_<id>_shots.json` (`{scorecardId, perHole:[{hole, response}]}`)

Keys: `scorecardId` joins all three levels; `clubId` joins shots→clubDetails;
`holeNumber`+`shotOrder` order shots. Coordinates are **semicircles** (`degrees =
semicircles × 180/2^31`), converted in `geo.py`.

## Round document (`data/processed/rounds/<YYYY_MM_DD_id>.json`)
A faithful **superset**: every Garmin field preserved, derived fields added alongside
(never replacing), provenance kept. Filename is date-prefixed for browsability.

Top-level keys:
- `scorecardId`, `round` (date/tees/handicap/walked), `course` (name/location/par/holePars/lat-lon)
- `score` — **authoritative** (strokes, par, toPar, putts, penalties, holesCompleted)
- `coachSummary` — round metrics (fairways, GIR, scrambles, first-putt avg, etc.)
- `garminStats` / `garminRatings` — Garmin's own rollups, preserved verbatim
- `strokesGained` — see strokes-gained.md (byCategory, sg0to100, putting, penalties, doubles)
- `reconciliation` — recordedShots vs strokes, shotCountDelta, suspectHoles, emptyShotHoles
- `holes[]` — per hole: par, strokes, putts, penalties, scoreToPar, fairway, **gir** (derived),
  strokeIndex, playedLengthYds (proxy), firstPuttDistanceFt, pin (decimal), `shots[]`
- `shots[]` — shotNumber, **club** (resolved name), clubId, clubTypeId, clubRetired, type,
  source (SENSOR vs DEVICE_AUTO), yards+meters, from/to **lie**, start/end `{lat,lon,lie,lieSource}`,
  distanceToPinBeforeYds, distanceRemainingYds, sgCategory, strokesGained, offMap

## Authoritative vs derived (the trust hierarchy)
- **Authoritative (trust fully):** score, strokes, putts, penalties, 3-putts, course rating,
  fairway outcome, GIR count — from the scorecard, no GPS.
- **Garmin-provided:** lie/lieSource (computed by Garmin from licensed map polygons —
  `CARTOGRAPHY`, not a ground sensor; `Unknown` = off-map), meters, club identity.
- **Derived (ours, labeled):** yards, gir, scoreToPar, distance-to-pin, Strokes Gained,
  reconciliation.

## Reconciliation (data-quality, surfaced not hidden)
The shot layer is imperfect: it can **under-record** (un-sensed short shots; penalties
carry no shot position) or **over-record** (phantom/practice strokes). So:
- `shotCountDelta = recordedShots − strokes` (+ over, − under)
- `suspectHoles` — holes where recorded ≫ strokes (sensor noise; excluded from club/SG aggregates)
- `emptyShotHoles` — scored holes with no recorded shots (data gap)
The **score is always authoritative**; the shot layer is spatial/club detail.

## Club identity (`config/clubs.json`)
Garmin's `clubTypeId` is a coarse bucket that collapses distinct clubs (two wedges →
one). So clubs are resolved by **physical `clubId` first** (`byClubId`), falling back
to `clubTypeId` (`map`). `retiredClubIds` are excluded from analysis. This is what
keeps the 50/54/58 wedges separate.

## Analysis window (`config/analysis.json`)
`analysisStartDate` (2026-05-01) excludes pre-cutoff rounds — before then the sensors
weren't in the clubs and the bag differed, so the club map doesn't apply. SIM rounds
(`roundType == "SIMULATION"`) are always excluded.
