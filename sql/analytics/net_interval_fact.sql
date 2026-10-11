-- Server net telemetry over this match's played halves, one row. ktp_net_intervals
-- is one row per 10 s window per server carrying the WORST client per gauge
-- (jitter, latency, drops, loss), so this is the box-level view: how rough the
-- match was, not who was rough. Windows outside the halves (warm-up, the gap
-- between halves) are excluded by the time join, not by match_id alone, because
-- the producer stamps the open match on pre-match windows too.
-- Read only. {{MATCH_ID}} is replaced with one safely quoted SQL literal by
-- scripts/match_analytics.py.
WITH halves AS (
    SELECT half, start_time, end_time
    FROM ktp_matches
    WHERE match_id = {{MATCH_ID}} AND end_time IS NOT NULL
)
SELECT
    COUNT(*) AS windows,
    ROUND(AVG(n.drops), 2) AS drops_per_window,
    ROUND(AVG(n.jitter_worst_ms), 1) AS jitter_worst_avg_ms,
    ROUND(AVG(n.latency_worst_ms), 1) AS latency_worst_avg_ms,
    SUM(CASE WHEN n.latency_worst_ms >= 300 THEN 1 ELSE 0 END) AS windows_ge300,
    SUM(CASE WHEN n.lagcomp_off > 0 THEN 1 ELSE 0 END) AS lagcomp_off_windows,
    ROUND(AVG(n.maxunlag_hits), 2) AS maxunlag_hits_per_window,
    SUM(CASE WHEN n.choke_peak > 0 THEN 1 ELSE 0 END) AS choke_windows
FROM ktp_net_intervals n
JOIN halves h ON n.ts BETWEEN h.start_time AND h.end_time
WHERE n.match_id = {{MATCH_ID}}
