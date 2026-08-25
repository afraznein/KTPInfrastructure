-- Unique flag-control events used only for private shadow correlations.
SELECT
    half,
    UNIX_TIMESTAMP(event_time) AS event_unix,
    event_time,
    team AS team_name,
    CASE LOWER(team)
      WHEN 'allies' THEN 1
      WHEN 'axis' THEN 2
      ELSE NULL
    END AS team,
    flag_name,
    COUNT(*) AS credited_players
FROM ktp_flag_captures
WHERE match_id = {{MATCH_ID}}
GROUP BY half, event_time, team, flag_name
ORDER BY half, event_time, flag_name;
