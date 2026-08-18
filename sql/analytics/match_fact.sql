SELECT
    match_id,
    MAX(server_id) AS server_id,
    MAX(map_name) AS map_name,
    MIN(start_time) AS started_at,
    MAX(end_time) AS ended_at,
    COUNT(*) AS halves_played,
    SUM(CASE WHEN end_time IS NULL THEN 1 ELSE 0 END) AS open_halves,
    SUM(CASE WHEN end_time IS NULL THEN 0
             ELSE GREATEST(TIMESTAMPDIFF(SECOND, start_time, end_time), 0)
        END) AS duration_seconds,
    CASE WHEN match_id LIKE '%-TEST' THEN 1 ELSE 0 END AS is_test_match
FROM ktp_matches
WHERE match_id = {{MATCH_ID}}
GROUP BY match_id;
