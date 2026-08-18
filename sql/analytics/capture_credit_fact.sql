-- One row is an aggregate of player capture credits. It is not a count of
-- unique flag-control changes when multiple players receive credit.
SELECT
    c.match_id,
    c.player_id,
    r.player_name AS player_name_at_match,
    r.team,
    c.flag_name,
    COUNT(*) AS capture_credits
FROM ktp_flag_captures c
LEFT JOIN ktp_match_players r
  ON r.match_id = c.match_id AND r.player_id = c.player_id
WHERE c.match_id = {{MATCH_ID}}
GROUP BY c.match_id, c.player_id, r.player_name, r.team, c.flag_name
ORDER BY r.team, capture_credits DESC, r.player_name, c.flag_name;
