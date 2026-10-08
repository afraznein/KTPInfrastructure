-- ENGINE: mysql (hlstatsx on the data server -- NOT the Supabase editor)
-- Position-corpus integrity: the epoch-zero timestamp and the orphan match id,
-- each pinned to ONE definition so two readings are comparable.
--
-- RUN AS:
--     sudo mysql --table hlstatsx < sql/integrity/position_corpus_integrity.sql
--
-- Read-only. It creates no temporary table, so it needs only SELECT, writes
-- nothing, and takes no lock a reader does not already take.
--
-- RUN IT AS root. A service account that lacks SELECT on ktp_matches does not
-- get an error here -- information_schema omits a table the asking account
-- cannot see, so the table reads ABSENT rather than DENIED and every sample
-- would score as an orphan. Section B halts on that rather than reporting it as
-- a finding.
--
-- SCOPE, AND THE CHEAP REPEAT READING. Every section honours @since_id, so one
-- file answers two different questions.
--
--     # whole corpus -- the baseline reading
--     sudo mysql --table hlstatsx < sql/integrity/position_corpus_integrity.sql
--
--     # only rows that arrived since the last reading -- is the source STOPPED?
--     sudo mysql --table hlstatsx \
--       --init-command="SET @since_id := <previous rows_max_id>" \
--       < sql/integrity/position_corpus_integrity.sql
--
-- The scoped form is the one that answers accrual, and it is cheap. A defect
-- count of 0 above a watermark is the only evidence a producer has stopped
-- emitting. A falling PERCENTAGE is not that evidence -- see the next block.
--
-- No comment in this file contains a semicolon. A naive statement splitter --
-- KTPAntiCheat's tier-2 fixture has one, cutting on semicolon-newline -- would
-- otherwise sever a statement at a prose semicolon, and the symptom is a syntax
-- error attributed to the SQL rather than to the comment.
--
--
-- ============================================================================
-- WHY NO PERCENTAGE APPEARS ANYWHERE IN THIS FILE
-- ============================================================================
--
-- This corpus has been read twice and the two figures disagreed: 14.3% / 3.1%
-- on 2026-09-14, then 6.2% / 1.4% on 2026-10-05. Against the row totals quoted
-- on those same two days -- 2.29M and 5,304,528 -- the absolute epoch-zero
-- counts work out at roughly 327k and 329k, within half a percent of each
-- other. Stated as an inference rather than a measurement: the defective
-- population did not shrink, the denominator doubled. A percentage over a
-- growing corpus falls while nothing has been fixed, and it also stops falling
-- while something IS broken.
--
-- So this file reports COUNTS and WATERMARKS. A count is comparable between
-- readings. MAX(id) and MAX(created_at) over the defective population are what
-- say whether the source is still emitting.
--
--
-- ============================================================================
-- DEFECT A -- EPOCH-ZERO TIMESTAMP
-- ============================================================================
--
-- DEFINITION. A row of ktp_position_samples whose
--
--     event_time < @epoch_floor      (@epoch_floor = '1971-01-01 00:00:00')
--
-- DENOMINATOR: every row. A time filter is applied to the whole table, so the
-- whole table is what it can lose from.
--
-- WHY A ONE-YEAR FLOOR AND NOT AN EQUALITY. The value stored is
-- FROM_UNIXTIME(0) evaluated in the SESSION time zone at insert time. MySQL here
-- runs time_zone = SYSTEM on an America/New_York box, so that renders
-- 1969-12-31 19:00:00, not 1970-01-01 00:00:00. An equality against
-- '1970-01-01 00:00:00' therefore returns a clean zero over a populated table,
-- which is the exact shape of wrong answer this card exists to stop. Under a
-- different session zone, or a zero-date or NULL-coerced write, the literal
-- moves again. A floor covers every representation, is sargable on
-- idx_event_time, and cannot reach real data, because the corpus begins when
-- migration 008 created the table on 2026-08-13. Section F prints the literals
-- actually present below the floor, so the next reader learns the
-- representation instead of assuming one.
--
-- THE CORROBORATING MARKER, AND THE TRAP IN IT. event_epoch = 0 marks the same
-- defect for rows written after migration 021 added that column. It is reported
-- in section H as a cross-check, never as the definition.
-- event_epoch IS NULL IS NOT THIS DEFECT. The column did not exist before
-- migration 021, so NULL is an honest "this row predates the column" on every
-- older row, and those rows carry a correct NOW() event_time.
--
--
-- ============================================================================
-- DEFECT B -- ORPHAN MATCH ID
-- ============================================================================
--
-- DEFINITION, at two grains, reported separately because they are two
-- questions. ktp_matches is unique on (match_id, half), so the pair is the real
-- grain.
--
--   B1 orphan_match: match_id is non-NULL and non-empty, and NO row of
--                    ktp_matches carries that match_id at all.
--   B2 orphan_half:  a ktp_matches row exists for the match_id but none for
--                    (match_id, half). A sample for half 2 of a match that only
--                    ever recorded half 1 is invisible to every per-half join
--                    and visible to every per-match count.
--
-- DENOMINATOR: rows whose match_id is non-NULL and non-empty. NOT every row.
--
-- A NULL match_id IS NOT A DEFECT AND MUST NOT BE COUNTED AS ONE. hlstats.pl's
-- doEvent_KTPPosition writes match_id NULL deliberately when the daemon held no
-- live match context -- warmup, between halves, practice -- and leaves half at
-- 0. That population is by design, and every checked-in consumer already
-- excludes it with `half > 0`.
-- The 2026-10-05 re-measure used a "null-or-zero match_id" test, which counts
-- the by-design population as defective. That is why its 1.4% is not comparable
-- to the 2026-09-14 3.1%, and it is the whole reason this file exists.
--
-- AN EMPTY-STRING match_id IS NOT THE SAME THING AS NULL, and it gets its own
-- line rather than being folded into either. The daemon writes the SQL literal
-- NULL for an untagged sample, so '' can only arrive from a producer that sent
-- (matchid "") -- and on origin/main that is refused upstream of the INSERT. A
-- non-zero count there is therefore a finding on its own, not a by-design row,
-- and it must not be swept into the untagged population where nobody looks.
--
-- COLLATION: THE JOIN HAS TWO ANSWERS AND THE CHECKED-IN READERS DISAGREE.
-- Migration 013 put every KTP table on utf8mb4_unicode_ci, so match_id compares
-- case-INsensitively unless BINARY is forced. sql/analytics/position_sample_fact.sql
-- and scripts/canary_evidence.py force BINARY. scripts/flag_ownership_report.py
-- and scripts/match_accumulation.py do not. Section D therefore reports the
-- case-insensitive answer as the definition and counts case-variant ids
-- separately. A non-zero case_variant_match_ids means two readers of one corpus
-- already disagree about which match a sample belongs to, and the daemon treats
-- that state as an error of its own -- "matchid case mismatch", in
-- ktpResolveProducerEventContext.
--
--
-- ============================================================================
-- WHAT THE REPORT IS FOR: THE GAP, NOT THE DEFECT COUNT
-- ============================================================================
--
-- A query that returns "N bad rows" rebuilds the problem, because the problem is
-- that a time-filtered query and a bare count disagree and NEITHER says so.
-- Sections C and D therefore print, on adjacent lines over one scope:
--
--     what a bare COUNT(*) sees | what a time filter sees | the gap between them
--     what a per-match join sees | what a per-half join sees | each gap
--
-- Read the GAP_ lines first. They are the finding. The defect counts below them
-- are how the finding is explained.
--
--
-- ============================================================================
-- COST
-- ============================================================================
--
-- Section C is index-driven: COUNT(*) plus a range scan on idx_event_time.
-- Sections D and G scan the table once each. Section H scans it once more and is
-- marked optional for that reason. On a multi-million-row table, run this off a
-- match night, and use @since_id for repeat readings.


-- ============================================================================
-- SECTION A  ENVIRONMENT AND REPRESENTATION -- read before any number below
-- ============================================================================

SET SESSION max_execution_time = 900000;
SET @since_id    := IFNULL(@since_id, 0);
SET @epoch_floor := '1971-01-01 00:00:00';

SELECT
    DATABASE()                      AS db,
    @@session.time_zone             AS session_time_zone,
    @@global.time_zone              AS global_time_zone,
    NOW()                           AS db_now,
    FROM_UNIXTIME(0)                AS from_unixtime_zero_renders_as,
    @epoch_floor                    AS epoch_floor_in_use,
    @since_id                       AS scoped_to_ids_above;


-- ============================================================================
-- SECTION B  PREFLIGHT -- halt rather than report a confident wrong number
-- ============================================================================

SET @missing := (
    SELECT GROUP_CONCAT(w.col ORDER BY w.col)
    FROM (SELECT 'id' AS col UNION ALL SELECT 'match_id' UNION ALL SELECT 'half'
          UNION ALL SELECT 'event_time' UNION ALL SELECT 'event_epoch'
          UNION ALL SELECT 'created_at') w
    WHERE NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS c
        WHERE c.TABLE_SCHEMA = DATABASE()
          AND c.TABLE_NAME = 'ktp_position_samples'
          AND c.COLUMN_NAME = w.col));
SET @ddl := IF(@missing IS NULL, 'DO 0',
    'SELECT * FROM ERROR_B1_ktp_position_samples_is_missing_a_required_column');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- An ungranted ktp_matches is omitted from information_schema, so it reads as
-- absent. Every sample would then score as an orphan, and the report would look
-- like a catastrophe rather than like a permissions problem.
SET @ddl := IF((SELECT COUNT(*) FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ktp_matches') = 1,
    'DO 0',
    'SELECT * FROM ERROR_B2_ktp_matches_invisible_to_this_account_every_row_would_read_orphan');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;


-- ============================================================================
-- SECTION C  DEFECT A, AND THE TIME-FILTER GAP
--     One output row per metric. Values are CAST to CHAR so counts and
--     datetime watermarks can share one pass and one readable column.
-- ============================================================================

WITH a AS (
    SELECT
        COUNT(*)                                                      AS rows_total,
        MIN(p.id)                                                     AS rows_min_id,
        MAX(p.id)                                                     AS rows_max_id,
        SUM(p.event_time <  @epoch_floor)                             AS ez_rows,
        MAX(IF(p.event_time <  @epoch_floor, p.id, NULL))             AS ez_max_id,
        MIN(IF(p.event_time <  @epoch_floor, p.created_at, NULL))     AS ez_min_created,
        MAX(IF(p.event_time <  @epoch_floor, p.created_at, NULL))     AS ez_max_created,
        MIN(IF(p.event_time >= @epoch_floor, p.event_time, NULL))     AS good_min_event_time,
        MAX(IF(p.event_time >= @epoch_floor, p.event_time, NULL))     AS good_max_event_time
    FROM ktp_position_samples p
    WHERE p.id > @since_id)
          SELECT  1 AS n, 'C rows_a_bare_COUNT_sees'    AS metric, CAST(a.rows_total              AS CHAR) AS value FROM a
UNION ALL SELECT  2, 'C rows_any_time_filter_sees',     CAST(a.rows_total - a.ez_rows  AS CHAR) FROM a
UNION ALL SELECT  3, 'C GAP_time_filter_silently_loses', CAST(a.ez_rows               AS CHAR) FROM a
UNION ALL SELECT  4, 'A epoch_zero_rows',               CAST(a.ez_rows                AS CHAR) FROM a
UNION ALL SELECT  5, 'A epoch_zero_max_id',             CAST(a.ez_max_id              AS CHAR) FROM a
UNION ALL SELECT  6, 'A epoch_zero_first_inserted_at',  CAST(a.ez_min_created         AS CHAR) FROM a
UNION ALL SELECT  7, 'A epoch_zero_last_inserted_at',   CAST(a.ez_max_created         AS CHAR) FROM a
UNION ALL SELECT  8, 'rows_min_id',                     CAST(a.rows_min_id            AS CHAR) FROM a
UNION ALL SELECT  9, 'rows_max_id',                     CAST(a.rows_max_id            AS CHAR) FROM a
UNION ALL SELECT 10, 'usable_event_time_earliest',      CAST(a.good_min_event_time    AS CHAR) FROM a
UNION ALL SELECT 11, 'usable_event_time_latest',        CAST(a.good_max_event_time    AS CHAR) FROM a
ORDER BY n;

-- HOW TO READ SECTION C
--   GAP_time_filter_silently_loses = 0
--       No row is invisible to a time filter. Defect A is absent in this scope.
--   above 0, and epoch_zero_max_id ABOVE the previous reading's rows_max_id
--       The producer is STILL EMITTING. The source is not stopped.
--   above 0, and epoch_zero_max_id UNCHANGED from the previous reading
--       A frozen historical population. Nothing new is accruing, and what
--       remains is the repair-or-exclude disposition for the stored rows.
--   epoch_zero_first_inserted_at / epoch_zero_last_inserted_at
--       created_at is TIMESTAMP DEFAULT CURRENT_TIMESTAMP (migration 008) and is
--       NOT derived from event_epoch, so it survives on a defective row. It
--       dates the population, and it is a real clock a repair could use instead
--       of a guess. Whether to use it is the operator's call, not this file's.


-- ============================================================================
-- SECTION D  DEFECT B, AND THE MATCH-JOIN GAP
--     Grouped at (match_id, half), which is ktp_matches' own unique grain. One
--     row of the inner aggregate is one (match_id, half) AS THE SAMPLES CLAIM
--     IT, which is not the same thing as a match half that exists.
-- ============================================================================

WITH pairs AS (
    SELECT p.match_id, p.half,
           COUNT(*)          AS rows_in_pair,
           MAX(p.id)         AS max_id,
           MIN(p.created_at) AS min_created,
           MAX(p.created_at) AS max_created
    FROM ktp_position_samples p
    WHERE p.id > @since_id
    GROUP BY p.match_id, p.half),
classified AS (
    SELECT q.match_id, q.half, q.rows_in_pair, q.max_id, q.min_created, q.max_created,
           (q.match_id IS NOT NULL AND q.match_id <> '')              AS has_match_id,
           EXISTS (SELECT 1 FROM ktp_matches m
                   WHERE m.match_id = q.match_id)                     AS match_known,
           EXISTS (SELECT 1 FROM ktp_matches m
                   WHERE m.match_id = q.match_id AND m.half = q.half) AS half_known,
           EXISTS (SELECT 1 FROM ktp_matches m
                   WHERE m.match_id = q.match_id
                     AND BINARY m.match_id = BINARY q.match_id)       AS match_known_bytewise
    FROM pairs q),
d AS (
    SELECT
        SUM(IF(has_match_id, rows_in_pair, 0))                                    AS rows_with_match_id,
        SUM(IF(match_id IS NULL, rows_in_pair, 0))                                AS rows_match_id_null,
        SUM(IF(match_id IS NOT NULL AND match_id = '', rows_in_pair, 0))          AS rows_match_id_empty_string,
        SUM(IF(has_match_id AND NOT match_known, rows_in_pair, 0))                AS orphan_match_rows,
        COUNT(DISTINCT IF(has_match_id AND NOT match_known, match_id, NULL))      AS orphan_match_ids,
        SUM(IF(has_match_id AND match_known AND NOT half_known, rows_in_pair, 0)) AS orphan_half_rows,
        COUNT(DISTINCT IF(has_match_id AND match_known AND NOT half_known,
                          CONCAT(match_id, '#', half), NULL))                     AS orphan_half_pairs,
        COUNT(DISTINCT IF(has_match_id AND match_known AND NOT match_known_bytewise,
                          match_id, NULL))                                        AS case_variant_match_ids,
        MAX(IF(has_match_id AND (NOT match_known OR NOT half_known), max_id, NULL))      AS orphan_max_id,
        MIN(IF(has_match_id AND (NOT match_known OR NOT half_known), min_created, NULL)) AS orphan_min_created,
        MAX(IF(has_match_id AND (NOT match_known OR NOT half_known), max_created, NULL)) AS orphan_max_created
    FROM classified)
          SELECT  1 AS n, 'D rows_with_a_match_id'  AS metric, CAST(d.rows_with_match_id AS CHAR) AS value FROM d
UNION ALL SELECT  2, 'D rows_a_per_match_join_sees', CAST(d.rows_with_match_id - d.orphan_match_rows AS CHAR) FROM d
UNION ALL SELECT  3, 'D GAP_per_match_join_loses',   CAST(d.orphan_match_rows  AS CHAR) FROM d
UNION ALL SELECT  4, 'D rows_a_per_half_join_sees',  CAST(d.rows_with_match_id - d.orphan_match_rows - d.orphan_half_rows AS CHAR) FROM d
UNION ALL SELECT  5, 'D GAP_per_half_join_loses',    CAST(d.orphan_match_rows + d.orphan_half_rows AS CHAR) FROM d
UNION ALL SELECT  6, 'B1 orphan_match_rows',         CAST(d.orphan_match_rows  AS CHAR) FROM d
UNION ALL SELECT  7, 'B1 orphan_match_ids',          CAST(d.orphan_match_ids   AS CHAR) FROM d
UNION ALL SELECT  8, 'B2 orphan_half_rows',          CAST(d.orphan_half_rows   AS CHAR) FROM d
UNION ALL SELECT  9, 'B2 orphan_half_pairs',         CAST(d.orphan_half_pairs  AS CHAR) FROM d
UNION ALL SELECT 10, 'B case_variant_match_ids',     CAST(d.case_variant_match_ids AS CHAR) FROM d
UNION ALL SELECT 11, 'B orphan_max_id',              CAST(d.orphan_max_id      AS CHAR) FROM d
UNION ALL SELECT 12, 'B orphan_first_inserted_at',   CAST(d.orphan_min_created AS CHAR) FROM d
UNION ALL SELECT 13, 'B orphan_last_inserted_at',    CAST(d.orphan_max_created AS CHAR) FROM d
UNION ALL SELECT 14, 'not_a_defect rows_match_id_null',  CAST(d.rows_match_id_null AS CHAR) FROM d
UNION ALL SELECT 15, 'B3 rows_match_id_empty_string',    CAST(d.rows_match_id_empty_string AS CHAR) FROM d
ORDER BY n;

-- HOW TO READ SECTION D
--   rows_match_id_null is printed so it cannot be mistaken for a defect, and so
--   nobody re-derives the 2026-10-05 null-or-zero figure by accident.
--   rows_match_id_empty_string above 0 IS a defect, and a different one. It
--   points at the producer side, not at a missing ktp_matches row.
--   RECONCILE THE TWO SECTIONS BEFORE BELIEVING EITHER. rows_with_a_match_id
--   plus rows_match_id_null plus rows_match_id_empty_string must equal section
--   C's rows_a_bare_COUNT_sees over the same @since_id. They are counted by two
--   different queries at two different grains, so a disagreement is a defect in
--   this file or a concurrent insert between the two statements -- not a finding
--   about the data.
--   GAP_per_half_join_loses is what a per-half report silently drops. It is
--   larger than GAP_per_match_join_loses by construction.
--   case_variant_match_ids above 0 means BINARY and non-BINARY readers of this
--   corpus return different populations. Fix the ids, or make every reader
--   agree. Do not pick whichever answer is smaller.
--   orphan_max_id against the previous reading's rows_max_id answers accrual,
--   exactly as in section C. An orphan can also be created RETROACTIVELY by
--   deleting a ktp_matches row, so a rising orphan_max_id is not by itself proof
--   that the producer regressed -- find what removed the match.
--   scripts/ktp-match-retention.py is not a candidate: it deletes
--   ktp_position_samples before ktp_matches inside one transaction, and both
--   tables are InnoDB.


-- ============================================================================
-- SECTION E  CONTROLS -- a zero above means nothing until these read as stated
-- ============================================================================

          SELECT 'ctl_position_rows_must_be_nonzero' AS control,
                 CAST((SELECT COUNT(*) FROM ktp_position_samples) AS CHAR) AS value,
                 'if 0, every count above is about an empty table' AS reading
UNION ALL SELECT 'ctl_match_rows_must_be_nonzero',
                 CAST((SELECT COUNT(*) FROM ktp_matches) AS CHAR),
                 'if 0, every row is an orphan for a reason that is not a data defect'
UNION ALL SELECT 'ctl_rows_in_a_sane_window_must_be_nonzero',
                 CAST((SELECT COUNT(*) FROM ktp_position_samples
                       WHERE event_time >= '2026-01-01' AND event_time <= NOW()) AS CHAR),
                 'positive control for the time predicate itself'
UNION ALL SELECT 'ctl_impossible_future_must_be_zero',
                 CAST((SELECT COUNT(*) FROM ktp_position_samples
                       WHERE event_time > '2090-01-01') AS CHAR),
                 'negative control, a predicate that cannot match'
UNION ALL SELECT 'ctl_nonsense_match_id_must_be_zero',
                 CAST((SELECT COUNT(*) FROM ktp_position_samples
                       WHERE match_id = 'zzz-no-such-match-zzz') AS CHAR),
                 'second negative control, on the match_id predicate';


-- ============================================================================
-- SECTION F  WHAT AN EPOCH-ZERO ROW ACTUALLY STORES ON THIS HOST
--     Print it. Do not carry a remembered literal into the next query.
-- ============================================================================

SELECT p.event_time       AS stored_literal,
       COUNT(*)           AS rows_with_it,
       MIN(p.event_epoch) AS min_event_epoch,
       MAX(p.event_epoch) AS max_event_epoch,
       MIN(p.created_at)  AS first_inserted_at,
       MAX(p.created_at)  AS last_inserted_at
FROM ktp_position_samples p
WHERE p.event_time < @epoch_floor
  AND p.id > @since_id
GROUP BY p.event_time
ORDER BY rows_with_it DESC
LIMIT 20;


-- ============================================================================
-- SECTION G  WORST-AFFECTED (match_id, half) PAIRS
--     One row is one (match_id, half) as the SAMPLES claim it.
--     match_row_exists and half_row_exists say whether ktp_matches agrees.
-- ============================================================================

SELECT p.match_id,
       p.half,
       COUNT(*)                                       AS sample_rows,
       SUM(p.event_time < @epoch_floor)               AS epoch_zero_rows,
       EXISTS (SELECT 1 FROM ktp_matches m
               WHERE m.match_id = p.match_id)         AS match_row_exists,
       EXISTS (SELECT 1 FROM ktp_matches m
               WHERE m.match_id = p.match_id
                 AND m.half = p.half)                 AS half_row_exists,
       MIN(p.created_at)                              AS first_inserted_at,
       MAX(p.created_at)                              AS last_inserted_at
FROM ktp_position_samples p
WHERE p.id > @since_id
GROUP BY p.match_id, p.half
HAVING epoch_zero_rows > 0 OR match_row_exists = 0 OR half_row_exists = 0
ORDER BY (epoch_zero_rows + IF(half_row_exists = 0, sample_rows, 0)) DESC
LIMIT 40;


-- ============================================================================
-- SECTION H  OPTIONAL CROSS-CHECK -- does event_epoch agree with the floor?
--     A full scan, because event_epoch is unindexed. Drop this section if it
--     costs too much. Nothing above depends on it.
-- ============================================================================

SELECT
    SUM(p.event_time <  @epoch_floor AND COALESCE(p.event_epoch = 0, 0))     AS both_markers_agree,
    SUM(p.event_time <  @epoch_floor AND NOT COALESCE(p.event_epoch = 0, 0)) AS near_epoch_time_but_epoch_not_zero,
    SUM(p.event_time >= @epoch_floor AND COALESCE(p.event_epoch = 0, 0))     AS epoch_zero_marker_but_time_looks_fine,
    SUM(p.event_time <  @epoch_floor AND p.event_epoch IS NULL)              AS near_epoch_time_with_pre_021_null_epoch
FROM ktp_position_samples p
WHERE p.id > @since_id;

-- HOW TO READ SECTION H
--   both_markers_agree should account for the whole of defect A on rows written
--   after migration 021. Each of the other three columns is a separate surprise.
--   A near-epoch event_time beside a real event_epoch means something other than
--   the `// 0` default produced it. An event_epoch of 0 beside a plausible
--   event_time means the two were not written from the same value. A near-epoch
--   event_time with a NULL event_epoch means a pre-021 row is affected, which
--   the writer history does not predict, because the original 2026-08-13 handler
--   inserted NOW().
--
--
-- ============================================================================
-- WHERE THE ROWS CAME FROM -- the producer, named so the second half is scopable
-- ============================================================================
--
-- KTPHLStatsX scripts/hlstats.pl, doEvent_KTPPosition. Commit e78a0e3
-- (2026-08-22, alongside migration 021) replaced the original handler's `NOW()`
-- with
--
--     int($event_epoch // 0), FROM_UNIXTIME(int($event_epoch // 0))
--
-- while `event_epoch` was still an OPTIONAL marker field and the handler had no
-- gate at all. A producer that did not send one took the legacy branch, and the
-- `// 0` turned "this producer reports no clock" into "this sample happened at
-- the epoch". The SAME branch tagged match_id from receipt-time daemon memory,
-- $g_ktpMatchContext, with no proof that a ktp_matches row existed -- so one
-- code path emits BOTH defects.
--
-- Commit 7663afc (2026-08-30) closed it, and on today's origin/main three gates
-- stand between a marker and that branch: the call site's
-- ktpCaptureManifestAuthorizes, the in-handler schema-23-or-later manifest
-- check, and ktpValidateProducerEventClock, whose event_epoch regex is
-- /^[1-9]\d{0,18}$/ -- zero is refused. The resolver additionally requires
-- exactly one matching ktp_matches interval, which is why a row written by
-- today's code cannot be an orphan either. Inference, not a measurement: the
-- stored defective population should be bounded by those two dates, and section
-- C's epoch_zero_first_inserted_at and epoch_zero_last_inserted_at are the test
-- of it.
--
-- THE DEFECT IS UNREACHABLE, NOT REMOVED. The `// 0` default is still in the
-- INSERT, so the guarantee lives entirely in the validators above it. Four other
-- streams share the same expression -- ktp_shot_events, ktp_move_census,
-- ktp_aim_vis and ktp_flag_state_events -- and this file does not measure them.
--
-- A SECOND, INDEPENDENT ORPHAN MECHANISM, from KTPHLStatsX's own service-dev
-- skill. getProperties' value branch has to be `.*?` -- with `.+?` the lazy
-- match runs past the closing quote and returns the rest of the log line as the
-- value, minting a match id no ktp_matches row will ever carry, with nothing
-- erroring. That is an orphan id of exactly the B1 shape and it arrives from the
-- parser rather than from the match-context branch, so a fix to one does not
-- close the other. The same skill records that $g_ktpMatchContext has no
-- staleness bound and is never cleared on an OT-decided match, so events after
-- one are tagged to the finished match -- that one mis-attributes to a match
-- that DOES exist, so it is invisible to both definitions here. Named so the
-- next reader does not conclude this file covers it.
