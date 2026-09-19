-- Approach-play primitives. Views only: no tables, no thresholds, nothing tunable —
-- every cut (zone radius, rings, bin edges, leave classes, window) is applied in Python
-- from config/analysis.json, so one definition serves every consumer.

-- derived.shot_play — one row per real stroke in play (non-phantom, not Garmin-excluded,
-- not a green putt) with its approach geometry, its hole context, and what came next.
-- The shared per-stroke primitive: the Approach Ladder bins it; a future shot-sequence
-- read walks it. It conceptually supersedes benchmarks._REAL_SHOT — the future
-- consolidation point, deliberately not refactored here.
CREATE OR REPLACE VIEW derived.shot_play AS
WITH real_stroke AS (
  -- Every real stroke, PUTTS INCLUDED, purely so "what came next" can see a putt: the
  -- putter-next diagnostic keys on club because Garmin sets shot_type='PUTT' only from
  -- the green, so a fringe putt reads as a chip. Without the putts in this sequence the
  -- next club after an approach that found the green would always be unknown.
  SELECT s.shot_id, s.round_id, s.hole_number, s.shot_order, s.shot_type,
         s.club_id, s.club_type_id, s.start_lie, s.end_lie,
         g.yards, g.to_pin_before_yds, g.remaining_yds,
         g.miss_range, g.miss_side, g.lateral_yds,
         lead(s.club_type_id) OVER (PARTITION BY s.round_id, s.hole_number
                                    ORDER BY s.shot_order) AS next_club_type_id,
         lead(s.shot_type)    OVER (PARTITION BY s.round_id, s.hole_number
                                    ORDER BY s.shot_order) AS next_shot_type
  FROM canon.shot s
  JOIN derived.shot_geom  g USING (shot_id)
  JOIN derived.shot_flags f USING (shot_id)
  WHERE NOT f.phantom AND s.exclude_from_stats IS NOT TRUE
), in_play AS (
  -- The rows themselves are the strokes in play: green putts are their own game.
  SELECT rs.*,
         row_number() OVER (PARTITION BY rs.round_id, rs.hole_number
                            ORDER BY rs.shot_order)                  AS play_order,
         count(*)     OVER (PARTITION BY rs.round_id, rs.hole_number) AS hole_shot_count
  FROM real_stroke rs
  WHERE rs.shot_type <> 'PUTT'
)
SELECT q.shot_id, q.round_id, r.round_date, r.holes_completed, r.course_global_id,
       q.hole_number, h.par, q.play_order, q.hole_shot_count,
       q.club_id, q.club_type_id, coalesce(c.name, ct.name) AS club_name,
       q.start_lie, q.end_lie,
       q.to_pin_before_yds AS to_pin_yds, q.remaining_yds AS leave_yds,
       q.miss_range, q.miss_side, q.lateral_yds,
       q.next_club_type_id, q.next_shot_type,
       h.strokes AS hole_strokes, h.putts AS hole_putts,
       -- Strokes to finish comes from the AUTHORITATIVE score minus the stroke's ordinal
       -- (extends ADR #3): the shot layer under-records tap-ins and penalties by design,
       -- so counting the remaining shot rows would flatter every leave class.
       h.strokes - q.play_order AS strokes_to_finish,
       (h.putts = 0 AND q.play_order = q.hole_shot_count
                    AND h.strokes - q.play_order = 0) AS holed,
       (h.pin_lat IS NOT NULL AND h.pin_lon IS NOT NULL) AS has_pin
FROM in_play q
JOIN canon.hole  h ON h.round_id = q.round_id AND h.hole_number = q.hole_number
JOIN canon.round r ON r.round_id = q.round_id
LEFT JOIN canon.club      c  ON c.club_id      = q.club_id
LEFT JOIN canon.club_type ct ON ct.club_type_id = q.club_type_id;

-- derived.hole_pin_coverage — pin-coordinate availability per hole. Pin-less holes carry
-- no shot data at all, so they contribute no approaches; this view makes the missing
-- denominator visible instead of silently shrinking it.
CREATE OR REPLACE VIEW derived.hole_pin_coverage AS
SELECT h.round_id, r.round_date, h.hole_number, h.par,
       (h.pin_lat IS NOT NULL AND h.pin_lon IS NOT NULL) AS has_pin
FROM canon.hole h JOIN canon.round r USING (round_id);
