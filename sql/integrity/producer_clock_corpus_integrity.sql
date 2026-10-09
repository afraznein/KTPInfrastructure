-- ENGINE: mysql (hlstatsx on the data server -- NOT the Supabase editor)
-- Producer-clock integrity across the FOUR streams sql/integrity/position_corpus_integrity.sql
-- names and does not measure, plus the position table itself so the five are
-- comparable in one reading.
--
-- RUN AS:
--     sudo mysql --table hlstatsx < sql/integrity/producer_clock_corpus_integrity.sql
--
-- Read-only. No temporary table, no lock a reader does not already take.
--
-- RUN IT AS root, for the reason the position file gives: information_schema
-- omits a table the asking account cannot see, so an ungranted ktp_matches reads
-- ABSENT rather than DENIED and every sample would score as an orphan. Section B
-- halts on that instead of reporting it as a finding.
--
-- No comment in this file contains a semicolon. A naive statement splitter that
-- cuts on semicolon-newline would otherwise sever a statement at a prose
-- semicolon, and the symptom is a syntax error attributed to the SQL.
--
--
-- ============================================================================
-- WHY THIS FILE EXISTS
-- ============================================================================
--
-- The position file closes with: "THE DEFECT IS UNREACHABLE, NOT REMOVED. The
-- `// 0` default is still in the INSERT ... Four other streams share the same
-- expression -- ktp_shot_events, ktp_move_census, ktp_aim_vis and
-- ktp_flag_state_events -- and this file does not measure them."
--
-- Nothing measures them. Both defects are defined per-table with no cross-table
-- part, so extending the definition is a copy, not a new design. The definitions
-- below are the position file's, unchanged.
--
-- DEFECT A, epoch-zero timestamp: event_time < @epoch_floor, a one-year FLOOR
--     and not an equality. FROM_UNIXTIME(0) is evaluated in the SESSION zone at
--     insert time, so on this America/New_York box it renders
--     1969-12-31 19:00:00. An equality against the 1970 literal returns a clean
--     zero over a populated table. Denominator: every row.
--
-- DEFECT B, orphan match id, at two grains: B1 no ktp_matches row for the id at
--     all, B2 a row for the id but none for (match_id, half), which is
--     ktp_matches' own unique grain and the grain every per-half join uses.
--     Denominator: rows whose match_id is non-NULL and non-empty.
--
-- A NULL match_id IS NOT A DEFECT on the three tables whose column is nullable.
-- It is reported, labelled not_a_defect, so nobody re-derives the withdrawn
-- 2026-10-05 null-or-zero figure by accident.
--
--
-- ============================================================================
-- THE FIVE STREAMS, AND THE ONE THAT IS NOT GATED
-- ============================================================================
--
-- Measured on KTPHLStatsX origin/main at 11f608c5, scripts/hlstats.pl. Five
-- INSERT sites derive a stored DATETIME from the epoch-zero default:
--
--   line 7056  flushPositionEvents queue   ktp_position_samples
--   line 7215  flushShotEvents queue       ktp_shot_events
--   line 7446  doEvent_KTPMove             ktp_move_census
--   line 7605  doEvent_KTPAimVis           ktp_aim_vis
--   line 7788  doEvent_KTPFlagState        ktp_flag_state_events
--
-- FOUR of the five are gated the same way, and the gate is airtight by
-- construction rather than by a second check. ktpCaptureContextKey refuses a
-- matchid that does not match /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/, so a handler
-- that reached its manifest check at all holds an explicit producer matchid --
-- which makes ktpHasExplicitProducerContext true, runs
-- ktpResolveValidatedProducerEventContext, and returns on a clock error.
-- ktpValidateProducerEventClock refuses zero with /^[1-9]\d{0,18}$/. The legacy
-- `elsif` branch below each of those four is unreachable on origin/main.
--
-- ktp_flag_state_events IS THE EXCEPTION AND ITS WRITER IS STILL OPEN.
-- doEvent_KTPFlagState has no manifest gate of any kind -- flag_state is not
-- even in ktpCaptureManifestAuthorizes' permitted event_type list, and the
-- dispatch site at line 4696 carries no authorisation call, unlike position,
-- shot, move, aim_vis, team_membership, objective_attempt and grenade_entity.
-- And on a clock error it calls ktpWarnProducerClock and FALLS THROUGH to the
-- receipt-time $g_ktpMatchContext branch rather than returning, so the row is
-- written with event_time = FROM_UNIXTIME(0) and a match_id taken from daemon
-- memory with no proof a ktp_matches row exists. Both defects, from today's
-- code, with a warning in the log and the row stored anyway.
--
-- So section C's flag_state watermarks answer a question the other four rows do
-- not: whether the stream is accruing NOW. For the other four, a non-zero count
-- is a historical population bounded by 2026-08-22 and 2026-08-30. Stated as an
-- inference from the writer history, which is what the watermarks test.
--
--
-- ============================================================================
-- event_time IS NOT UTC, AND NOTHING HERE CHANGES THAT
-- ============================================================================
--
-- event_time on all five tables is FROM_UNIXTIME(producer epoch) rendered in the
-- MySQL session zone, which is SYSTEM on an America/New_York host. created_at is
-- a TIMESTAMP, stored UTC and displayed in that same session zone. So a window
-- expressed in UTC against event_time is off by the Eastern offset, and the
-- offset is not constant across a DST boundary.
--
-- Several checked-in readers already window on these columns -- among them
-- scripts/mmr/momentum_fetch.py over ktp_flag_state_events,
-- sql/analytics/capture_credit_timeline_fact.sql, player_half_fact.sql and
-- player_match_fact.sql. They read event_time against other columns from the
-- same clock, so they are self-consistent. Re-stamping any of these columns
-- would move all of them at once, and that is a decision for whoever owns those
-- readers, not a repair this file authorises.
--
-- The one-year floor is deliberately immune to the whole question: no offset of
-- any size moves a real 2026 sample below 1971, and no offset lifts
-- FROM_UNIXTIME(0) above it. That is the second reason it is a floor.
--
--
-- ============================================================================
-- SCOPE, AND THE REPEAT READING
-- ============================================================================
--
-- Each stream has its OWN id space, so there is one watermark variable per
-- stream rather than one shared @since_id. All five default to 0.
--
--     # whole corpus -- the baseline reading
--     sudo mysql --table hlstatsx < sql/integrity/producer_clock_corpus_integrity.sql
--
--     # only rows above the last reading -- is each source STOPPED?
--     sudo mysql --table hlstatsx --init-command="SET \
--         @since_position := 0, @since_shot := 0, @since_move := 0, \
--         @since_aim := 0, @since_flag := 0" \
--       < sql/integrity/producer_clock_corpus_integrity.sql
--
-- A defect count of 0 above a watermark is the only evidence a producer has
-- stopped emitting. A falling PERCENTAGE is not that evidence, which is why no
-- percentage appears in this file either -- see the position file's own block on
-- the two readings that disagreed because the denominator doubled.
--
--
-- ============================================================================
-- COST
-- ============================================================================
--
-- Section C is a COUNT(*) plus a range scan on each table's idx_event_time.
-- Sections D1, D2 and F scan each table once. Run it off a match night, and use
-- the watermarks for repeat readings.


-- ============================================================================
-- SECTION A  ENVIRONMENT AND REPRESENTATION -- read before any number below
-- ============================================================================

SET SESSION max_execution_time = 900000;
SET @since_position := IFNULL(@since_position, 0);
SET @since_shot     := IFNULL(@since_shot,     0);
SET @since_move     := IFNULL(@since_move,     0);
SET @since_aim      := IFNULL(@since_aim,      0);
SET @since_flag     := IFNULL(@since_flag,     0);
SET @epoch_floor    := '1971-01-01 00:00:00';

SELECT
    DATABASE()              AS db,
    @@session.time_zone     AS session_time_zone,
    @@global.time_zone      AS global_time_zone,
    NOW()                   AS db_now,
    FROM_UNIXTIME(0)        AS from_unixtime_zero_renders_as,
    @epoch_floor            AS epoch_floor_in_use,
    CONCAT_WS(' ', @since_position, @since_shot, @since_move, @since_aim,
                   @since_flag) AS scoped_above_ids_pos_shot_move_aim_flag;


-- ============================================================================
-- SECTION B  PREFLIGHT -- halt rather than report a confident wrong number
-- ============================================================================

SET @missing := (
    SELECT GROUP_CONCAT(CONCAT(w.tbl, '.', w.col) ORDER BY w.tbl, w.col)
    FROM (
        SELECT 'ktp_position_samples'  AS tbl, 'id'          AS col
        UNION ALL SELECT 'ktp_position_samples',  'match_id'
        UNION ALL SELECT 'ktp_position_samples',  'half'
        UNION ALL SELECT 'ktp_position_samples',  'event_time'
        UNION ALL SELECT 'ktp_position_samples',  'event_epoch'
        UNION ALL SELECT 'ktp_position_samples',  'created_at'
        UNION ALL SELECT 'ktp_shot_events',       'id'
        UNION ALL SELECT 'ktp_shot_events',       'match_id'
        UNION ALL SELECT 'ktp_shot_events',       'half'
        UNION ALL SELECT 'ktp_shot_events',       'event_time'
        UNION ALL SELECT 'ktp_shot_events',       'event_epoch'
        UNION ALL SELECT 'ktp_shot_events',       'created_at'
        UNION ALL SELECT 'ktp_move_census',       'id'
        UNION ALL SELECT 'ktp_move_census',       'match_id'
        UNION ALL SELECT 'ktp_move_census',       'half'
        UNION ALL SELECT 'ktp_move_census',       'event_time'
        UNION ALL SELECT 'ktp_move_census',       'event_epoch'
        UNION ALL SELECT 'ktp_move_census',       'created_at'
        UNION ALL SELECT 'ktp_aim_vis',           'id'
        UNION ALL SELECT 'ktp_aim_vis',           'match_id'
        UNION ALL SELECT 'ktp_aim_vis',           'half'
        UNION ALL SELECT 'ktp_aim_vis',           'event_time'
        UNION ALL SELECT 'ktp_aim_vis',           'event_epoch'
        UNION ALL SELECT 'ktp_aim_vis',           'created_at'
        UNION ALL SELECT 'ktp_flag_state_events', 'id'
        UNION ALL SELECT 'ktp_flag_state_events', 'match_id'
        UNION ALL SELECT 'ktp_flag_state_events', 'half'
        UNION ALL SELECT 'ktp_flag_state_events', 'event_time'
        UNION ALL SELECT 'ktp_flag_state_events', 'event_epoch'
        UNION ALL SELECT 'ktp_flag_state_events', 'created_at'
    ) w
    WHERE NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS c
        WHERE c.TABLE_SCHEMA = DATABASE()
          AND c.TABLE_NAME = w.tbl
          AND c.COLUMN_NAME = w.col));
-- Printed BEFORE the halt, deliberately. mysql stops at the sentinel, so a
-- SELECT placed after it would never run and the reader would get a table name
-- in an error message with no list of which columns were missing. A clean run
-- prints `none`, which also records that the shape was checked.
SELECT IFNULL(@missing, 'none') AS missing_stream_columns;

SET @ddl := IF(@missing IS NULL, 'DO 0',
    'SELECT * FROM ERROR_B1_a_required_stream_column_is_missing_see_the_row_above');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl := IF((SELECT COUNT(*) FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ktp_matches') = 1,
    'DO 0',
    'SELECT * FROM ERROR_B2_ktp_matches_invisible_to_this_account_every_row_would_read_orphan');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;


-- ============================================================================
-- SECTION C  DEFECT A AND THE TIME-FILTER GAP, ONE ROW PER STREAM
--     Read gap_time_filter_loses first. It is the finding. The columns to its
--     right are how the finding is explained.
-- ============================================================================

          SELECT 'ktp_position_samples' AS stream,
                 COUNT(*)                                                  AS rows_a_bare_count_sees,
                 COUNT(*) - SUM(event_time < @epoch_floor)                 AS rows_a_time_filter_sees,
                 SUM(event_time < @epoch_floor)                            AS gap_time_filter_loses,
                 MAX(IF(event_time < @epoch_floor, id, NULL))              AS epoch_zero_max_id,
                 MIN(IF(event_time < @epoch_floor, created_at, NULL))      AS epoch_zero_first_inserted_at,
                 MAX(IF(event_time < @epoch_floor, created_at, NULL))      AS epoch_zero_last_inserted_at,
                 MAX(id)                                                   AS rows_max_id,
                 MIN(IF(event_time >= @epoch_floor, event_time, NULL))     AS usable_event_time_earliest,
                 MAX(IF(event_time >= @epoch_floor, event_time, NULL))     AS usable_event_time_latest
          FROM ktp_position_samples WHERE id > @since_position
UNION ALL SELECT 'ktp_shot_events',
                 COUNT(*), COUNT(*) - SUM(event_time < @epoch_floor),
                 SUM(event_time < @epoch_floor),
                 MAX(IF(event_time < @epoch_floor, id, NULL)),
                 MIN(IF(event_time < @epoch_floor, created_at, NULL)),
                 MAX(IF(event_time < @epoch_floor, created_at, NULL)),
                 MAX(id),
                 MIN(IF(event_time >= @epoch_floor, event_time, NULL)),
                 MAX(IF(event_time >= @epoch_floor, event_time, NULL))
          FROM ktp_shot_events WHERE id > @since_shot
UNION ALL SELECT 'ktp_move_census',
                 COUNT(*), COUNT(*) - SUM(event_time < @epoch_floor),
                 SUM(event_time < @epoch_floor),
                 MAX(IF(event_time < @epoch_floor, id, NULL)),
                 MIN(IF(event_time < @epoch_floor, created_at, NULL)),
                 MAX(IF(event_time < @epoch_floor, created_at, NULL)),
                 MAX(id),
                 MIN(IF(event_time >= @epoch_floor, event_time, NULL)),
                 MAX(IF(event_time >= @epoch_floor, event_time, NULL))
          FROM ktp_move_census WHERE id > @since_move
UNION ALL SELECT 'ktp_aim_vis',
                 COUNT(*), COUNT(*) - SUM(event_time < @epoch_floor),
                 SUM(event_time < @epoch_floor),
                 MAX(IF(event_time < @epoch_floor, id, NULL)),
                 MIN(IF(event_time < @epoch_floor, created_at, NULL)),
                 MAX(IF(event_time < @epoch_floor, created_at, NULL)),
                 MAX(id),
                 MIN(IF(event_time >= @epoch_floor, event_time, NULL)),
                 MAX(IF(event_time >= @epoch_floor, event_time, NULL))
          FROM ktp_aim_vis WHERE id > @since_aim
UNION ALL SELECT 'ktp_flag_state_events',
                 COUNT(*), COUNT(*) - SUM(event_time < @epoch_floor),
                 SUM(event_time < @epoch_floor),
                 MAX(IF(event_time < @epoch_floor, id, NULL)),
                 MIN(IF(event_time < @epoch_floor, created_at, NULL)),
                 MAX(IF(event_time < @epoch_floor, created_at, NULL)),
                 MAX(id),
                 MIN(IF(event_time >= @epoch_floor, event_time, NULL)),
                 MAX(IF(event_time >= @epoch_floor, event_time, NULL))
          FROM ktp_flag_state_events WHERE id > @since_flag;

-- HOW TO READ SECTION C
--   gap_time_filter_loses = 0
--       No row on that stream is invisible to a time filter.
--   above 0, with epoch_zero_max_id ABOVE the previous reading's rows_max_id
--       The producer is STILL EMITTING on that stream.
--   above 0, with epoch_zero_max_id unchanged
--       A frozen historical population. What remains is the repair-or-exclude
--       disposition for the stored rows.
--   On ktp_flag_state_events, expect the first shape to be the live risk rather
--       than the historical one -- its writer is not gated. See the block above.
--   created_at is DEFAULT CURRENT_TIMESTAMP on all five and is NOT derived from
--       event_epoch, so it survives on a defective row and dates the population.
--       It is a real clock a repair could use instead of a guess. Whether to use
--       it is the operator's call, not this file's.


-- ============================================================================
-- SECTION D1  DEFECT B AND THE MATCH-JOIN GAPS, ONE ROW PER STREAM
--     Grouped at (match_id, half) -- ktp_matches' own unique grain. One row of
--     each inner aggregate is one (match_id, half) AS THE SAMPLES CLAIM IT,
--     which is not the same thing as a match half that exists.
-- ============================================================================

WITH classified AS (
              SELECT 'ktp_position_samples' AS stream, match_id, half, COUNT(*) AS rows_in_pair,
                     MAX(id) AS max_id, MIN(created_at) AS min_created, MAX(created_at) AS max_created
              FROM ktp_position_samples WHERE id > @since_position GROUP BY match_id, half
    UNION ALL SELECT 'ktp_shot_events', match_id, half, COUNT(*),
                     MAX(id), MIN(created_at), MAX(created_at)
              FROM ktp_shot_events WHERE id > @since_shot GROUP BY match_id, half
    UNION ALL SELECT 'ktp_move_census', match_id, half, COUNT(*),
                     MAX(id), MIN(created_at), MAX(created_at)
              FROM ktp_move_census WHERE id > @since_move GROUP BY match_id, half
    UNION ALL SELECT 'ktp_aim_vis', match_id, half, COUNT(*),
                     MAX(id), MIN(created_at), MAX(created_at)
              FROM ktp_aim_vis WHERE id > @since_aim GROUP BY match_id, half
    UNION ALL SELECT 'ktp_flag_state_events', match_id, half, COUNT(*),
                     MAX(id), MIN(created_at), MAX(created_at)
              FROM ktp_flag_state_events WHERE id > @since_flag GROUP BY match_id, half),
judged AS (
    SELECT c.*,
           (c.match_id IS NOT NULL AND c.match_id <> '')              AS has_match_id,
           EXISTS (SELECT 1 FROM ktp_matches m
                   WHERE m.match_id = c.match_id)                     AS match_known,
           EXISTS (SELECT 1 FROM ktp_matches m
                   WHERE m.match_id = c.match_id AND m.half = c.half) AS half_known,
           EXISTS (SELECT 1 FROM ktp_matches m
                   WHERE m.match_id = c.match_id
                     AND BINARY m.match_id = BINARY c.match_id)       AS match_known_bytewise
    FROM classified c)
SELECT stream,
       SUM(IF(has_match_id, rows_in_pair, 0))                                    AS rows_with_a_match_id,
       SUM(IF(has_match_id AND match_known, rows_in_pair, 0))                    AS rows_a_per_match_join_sees,
       SUM(IF(has_match_id AND NOT match_known, rows_in_pair, 0))                AS gap_per_match_join_loses,
       SUM(IF(has_match_id AND match_known AND half_known, rows_in_pair, 0))     AS rows_a_per_half_join_sees,
       SUM(IF(has_match_id AND NOT (match_known AND half_known), rows_in_pair, 0)) AS gap_per_half_join_loses,
       SUM(IF(has_match_id AND NOT match_known, rows_in_pair, 0))                AS b1_orphan_match_rows,
       COUNT(DISTINCT IF(has_match_id AND NOT match_known, match_id, NULL))      AS b1_orphan_match_ids,
       SUM(IF(has_match_id AND match_known AND NOT half_known, rows_in_pair, 0)) AS b2_orphan_half_rows,
       COUNT(DISTINCT IF(has_match_id AND match_known AND NOT half_known,
                         CONCAT(match_id, '#', half), NULL))                     AS b2_orphan_half_pairs,
       COUNT(DISTINCT IF(has_match_id AND match_known AND NOT match_known_bytewise,
                         match_id, NULL))                                        AS case_variant_match_ids
FROM judged
GROUP BY stream
ORDER BY FIELD(stream, 'ktp_position_samples', 'ktp_shot_events', 'ktp_move_census',
                       'ktp_aim_vis', 'ktp_flag_state_events');


-- ============================================================================
-- SECTION D2  ORPHAN WATERMARKS AND THE TWO POPULATIONS THAT ARE NOT DEFECT B
-- ============================================================================

WITH classified AS (
              SELECT 'ktp_position_samples' AS stream, match_id, half, COUNT(*) AS rows_in_pair,
                     MAX(id) AS max_id, MIN(created_at) AS min_created, MAX(created_at) AS max_created
              FROM ktp_position_samples WHERE id > @since_position GROUP BY match_id, half
    UNION ALL SELECT 'ktp_shot_events', match_id, half, COUNT(*),
                     MAX(id), MIN(created_at), MAX(created_at)
              FROM ktp_shot_events WHERE id > @since_shot GROUP BY match_id, half
    UNION ALL SELECT 'ktp_move_census', match_id, half, COUNT(*),
                     MAX(id), MIN(created_at), MAX(created_at)
              FROM ktp_move_census WHERE id > @since_move GROUP BY match_id, half
    UNION ALL SELECT 'ktp_aim_vis', match_id, half, COUNT(*),
                     MAX(id), MIN(created_at), MAX(created_at)
              FROM ktp_aim_vis WHERE id > @since_aim GROUP BY match_id, half
    UNION ALL SELECT 'ktp_flag_state_events', match_id, half, COUNT(*),
                     MAX(id), MIN(created_at), MAX(created_at)
              FROM ktp_flag_state_events WHERE id > @since_flag GROUP BY match_id, half),
judged AS (
    SELECT c.*,
           (c.match_id IS NOT NULL AND c.match_id <> '')              AS has_match_id,
           EXISTS (SELECT 1 FROM ktp_matches m
                   WHERE m.match_id = c.match_id)                     AS match_known,
           EXISTS (SELECT 1 FROM ktp_matches m
                   WHERE m.match_id = c.match_id AND m.half = c.half) AS half_known
    FROM classified c)
SELECT stream,
       MAX(IF(has_match_id AND NOT (match_known AND half_known), max_id, NULL))      AS orphan_max_id,
       MIN(IF(has_match_id AND NOT (match_known AND half_known), min_created, NULL)) AS orphan_first_inserted_at,
       MAX(IF(has_match_id AND NOT (match_known AND half_known), max_created, NULL)) AS orphan_last_inserted_at,
       SUM(IF(match_id IS NULL, rows_in_pair, 0))                                    AS not_a_defect_rows_match_id_null,
       SUM(IF(match_id IS NOT NULL AND match_id = '', rows_in_pair, 0))              AS b3_rows_match_id_empty_string,
       SUM(rows_in_pair)                                                             AS reconcile_total_must_equal_section_c
FROM judged
GROUP BY stream
ORDER BY FIELD(stream, 'ktp_position_samples', 'ktp_shot_events', 'ktp_move_census',
                       'ktp_aim_vis', 'ktp_flag_state_events');

-- HOW TO READ SECTIONS D1 AND D2
--   RECONCILE BEFORE BELIEVING EITHER. reconcile_total_must_equal_section_c must
--   equal that stream's rows_a_bare_count_sees. The two are counted by different
--   statements at different grains, so a disagreement is a defect in this file or
--   a concurrent insert between the statements -- not a finding about the data.
--   not_a_defect_rows_match_id_null must be 0 on ktp_aim_vis and
--   ktp_flag_state_events, whose match_id columns are NOT NULL. A non-zero there
--   means the live DDL is not what this file assumes, and section E repeats it as
--   a structural control.
--   b3_rows_match_id_empty_string above 0 IS a defect, and a different one. The
--   daemon writes the SQL literal NULL for an untagged sample, so an empty string
--   can only arrive from a producer that sent a blank matchid. It points at the
--   producer, not at a missing ktp_matches row, and it must not be swept into the
--   untagged population where nobody looks.
--   case_variant_match_ids above 0 means BINARY and non-BINARY readers of one
--   corpus return different populations. Migration 013 put these tables on
--   utf8mb4_unicode_ci, and the checked-in readers disagree -- two force BINARY,
--   two do not. Fix the ids or make every reader agree. Do not pick whichever
--   answer is smaller.
--   An orphan can also be created RETROACTIVELY by deleting a ktp_matches row, so
--   a rising orphan_max_id is not by itself proof that a producer regressed.
--   scripts/ktp-match-retention.py is not a candidate: it deletes the sample rows
--   before ktp_matches inside one transaction, and both tables are InnoDB.


-- ============================================================================
-- SECTION E  CONTROLS -- a zero above means nothing until these read as stated
-- ============================================================================

          SELECT 'ctl_rows_must_be_nonzero' AS control, 'ktp_position_samples' AS stream,
                 CAST((SELECT COUNT(*) FROM ktp_position_samples) AS CHAR) AS value,
                 'if 0, every count above is about an empty table' AS reading
UNION ALL SELECT 'ctl_rows_must_be_nonzero', 'ktp_shot_events',
                 CAST((SELECT COUNT(*) FROM ktp_shot_events) AS CHAR), 'same'
UNION ALL SELECT 'ctl_rows_must_be_nonzero', 'ktp_move_census',
                 CAST((SELECT COUNT(*) FROM ktp_move_census) AS CHAR), 'same'
UNION ALL SELECT 'ctl_rows_must_be_nonzero', 'ktp_aim_vis',
                 CAST((SELECT COUNT(*) FROM ktp_aim_vis) AS CHAR), 'same'
UNION ALL SELECT 'ctl_rows_must_be_nonzero', 'ktp_flag_state_events',
                 CAST((SELECT COUNT(*) FROM ktp_flag_state_events) AS CHAR), 'same'
UNION ALL SELECT 'ctl_match_rows_must_be_nonzero', 'ktp_matches',
                 CAST((SELECT COUNT(*) FROM ktp_matches) AS CHAR),
                 'if 0, every row is an orphan for a reason that is not a data defect'
UNION ALL SELECT 'ctl_sane_window_must_be_nonzero', 'ktp_flag_state_events',
                 CAST((SELECT COUNT(*) FROM ktp_flag_state_events
                       WHERE event_time >= '2026-01-01' AND event_time <= NOW()) AS CHAR),
                 'positive control for the time predicate itself'
UNION ALL SELECT 'ctl_impossible_future_must_be_zero', 'ktp_flag_state_events',
                 CAST((SELECT COUNT(*) FROM ktp_flag_state_events
                       WHERE event_time > '2090-01-01') AS CHAR),
                 'negative control, a predicate that cannot match'
UNION ALL SELECT 'ctl_nonsense_match_id_must_be_zero', 'ktp_flag_state_events',
                 CAST((SELECT COUNT(*) FROM ktp_flag_state_events
                       WHERE match_id = 'zzz-no-such-match-zzz') AS CHAR),
                 'second negative control, on the match_id predicate'
UNION ALL SELECT 'ctl_aim_vis_match_id_nulls_must_be_zero', 'ktp_aim_vis',
                 CAST((SELECT COUNT(*) FROM ktp_aim_vis WHERE match_id IS NULL) AS CHAR),
                 'structural control: the column is NOT NULL in migration 042'
UNION ALL SELECT 'ctl_flag_state_match_id_nulls_must_be_zero', 'ktp_flag_state_events',
                 CAST((SELECT COUNT(*) FROM ktp_flag_state_events WHERE match_id IS NULL) AS CHAR),
                 'structural control: the column is NOT NULL in migration 015';


-- ============================================================================
-- SECTION F  WHAT AN EPOCH-ZERO ROW ACTUALLY STORES ON THIS HOST, PER STREAM
--     Print it. Do not carry a remembered literal into the next query.
-- ============================================================================

          SELECT 'ktp_position_samples' AS stream, event_time AS stored_literal, COUNT(*) AS rows_with_it,
                 MIN(event_epoch) AS min_event_epoch, MAX(event_epoch) AS max_event_epoch,
                 MIN(created_at) AS first_inserted_at, MAX(created_at) AS last_inserted_at
          FROM ktp_position_samples
          WHERE event_time < @epoch_floor AND id > @since_position GROUP BY event_time
UNION ALL SELECT 'ktp_shot_events', event_time, COUNT(*),
                 MIN(event_epoch), MAX(event_epoch), MIN(created_at), MAX(created_at)
          FROM ktp_shot_events
          WHERE event_time < @epoch_floor AND id > @since_shot GROUP BY event_time
UNION ALL SELECT 'ktp_move_census', event_time, COUNT(*),
                 MIN(event_epoch), MAX(event_epoch), MIN(created_at), MAX(created_at)
          FROM ktp_move_census
          WHERE event_time < @epoch_floor AND id > @since_move GROUP BY event_time
UNION ALL SELECT 'ktp_aim_vis', event_time, COUNT(*),
                 MIN(event_epoch), MAX(event_epoch), MIN(created_at), MAX(created_at)
          FROM ktp_aim_vis
          WHERE event_time < @epoch_floor AND id > @since_aim GROUP BY event_time
UNION ALL SELECT 'ktp_flag_state_events', event_time, COUNT(*),
                 MIN(event_epoch), MAX(event_epoch), MIN(created_at), MAX(created_at)
          FROM ktp_flag_state_events
          WHERE event_time < @epoch_floor AND id > @since_flag GROUP BY event_time
ORDER BY stream, rows_with_it DESC
LIMIT 60;


-- ============================================================================
-- SECTION G  THE SIXTH SITE -- ktp_flag_positions, WHICH STORES NO DERIVED TIME
--     doEvent_KTPFlagPosition carries the same `// 0` at hlstats.pl 7718 and
--     7728, but into last_event_epoch, an integer column, with no
--     FROM_UNIXTIME beside it. So it cannot produce defect A, and the table is
--     an upsert of one row per flag rather than an event stream. A zero there is
--     still a corrupt clock marker on a durable row, and it is cheap to read.
-- ============================================================================

SELECT COUNT(*)                                            AS flag_position_rows,
       SUM(last_event_epoch = 0)                           AS last_event_epoch_zero,
       SUM(last_event_epoch IS NULL)                        AS last_event_epoch_null_pre_021,
       SUM(last_match_id IS NOT NULL AND last_match_id <> ''
           AND NOT EXISTS (SELECT 1 FROM ktp_matches m
                           WHERE m.match_id = last_match_id)) AS last_match_id_orphan,
       MAX(updated_at)                                     AS newest_upsert
FROM ktp_flag_positions;

-- HOW TO READ SECTION G
--   last_event_epoch_null_pre_021 is not a defect -- migration 021 added the
--   column, so NULL is an honest "this row predates it".
--   last_event_epoch_zero IS the `// 0` default landing on a durable row. It
--   does not hide anything from a time filter, because nothing derives a
--   DATETIME from it, so it is a provenance defect rather than a counting one.
--   If updated_at does not exist on this table the statement fails loudly rather
--   than silently -- that is deliberate, and section B does not pre-check it
--   because nothing above depends on this section.


-- ============================================================================
-- SECTION H  OPTIONAL CROSS-CHECK -- does event_epoch agree with the floor?
--     A full scan per stream, because event_epoch is unindexed on all five.
--     Nothing above depends on it.
-- ============================================================================

          SELECT 'ktp_position_samples' AS stream,
                 SUM(event_time <  @epoch_floor AND COALESCE(event_epoch = 0, 0))     AS both_markers_agree,
                 SUM(event_time <  @epoch_floor AND NOT COALESCE(event_epoch = 0, 0)) AS near_epoch_time_but_epoch_not_zero,
                 SUM(event_time >= @epoch_floor AND COALESCE(event_epoch = 0, 0))     AS epoch_zero_marker_but_time_looks_fine,
                 SUM(event_time <  @epoch_floor AND event_epoch IS NULL)              AS near_epoch_time_with_null_epoch
          FROM ktp_position_samples WHERE id > @since_position
UNION ALL SELECT 'ktp_shot_events',
                 SUM(event_time <  @epoch_floor AND COALESCE(event_epoch = 0, 0)),
                 SUM(event_time <  @epoch_floor AND NOT COALESCE(event_epoch = 0, 0)),
                 SUM(event_time >= @epoch_floor AND COALESCE(event_epoch = 0, 0)),
                 SUM(event_time <  @epoch_floor AND event_epoch IS NULL)
          FROM ktp_shot_events WHERE id > @since_shot
UNION ALL SELECT 'ktp_move_census',
                 SUM(event_time <  @epoch_floor AND COALESCE(event_epoch = 0, 0)),
                 SUM(event_time <  @epoch_floor AND NOT COALESCE(event_epoch = 0, 0)),
                 SUM(event_time >= @epoch_floor AND COALESCE(event_epoch = 0, 0)),
                 SUM(event_time <  @epoch_floor AND event_epoch IS NULL)
          FROM ktp_move_census WHERE id > @since_move
UNION ALL SELECT 'ktp_aim_vis',
                 SUM(event_time <  @epoch_floor AND COALESCE(event_epoch = 0, 0)),
                 SUM(event_time <  @epoch_floor AND NOT COALESCE(event_epoch = 0, 0)),
                 SUM(event_time >= @epoch_floor AND COALESCE(event_epoch = 0, 0)),
                 SUM(event_time <  @epoch_floor AND event_epoch IS NULL)
          FROM ktp_aim_vis WHERE id > @since_aim
UNION ALL SELECT 'ktp_flag_state_events',
                 SUM(event_time <  @epoch_floor AND COALESCE(event_epoch = 0, 0)),
                 SUM(event_time <  @epoch_floor AND NOT COALESCE(event_epoch = 0, 0)),
                 SUM(event_time >= @epoch_floor AND COALESCE(event_epoch = 0, 0)),
                 SUM(event_time <  @epoch_floor AND event_epoch IS NULL)
          FROM ktp_flag_state_events WHERE id > @since_flag;

-- HOW TO READ SECTION H
--   both_markers_agree should account for the whole of defect A on rows written
--   after migration 021 added event_epoch. Each of the other three columns is a
--   separate surprise. A near-epoch event_time beside a real event_epoch means
--   something other than the `// 0` default produced it. An event_epoch of 0
--   beside a plausible event_time means the two were not written from the same
--   value. A near-epoch event_time with a NULL event_epoch means a row written
--   before 021 is affected, which the writer history does not predict.
--
--
-- ============================================================================
-- WHAT THIS FILE DOES NOT COVER
-- ============================================================================
--
-- The two mechanisms the position file names, because neither is table-scoped
-- and neither is closed by anything here:
--
--   getProperties' value branch has to be `.*?`. With `.+?` the lazy match runs
--   past the closing quote and returns the rest of the log line as the value,
--   minting a match id no ktp_matches row will ever carry, with nothing erroring.
--   That is an orphan of exactly the B1 shape, arriving from the parser rather
--   than from a match-context branch, so a fix to one does not close the other.
--
--   $g_ktpMatchContext has no staleness bound and is never cleared on an
--   OT-decided match, so events after one are tagged to the finished match. That
--   mis-attributes to a match that DOES exist, so it is invisible to both
--   definitions here and to every count in this file.
--
-- And the disposition itself. This file measures. Whether the stored rows are
-- repaired from created_at, excluded by a view, or left in place is the
-- operator's call.
