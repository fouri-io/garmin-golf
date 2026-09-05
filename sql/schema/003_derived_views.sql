-- derived: recomputable interpretations over canon facts. Tables here are written by
-- src/derive.py (Python, because they need geometry/interpolation); everything else is
-- a view, redefined on every bootstrap so definition changes deploy with the code.
-- Nothing in this schema is ever the source of anything — drop it and re-derive.

CREATE SCHEMA IF NOT EXISTS derived;

-- Haversine shot geometry (start/end vs the hole's pin), written by derive.py using
-- src/geo.py — the same code path the legacy parser used, so numbers match exactly.
CREATE TABLE IF NOT EXISTS derived.shot_geom (
  shot_id BIGINT PRIMARY KEY,
  yards DOUBLE,                         -- meters * 1.09361, rounded 0.1 (legacy parity)
  to_pin_before_yds DOUBLE,
  remaining_yds DOUBLE,
  miss_range TEXT,                      -- short | long
  miss_side TEXT,                       -- left | right | straight
  lateral_yds DOUBLE
);

-- Per-shot SG (written by derive.py from canon + shot_geom + sg_core). Phantom shots
-- get no row — they aren't strokes.
CREATE TABLE IF NOT EXISTS derived.shot_sg (
  shot_id BIGINT PRIMARY KEY,
  sg_category TEXT,                     -- offTee|longApproach|midApproach|inside50|putting
  strokes_gained DOUBLE,                -- NULL for putts (count-based) and ungradeable shots
  sg_version INTEGER NOT NULL
);

-- Per-hole putting expectation (written by derive.py; needs baseline interpolation).
-- Putting SG for a hole = expected_putts - actual putts (authoritative count).
CREATE TABLE IF NOT EXISTS derived.hole_putting (
  round_id BIGINT NOT NULL,
  hole_number INTEGER NOT NULL,
  first_putt_ft DOUBLE NOT NULL,
  expected_putts DOUBLE NOT NULL,
  PRIMARY KEY (round_id, hole_number)
);

-- Confidence layer, per shot. Phantom = between-hole transit logged as a stroke; the
-- thresholds mirror the legacy parser (constants.MAX_PLAUSIBLE_*).
CREATE OR REPLACE VIEW derived.shot_flags AS
SELECT s.shot_id,
       coalesce(g.yards, 0) > 400 OR coalesce(g.to_pin_before_yds, 0) > 700   AS phantom,
       CASE WHEN coalesce(g.yards, 0) > 400 THEN 'implausible-distance'
            WHEN coalesce(g.to_pin_before_yds, 0) > 700 THEN 'off-hole-start'
       END                                                                     AS phantom_reason,
       s.end_lie = 'Unknown'                                                   AS off_map,
       CASE WHEN coalesce(g.yards, 0) > 400
              OR coalesce(g.to_pin_before_yds, 0) > 700 THEN 'anomalous'
            WHEN s.end_lie = 'Unknown'                  THEN 'approximate'
            WHEN s.shot_source = 'DEVICE_AUTO'          THEN 'inferred'
            ELSE 'authoritative'
       END                                                                     AS confidence
FROM canon.shot s
LEFT JOIN derived.shot_geom g USING (shot_id);

-- Per-hole reconciliation: how the sensor shot layer squares with the authoritative
-- score. Mirrors the legacy round document's reconciliation block.
CREATE OR REPLACE VIEW derived.hole_recon AS
SELECT h.round_id, h.hole_number, h.strokes,
       count(s.shot_id) FILTER (WHERE NOT f.phantom)                 AS shots_recorded,
       count(s.shot_id) FILTER (WHERE f.phantom)                     AS phantom_shots,
       CASE WHEN h.strokes IS NOT NULL
            THEN count(s.shot_id) FILTER (WHERE NOT f.phantom) - h.strokes
       END                                                           AS shot_count_delta,
       coalesce(h.strokes, 0) > 0
         AND (count(s.shot_id) FILTER (WHERE NOT f.phantom) - h.strokes) > 2
                                                                     AS suspect,
       coalesce(h.strokes, 0) > 0
         AND count(s.shot_id) FILTER (WHERE NOT f.phantom) = 0       AS empty_shot_data
FROM canon.hole h
LEFT JOIN canon.shot s ON s.round_id = h.round_id AND s.hole_number = h.hole_number
LEFT JOIN derived.shot_flags f ON f.shot_id = s.shot_id
GROUP BY h.round_id, h.hole_number, h.strokes;

-- Round-level reconciliation + the clean-round gate for SG windows (POLLUTION_DELTA=3).
CREATE OR REPLACE VIEW derived.round_recon AS
SELECT r.round_id,
       sum(hr.shots_recorded)                                        AS shots_recorded,
       sum(hr.phantom_shots)                                         AS phantom_shots,
       sum(hr.shots_recorded) - r.total_strokes                      AS shot_count_delta,
       (sum(hr.shots_recorded) - r.total_strokes) <= 3               AS clean
FROM canon.round r
JOIN derived.hole_recon hr USING (round_id)
GROUP BY r.round_id, r.total_strokes;

-- First-putt distance: how far from the cup when the ball reached the green. Only
-- trustworthy when a real putt was recorded — on putt-less holes Garmin snaps the
-- approach's end onto the pin, producing a false 0 ft (legacy parser guard).
CREATE OR REPLACE VIEW derived.hole_first_putt AS
WITH green_reach AS (
  SELECT s.round_id, s.hole_number, min(s.shot_order) AS reach_order
  FROM canon.shot s
  JOIN derived.shot_flags f USING (shot_id)
  WHERE s.end_lie = 'Green' AND NOT f.phantom
  GROUP BY s.round_id, s.hole_number
), has_putt AS (
  SELECT DISTINCT s.round_id, s.hole_number
  FROM canon.shot s
  JOIN derived.shot_flags f USING (shot_id)
  WHERE s.shot_type = 'PUTT' AND NOT f.phantom
)
SELECT gr.round_id, gr.hole_number,
       round(g.remaining_yds * 3.0, 1) AS first_putt_ft
FROM green_reach gr
JOIN has_putt hp ON hp.round_id = gr.round_id AND hp.hole_number = gr.hole_number
JOIN canon.shot s ON s.round_id = gr.round_id AND s.hole_number = gr.hole_number
                 AND s.shot_order = gr.reach_order
JOIN derived.shot_geom g ON g.shot_id = s.shot_id
WHERE g.remaining_yds IS NOT NULL;

-- Per-hole facts + standard interpretations (GIR, scrambling, doubles).
CREATE OR REPLACE VIEW derived.hole_facts AS
SELECT h.round_id, h.hole_number, h.par, h.stroke_index, h.strokes, h.putts,
       h.penalties, h.fairway_outcome, h.handicap_score,
       r.round_date, r.holes_completed,
       h.strokes - h.par                                             AS score_to_par,
       coalesce(CASE WHEN h.strokes IS NOT NULL AND h.putts IS NOT NULL AND h.par IS NOT NULL
                     THEN (h.strokes - h.putts) <= (h.par - 2)
                END, h.gir_observed)                                 AS gir,
       CASE WHEN h.strokes IS NOT NULL AND h.putts IS NOT NULL AND h.par IS NOT NULL
            THEN (h.strokes - h.putts) > (h.par - 2)
       END                                                           AS scramble_opportunity,
       CASE WHEN h.strokes IS NOT NULL AND h.putts IS NOT NULL AND h.par IS NOT NULL
            THEN (h.strokes - h.putts) > (h.par - 2) AND h.strokes <= h.par
       END                                                           AS scramble_save,
       CASE WHEN h.strokes IS NOT NULL AND h.par IS NOT NULL
            THEN h.strokes - h.par >= 2
       END                                                           AS double_plus,
       fp.first_putt_ft
FROM canon.hole h
JOIN canon.round r USING (round_id)
LEFT JOIN derived.hole_first_putt fp
  ON fp.round_id = h.round_id AND fp.hole_number = h.hole_number;

-- Fine putting bands (vNext: 0-3 cleanup / 3-6 short / 6-10 scoring / 10-20 make-or-
-- speed / 20-40 lag / 40+ long lag). First-putt distance is GPS-derived — the shortest
-- band is the least reliable.
CREATE OR REPLACE VIEW derived.putting_bands AS
SELECT round_id, hole_number, round_date, putts, first_putt_ft,
       CASE WHEN first_putt_ft < 3 THEN '0-3'
            WHEN first_putt_ft < 6 THEN '3-6'
            WHEN first_putt_ft < 10 THEN '6-10'
            WHEN first_putt_ft < 20 THEN '10-20'
            WHEN first_putt_ft < 40 THEN '20-40'
            ELSE '40+'
       END                                                           AS band,
       putts = 1                                                     AS made_first
FROM derived.hole_facts
WHERE putts >= 1 AND first_putt_ft IS NOT NULL;
