-- Compact ownership timeline for private objective-pressure classification.
SELECT
    id AS event_id,
    half,
    flag_index,
    flag_name,
    owner_team,
    is_initial,
    game_time,
    event_time
FROM ktp_flag_state_events
WHERE match_id = {{MATCH_ID}}
  AND half > 0
ORDER BY half, flag_index, game_time, id;
