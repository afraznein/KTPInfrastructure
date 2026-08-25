-- Private, read-only canonical assist-context feed. Unlike the generic
-- PlayerPlayerAction row, this ledger preserves producer match, half, and
-- clocks before the AMXX log buffer can delay daemon receipt.
SELECT
    ae.id AS event_id,
    ae.event_epoch,
    ae.event_epoch AS event_unix,
    FROM_UNIXTIME(ae.event_epoch) AS event_time,
    ae.game_time,
    ae.half,
    ae.assister_id,
    assister.steam_id AS assister_steam_id,
    assister.player_name AS assister_name,
    assister.team AS assister_team,
    ae.victim_id,
    victim.steam_id AS victim_steam_id,
    victim.player_name AS victim_name,
    victim.team AS victim_team
FROM ktp_assist_events ae
LEFT JOIN ktp_match_players assister
  ON BINARY assister.match_id = BINARY ae.match_id
 AND assister.player_id = ae.assister_id
LEFT JOIN ktp_match_players victim
  ON BINARY victim.match_id = BINARY ae.match_id
 AND victim.player_id = ae.victim_id
WHERE BINARY ae.match_id = BINARY {{MATCH_ID}}
  AND ae.half > 0
  AND ae.game_time >= 0
  AND ae.event_epoch > 0
ORDER BY ae.half, ae.game_time, ae.id;
