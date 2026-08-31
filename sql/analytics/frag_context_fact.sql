-- Enriched frag feed used only for private weapon/range exploration. Keep the
-- smaller frag_timeline_fact query as the compatibility source for archives
-- that predate KTP tactical-context columns.
SELECT
    f.id AS event_id,
    f.event_epoch AS event_unix,
    FROM_UNIXTIME(f.event_epoch) AS event_time,
    CASE
      WHEN BINARY f.producer_match_id = BINARY {{MATCH_ID}}
       AND f.producer_half > 0
      THEN f.producer_half
      ELSE NULL
    END AS half,
    f.half AS stored_half,
    f.producer_match_id,
    f.producer_half,
    f.game_time,
    f.event_epoch,
    f.killerId AS killer_id,
    killer.steam_id AS killer_steam_id,
    killer.player_name AS killer_name,
    killer.team AS killer_team,
    f.victimId AS victim_id,
    victim.steam_id AS victim_steam_id,
    victim.player_name AS victim_name,
    victim.team AS victim_team,
    f.weapon,
    f.headshot,
    f.killerRole AS killer_role,
    f.victimRole AS victim_role,
    f.pos_x AS killer_pos_x,
    f.pos_y AS killer_pos_y,
    f.pos_z AS killer_pos_z,
    f.pos_victim_x AS victim_pos_x,
    f.pos_victim_y AS victim_pos_y,
    f.pos_victim_z AS victim_pos_z,
    f.k_prone AS killer_prone,
    f.k_scope AS killer_scoped,
    f.k_clip AS killer_clip,
    f.k_ammo AS killer_ammo,
    f.is_last_flag_defense,
    f.frag_context_recorded
FROM hlstats_Events_Frags f
LEFT JOIN ktp_match_players killer
  ON BINARY killer.match_id = BINARY f.producer_match_id
 AND killer.player_id = f.killerId
LEFT JOIN ktp_match_players victim
  ON BINARY victim.match_id = BINARY f.producer_match_id
 AND victim.player_id = f.victimId
WHERE (BINARY f.match_id = BINARY {{MATCH_ID}}
       OR BINARY f.producer_match_id = BINARY {{MATCH_ID}})
  -- Keep legacy/mismatched stored rows visible as invalid coverage. `half` is
  -- NULL unless producer context names this exact match and a positive half.
ORDER BY COALESCE(f.producer_half, f.half),
         COALESCE(f.game_time, UNIX_TIMESTAMP(f.eventTime)), f.id;
