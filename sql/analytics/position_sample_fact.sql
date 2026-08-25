-- Private input only. Callers must aggregate these rows and must never copy
-- raw coordinates into the shareable match report.
SELECT
    ps.id AS sample_id,
    ps.player_id,
    roster.steam_id,
    roster.player_name AS player_name_at_match,
    ps.team,
    ps.half,
    ps.pos_x,
    ps.pos_y,
    ps.pos_z,
    ps.game_time,
    ps.event_time
FROM ktp_position_samples ps
LEFT JOIN ktp_match_players roster
  ON BINARY roster.match_id = BINARY ps.match_id
 AND roster.player_id = ps.player_id
WHERE BINARY ps.match_id = BINARY {{MATCH_ID}}
  AND ps.half > 0
ORDER BY ps.half, ps.game_time, ps.id;
