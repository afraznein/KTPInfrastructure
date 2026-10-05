-- Whether the per-hit damage producer existed for this match. Read only.
-- {{MATCH_ID}} is replaced with one safely quoted SQL literal by
-- scripts/match_analytics.py.
--
-- ktp_damage_events exists on every match the live database holds, but it was
-- born partway through the archive. A match that ended before the ledger's
-- first hit cannot have measured damage taken, team or self damage, so its 0
-- there is unknown, not zero. Both probes are index lookups (idx_match,
-- idx_event_time) on an InnoDB table.
SELECT
    (EXISTS(SELECT 1 FROM ktp_damage_events WHERE match_id = {{MATCH_ID}})
     OR EXISTS(SELECT 1 FROM ktp_damage_events
               WHERE event_time <= (SELECT MAX(COALESCE(end_time, start_time))
                                    FROM ktp_matches
                                    WHERE match_id = {{MATCH_ID}})))
        AS per_hit_damage_covered;
