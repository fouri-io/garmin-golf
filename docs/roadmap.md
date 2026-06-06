# Roadmap & research notes

## Built
Pull/parse pipeline · round documents · Strokes Gained (distance buckets, count-based
putting, SG 0–100) · club gapping · reconciliation/data-quality flags · selectable
baselines (scratch/my-average/target) · responsive PWA · per-round shot detail ·
satellite shot maps · one-command update + deploy · docs · **(building)** Trend view +
AI coach.

## Near-term feature backlog
- **Proximity** — avg "leave" by distance band (free from `distanceRemaining` we store).
- **Up-and-down / scrambling by lie** — re-add (had it; dropped in a refactor). Authoritative-ish.
- **Standard categories toggle** — OTT / APP / ARG(<30yd) / Putting, for app comparability.
- **Driver-dispersion map** — all drives normalized to a common target line (left/right +
  distance scatter); turns "Off-Tee −8" into a visible miss pattern. Ties to dispersion goal.
- **Putting make-% by distance** — blocked by data (no reliable per-putt distances from the
  export; the S44 watch may expose more — worth investigating).

## Infra
- **Storage seam** (`read_raw`/`write_processed`) → local FS or S3 by config.
- **Cloud automation** — pull at home (Garmin rate-limits datacenter IPs), compute in a
  Lambda/Step-Functions pipeline writing to S3; phone ⟳ triggers the compute half.

## Data-quality frontier
- Investigate whether the **Garmin S44 watch** export carries cleaner putt-by-putt data
  than the Connect endpoints (would unlock real putting make-%).
- Better short-game GPS handling (Inside-50 magnitude is approximate).

## Hardware exploration (researched, shelved)
What's inside CT10/Arccos/Shot Scope: the **GPS is in the watch/phone, not the grip**.
The grip puck only answers "which club + did it impact." Three architectures: active
BLE+IMU (Arccos/CT10), active ANT+ (Garmin → watch), passive RFID (Shot Scope → needs a
wrist reader; NFC range is too short for a pocket phone). Industry is drifting sensorless
(Arccos Air: phone-less IMU+GPS, but **can't identify the club** — manual edit; $350 +
$200/yr).

DIY verdict: a **phone-as-hub + active nRF52 + accelerometer grip puck** (~$5–8/club,
pairs once, years on a coin cell) is very feasible and would feed the existing
`(club, time, lat, lon)` schema directly. Club ID requires the puck to self-detect
impact (proximity/RSSI is too noisy; NFC too short-range for a pocket phone). Commercial
play is the **analytics/coaching layer**, hardware-agnostic — not another puck (cheap,
undifferentiated, patent-risky: e.g. US 8,142,302 / US 9,050,519).
