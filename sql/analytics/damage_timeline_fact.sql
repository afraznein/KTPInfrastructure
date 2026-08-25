-- Private, read-only per-hit feed for shadow damage-conversion analysis.
-- damage_capped is the competitive damage definition; raw nominal damage is
-- intentionally excluded from this exploration.
SELECT
    d.id AS event_id,
    d.event_epoch AS event_unix,
    FROM_UNIXTIME(d.event_epoch) AS event_time,
    d.game_time,
    d.event_epoch,
    CASE
      WHEN BINARY d.producer_match_id = BINARY {{MATCH_ID}}
       AND d.producer_half > 0
      THEN d.producer_half
      ELSE NULL
    END AS half,
    d.half AS stored_half,
    d.producer_match_id,
    d.producer_half,
    d.attacker_id,
    attacker.steam_id AS attacker_steam_id,
    attacker.player_name AS attacker_name,
    attacker.team AS attacker_team,
    d.victim_id,
    victim.steam_id AS victim_steam_id,
    victim.player_name AS victim_name,
    victim.team AS victim_team,
    d.weapon,
    d.damage_capped,
    d.hitplace
FROM ktp_damage_events d
LEFT JOIN ktp_match_players attacker
  ON BINARY attacker.match_id = BINARY d.producer_match_id
 AND attacker.player_id = d.attacker_id
LEFT JOIN ktp_match_players victim
  ON BINARY victim.match_id = BINARY d.producer_match_id
 AND victim.player_id = d.victim_id
WHERE (BINARY d.match_id = BINARY {{MATCH_ID}}
       OR BINARY d.producer_match_id = BINARY {{MATCH_ID}})
  -- Stored context keeps contract-violating/legacy rows visible to the pure
  -- analyzer. The CASE above nulls their half, so they are counted and fail
  -- closed instead of being mistaken for target-match evidence.
ORDER BY COALESCE(d.producer_half, d.half),
         COALESCE(d.game_time, UNIX_TIMESTAMP(d.event_time)), d.id;
