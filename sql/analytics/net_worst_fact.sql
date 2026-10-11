-- Who was the server's worst client, per gauge, over this match's played halves:
-- one row per name that was ever worst. ktp_net_intervals stores NAMES in its
-- worst-of columns, not ids, so the join to the roster happens in Python on the
-- name the player carried in the match. A share of 0.8 means "worst on the box in
-- 80% of windows" -- server-relative, never an absolute level.
-- Read only. {{MATCH_ID}} is replaced with one safely quoted SQL literal by
-- scripts/match_analytics.py.
WITH halves AS (
    SELECT half, start_time, end_time
    FROM ktp_matches
    WHERE match_id = {{MATCH_ID}} AND end_time IS NOT NULL
),
w AS (
    SELECT n.jitter_worst_name, n.jitter_worst_ms,
           n.latency_worst_name, n.latency_worst_ms,
           n.drops_worst_name, n.drops_worst_n
    FROM ktp_net_intervals n
    JOIN halves h ON n.ts BETWEEN h.start_time AND h.end_time
    WHERE n.match_id = {{MATCH_ID}}
),
u AS (
    SELECT jitter_worst_name AS name, 'jitter' AS gauge, jitter_worst_ms AS v FROM w
    UNION ALL
    SELECT latency_worst_name, 'latency', latency_worst_ms FROM w
    UNION ALL
    SELECT drops_worst_name, 'drops', drops_worst_n FROM w
)
SELECT
    name AS worst_name,
    SUM(CASE WHEN gauge = 'jitter' THEN 1 ELSE 0 END) AS jitter_worst_windows,
    SUM(CASE WHEN gauge = 'latency' THEN 1 ELSE 0 END) AS latency_worst_windows,
    SUM(CASE WHEN gauge = 'drops' THEN 1 ELSE 0 END) AS drops_worst_windows,
    SUM(CASE WHEN gauge = 'drops' THEN v ELSE 0 END) AS drops_when_worst,
    SUM(CASE WHEN gauge = 'latency' AND v >= 300 THEN 1 ELSE 0 END) AS latency_spikes_ge300,
    ROUND(AVG(CASE WHEN gauge = 'jitter' THEN v END), 1) AS jitter_when_worst_ms,
    MAX(CASE WHEN gauge = 'latency' THEN v END) AS latency_when_worst_max_ms
FROM u
WHERE name IS NOT NULL AND name <> ''
GROUP BY name
