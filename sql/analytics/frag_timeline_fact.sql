-- Private, read-only event feed for shadow timeline analytics.
SELECT
    f.id AS event_id,
    UNIX_TIMESTAMP(f.eventTime) AS event_unix,
    f.eventTime AS event_time,
    f.half,
    f.killerId AS killer_id,
    killer.steam_id AS killer_steam_id,
    killer.player_name AS killer_name,
    killer.team AS killer_team,
    f.victimId AS victim_id,
    victim.steam_id AS victim_steam_id,
    victim.player_name AS victim_name,
    victim.team AS victim_team,
    f.weapon,
    f.headshot
FROM hlstats_Events_Frags f
LEFT JOIN ktp_match_players killer
  ON killer.match_id = f.match_id AND killer.player_id = f.killerId
LEFT JOIN ktp_match_players victim
  ON victim.match_id = f.match_id AND victim.player_id = f.victimId
WHERE f.match_id = {{MATCH_ID}}
  AND f.half > 0
  AND f.eventTime IS NOT NULL
ORDER BY f.half, f.eventTime, f.id;
