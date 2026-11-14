-- Per-event cap-break feed, producer-clocked. One row per correlated break
-- (hlstats_Actions.code = 'cap_break', break_context_recorded = 1) -- an
-- uncorrelated break has no game_time and is excluded, same discipline the
-- damage/frag timelines use for their own clock columns.
SELECT
    pa.id AS event_id,
    pa.producer_event_epoch AS event_unix,
    FROM_UNIXTIME(pa.producer_event_epoch) AS event_time,
    pa.producer_game_time AS game_time,
    pa.producer_event_epoch AS event_epoch,
    pa.producer_half AS half,
    pa.producer_match_id,
    pa.playerId AS breaker_id,
    breaker.steam_id AS breaker_steam_id,
    breaker.player_name AS breaker_name,
    breaker.team AS breaker_team,
    pa.flag_name,
    pa.flag_index,
    pa.break_victim_id AS victim_id,
    victim.steam_id AS victim_steam_id,
    victim.player_name AS victim_name,
    pa.is_capout,
    pa.contester_count,
    pa.time_remaining
FROM hlstats_Events_PlayerActions pa
JOIN hlstats_Actions a ON a.id = pa.actionId AND a.game = 'dod' AND a.code = 'cap_break'
LEFT JOIN ktp_match_players breaker
  ON breaker.match_id = pa.producer_match_id
 AND BINARY breaker.match_id = BINARY pa.producer_match_id
 AND breaker.player_id = pa.playerId
LEFT JOIN ktp_match_players victim
  ON victim.match_id = pa.producer_match_id
 AND BINARY victim.match_id = BINARY pa.producer_match_id
 AND victim.player_id = pa.break_victim_id
WHERE pa.producer_match_id = {{MATCH_ID}}
  AND BINARY pa.producer_match_id = BINARY {{MATCH_ID}}
  AND pa.break_context_recorded = 1
  AND pa.producer_game_time IS NOT NULL
ORDER BY pa.producer_half, pa.producer_game_time, pa.id;
