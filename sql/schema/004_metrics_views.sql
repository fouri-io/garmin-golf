-- Round-level rollups: Strokes Gained per round and the priority metrics that are
-- derivable from Garmin data alone (annotation-dependent metrics arrive with annot
-- loading). progress.py windows these per-round rows into This/L5/L10/L20/All.

-- Per-round SG by bucket. Tee-to-green from per-shot grades; putting is count-based:
-- expected putts (from first-putt distance) minus authoritative putts. Matches the
-- legacy strokes_gained.compute summary (categories rounded to 2 at read time).
CREATE OR REPLACE VIEW derived.round_sg AS
WITH tee_to_green AS (
  SELECT s.round_id,
         sum(sg.strokes_gained) FILTER (WHERE sg.sg_category = 'offTee')       AS off_tee,
         sum(sg.strokes_gained) FILTER (WHERE sg.sg_category = 'longApproach') AS long_approach,
         sum(sg.strokes_gained) FILTER (WHERE sg.sg_category = 'midApproach')  AS mid_approach,
         sum(sg.strokes_gained) FILTER (WHERE sg.sg_category = 'inside50')     AS inside50,
         sum(sg.strokes_gained) FILTER (WHERE sg.sg_category NOT IN ('offTee', 'putting')
                                          AND g.to_pin_before_yds <= 100)      AS sg_0_100,
         count(sg.strokes_gained)                                              AS categorized_shots
  FROM derived.shot_sg sg
  JOIN canon.shot s USING (shot_id)
  LEFT JOIN derived.shot_geom g USING (shot_id)
  GROUP BY s.round_id
), putting AS (
  SELECT hp.round_id,
         sum(hp.expected_putts - h.putts) AS putting_sg,
         count(*)                         AS putt_holes_measured,
         sum(h.putts)                     AS putts_covered
  FROM derived.hole_putting hp
  JOIN canon.hole h USING (round_id, hole_number)
  GROUP BY hp.round_id
)
SELECT r.round_id, r.round_date,
       coalesce(t.off_tee, 0)        AS sg_off_tee,
       coalesce(t.long_approach, 0)  AS sg_long_approach,
       coalesce(t.mid_approach, 0)   AS sg_mid_approach,
       coalesce(t.inside50, 0)       AS sg_inside50,
       coalesce(p.putting_sg, 0)     AS sg_putting,
       coalesce(t.sg_0_100, 0)       AS sg_0_100,
       coalesce(t.categorized_shots, 0)    AS categorized_shots,
       coalesce(p.putt_holes_measured, 0)  AS putt_holes_measured,
       coalesce(p.putts_covered, 0)        AS putts_covered
FROM canon.round r
LEFT JOIN tee_to_green t ON t.round_id = r.round_id
LEFT JOIN putting p ON p.round_id = r.round_id;

-- Per-round priority metrics (Garmin-derivable subset). Rates are computed at the
-- window level in progress.py from these counts, never averaged from per-round rates.
CREATE OR REPLACE VIEW derived.round_metrics AS
WITH holes AS (
  SELECT round_id,
         count(*)                                          AS holes_played,
         count(*) FILTER (WHERE double_plus)               AS doubles_plus,
         count(*) FILTER (WHERE scramble_opportunity)      AS scramble_opps,
         count(*) FILTER (WHERE scramble_save)             AS scramble_saves,
         count(*) FILTER (WHERE putts >= 3)                AS three_putt_holes
  FROM derived.hole_facts
  GROUP BY round_id
), bands AS (
  SELECT round_id,
         count(*) FILTER (WHERE band = '3-6')                    AS putts_3_6,
         count(*) FILTER (WHERE band = '3-6' AND made_first)     AS makes_3_6,
         count(*) FILTER (WHERE band = '6-10')                   AS putts_6_10,
         count(*) FILTER (WHERE band = '6-10' AND made_first)    AS makes_6_10,
         count(*) FILTER (WHERE band IN ('20-40', '40+'))        AS putts_30plus_ish,
         count(*) FILTER (WHERE band IN ('20-40', '40+') AND putts >= 3) AS three_putts_long
  FROM derived.putting_bands
  GROUP BY round_id
)
SELECT r.round_id, r.round_date,
       coalesce(r.holes_completed, h.holes_played) AS holes,
       r.total_strokes, r.total_putts, r.total_penalties,
       r.tee_rating, r.tee_slope,
       h.doubles_plus, h.scramble_opps, h.scramble_saves, h.three_putt_holes,
       coalesce(b.putts_3_6, 0)   AS putts_3_6,
       coalesce(b.makes_3_6, 0)   AS makes_3_6,
       coalesce(b.putts_6_10, 0)  AS putts_6_10,
       coalesce(b.makes_6_10, 0)  AS makes_6_10,
       coalesce(b.putts_30plus_ish, 0)  AS long_first_putts,
       coalesce(b.three_putts_long, 0)  AS long_three_putts
FROM canon.round r
JOIN holes h USING (round_id)
LEFT JOIN bands b USING (round_id);
