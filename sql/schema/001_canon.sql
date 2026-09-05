-- canon: facts only — a faithful projection of the raw Garmin files plus nothing else.
-- Deterministic unit conversions (semicircles -> degrees) are allowed; interpretations
-- (GIR, phantom flags, SG) are NOT — those live in derived.* and are recomputable.
-- Executed by src/db.py bootstrap on every connect (idempotent).

CREATE SCHEMA IF NOT EXISTS canon;

-- Idempotency ledger: one row per ingested round; sha256 of the raw pair decides
-- whether a re-ingest is needed. loader_version bumps force a re-ingest on rebuild.
CREATE TABLE IF NOT EXISTS canon.ingest_meta (
  round_id BIGINT PRIMARY KEY,
  raw_detail_path TEXT NOT NULL,
  raw_shots_path TEXT NOT NULL,
  raw_detail_sha256 TEXT NOT NULL,
  raw_shots_sha256 TEXT NOT NULL,
  loader_version INTEGER NOT NULL,
  ingested_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS canon.round (
  round_id BIGINT PRIMARY KEY,          -- Garmin scorecard id
  round_date DATE NOT NULL,
  start_time TEXT,                      -- verbatim ISO from Garmin (fact, no tz math)
  end_time TEXT,
  score_type TEXT,
  round_type TEXT,
  holes_completed INTEGER,
  tee_box TEXT,
  tee_rating DOUBLE,
  tee_slope INTEGER,
  player_handicap DOUBLE,
  handicapped_strokes INTEGER,
  sensor_on_putter BOOLEAN,
  distance_walked_m DOUBLE,
  steps_taken INTEGER,
  course_global_id BIGINT,
  course_snapshot_id BIGINT,
  course_name TEXT,
  course_city TEXT,
  course_state TEXT,
  course_country TEXT,
  course_lat DOUBLE,
  course_lon DOUBLE,
  round_par INTEGER,
  front_nine_par INTEGER,
  back_nine_par INTEGER,
  hole_pars TEXT,                       -- verbatim holePars digit string, e.g. "433334433"
  total_strokes INTEGER,                -- AUTHORITATIVE (summed from scorecard holes)
  total_putts INTEGER,                  -- AUTHORITATIVE
  total_penalties INTEGER,              -- AUTHORITATIVE
  longest_shot_m DOUBLE,
  garmin_stats JSON,                    -- scorecardStats.round, preserved verbatim
  garmin_ratings JSON                   -- statsComparison, preserved verbatim
);

CREATE TABLE IF NOT EXISTS canon.hole (
  round_id BIGINT NOT NULL,
  hole_number INTEGER NOT NULL,
  par INTEGER,                          -- resolved: 9-hole layout played as 18 wraps modulo
  stroke_index INTEGER,                 -- from the played tee's holeHandicaps
  strokes INTEGER,                      -- AUTHORITATIVE
  putts INTEGER,                        -- AUTHORITATIVE
  penalties INTEGER,                    -- AUTHORITATIVE
  fairway_outcome TEXT,                 -- HIT / LEFT / RIGHT / NULL (par 3)
  handicap_score INTEGER,
  pin_lat DOUBLE,                       -- decimal degrees (converted from semicircles)
  pin_lon DOUBLE,
  PRIMARY KEY (round_id, hole_number)
);

CREATE TABLE IF NOT EXISTS canon.shot (
  shot_id BIGINT PRIMARY KEY,           -- Garmin's stable shot id, preserved at last
  round_id BIGINT NOT NULL,
  hole_number INTEGER NOT NULL,
  shot_order INTEGER NOT NULL,
  shot_time_ms BIGINT,                  -- epoch ms, verbatim
  shot_tz_offset_ms BIGINT,             -- verbatim, for faithful local-time rendering
  club_id BIGINT,                       -- 0 = no sensor / unselected
  club_type_id INTEGER,                 -- from the payload's clubDetails
  shot_type TEXT,                       -- TEE | APPROACH | CHIP | PUTT
  auto_shot_type TEXT,
  shot_source TEXT,                     -- SENSOR (CT10) | DEVICE_AUTO (watch)
  meters DOUBLE,
  start_lat DOUBLE, start_lon DOUBLE, start_lie TEXT,
  end_lat DOUBLE,   end_lon DOUBLE,   end_lie TEXT,   -- lieSource is always CARTOGRAPHY
  exclude_from_stats BOOLEAN
);

-- Reference tables loaded from config/ (facts about the bag, not interpretations).
CREATE TABLE IF NOT EXISTS canon.club (
  club_id BIGINT PRIMARY KEY,
  name TEXT NOT NULL,
  retired BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS canon.club_type (
  club_type_id INTEGER PRIMARY KEY,
  name TEXT NOT NULL
);

-- Expected-strokes baseline (config/sg_baseline.json). dist is yards for through-green
-- lies, FEET for lie='putt'.
CREATE TABLE IF NOT EXISTS canon.sg_baseline (
  lie TEXT NOT NULL,                    -- tee|fairway|rough|sand|recovery|putt
  dist DOUBLE NOT NULL,
  expected DOUBLE NOT NULL,
  PRIMARY KEY (lie, dist)
);
