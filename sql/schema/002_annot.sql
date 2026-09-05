-- annot: human/LLM context — first-class raw-layer input, loaded from committed files
-- under data/annotations/ (the files are truth; these tables are fully reloaded each
-- ingest). Context NEVER overwrites facts or SG; it changes which shots feed which
-- derived metrics (e.g. exclude_from_stock keeps a recovery punch out of club stats).

CREATE SCHEMA IF NOT EXISTS annot;

CREATE TABLE IF NOT EXISTS annot.round_narrative (
  round_id BIGINT PRIMARY KEY,
  narrative TEXT NOT NULL,              -- the freeform post-round writeup, verbatim
  source_path TEXT,
  written_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS annot.shot_context (
  round_id BIGINT NOT NULL,
  shot_id BIGINT,                       -- NULL when the note couldn't be matched to a shot
  hole_number INTEGER,                  -- locator; required when shot_id IS NULL
  intent TEXT NOT NULL,                 -- normal|recovery|punch|layup|safety|forced_carry|other
  lie_quality TEXT,                     -- tight|perched|sitting_down|divot|... (optional)
  evaluation TEXT,                      -- recovery_success|recovery_fail|
                                        -- good_decision_bad_execution|bad_decision_good_outcome|...
  exclude_from_stock BOOLEAN NOT NULL DEFAULT FALSE,
  match_status TEXT NOT NULL,           -- confirmed | unmatched
  note TEXT
);

CREATE TABLE IF NOT EXISTS annot.hole_context (
  round_id BIGINT NOT NULL,
  hole_number INTEGER NOT NULL,
  post_tee_state TEXT,                  -- clean|compromised|recovery  (par 4/5 only)
  double_class TEXT,                    -- normal_execution|compounded|penalty_driven|
                                        -- short_game_driven|putting_driven|other
  preventable_escalation BOOLEAN,
  note TEXT,
  PRIMARY KEY (round_id, hole_number)
);

CREATE TABLE IF NOT EXISTS annot.annotation_meta (
  round_id BIGINT PRIMARY KEY,
  tags_path TEXT,
  tag_schema_version INTEGER,
  confirmed_at TIMESTAMP
);
