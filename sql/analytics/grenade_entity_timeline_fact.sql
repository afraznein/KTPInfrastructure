-- Private analytics fact. Coordinates must never enter a public report.
SELECT
  server_id,
  match_id,
  half,
  entity_kind,
  entindex,
  serial,
  weapon_id,
  weapon_type,
  owner_player_id,
  owner_engine_userid,
  pos_x,
  pos_y,
  pos_z,
  game_time,
  event_epoch,
  producer_sequence,
  event_time
FROM ktp_grenade_entity_events
WHERE BINARY match_id = BINARY {{MATCH_ID}}
ORDER BY half, event_epoch, producer_sequence, id;
