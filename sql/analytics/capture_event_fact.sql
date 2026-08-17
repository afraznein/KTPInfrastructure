-- One row per unique capture event. credited_players preserves multi-capper
-- size; do not sum ktp_flag_captures directly to count control changes.
SELECT
    match_id,
    half,
    team AS team_name,
    flag_name,
    event_time,
    COUNT(*) AS credited_players
FROM ktp_flag_captures
WHERE match_id = {{MATCH_ID}}
GROUP BY match_id, half, team, flag_name, event_time
ORDER BY event_time, flag_name, team;
