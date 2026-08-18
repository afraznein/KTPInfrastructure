-- One row per assister/victim pair. The event does not carry an assist weapon,
-- so none is inferred from nearby damage events.
SELECT
    e.match_id,
    e.playerId AS player_id,
    assister.player_name AS player_name_at_match,
    assister.team,
    e.victimId AS victim_id,
    victim.player_name AS victim_name_at_match,
    COUNT(*) AS assists
FROM hlstats_Events_PlayerPlayerActions e
JOIN hlstats_Actions a ON a.id = e.actionId
LEFT JOIN ktp_match_players assister
  ON assister.match_id = e.match_id AND assister.player_id = e.playerId
LEFT JOIN ktp_match_players victim
  ON victim.match_id = e.match_id AND victim.player_id = e.victimId
WHERE e.match_id = {{MATCH_ID}} AND a.game = 'dod' AND a.code = 'assist'
GROUP BY e.match_id, e.playerId, assister.player_name, assister.team,
         e.victimId, victim.player_name
ORDER BY assister.team, assists DESC, assister.player_name, victim.player_name;
