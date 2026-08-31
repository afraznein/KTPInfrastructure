-- Private, read-only physical-life boundary feed. round_live is intentionally
-- nullable: the v1 AMXX emitter cannot observe MatchHandler's private DODX
-- pause flag, and buffered receipt-time state would be an unsafe substitute.
SELECT
    le.id AS event_id,
    le.event_epoch,
    le.event_epoch AS event_unix,
    FROM_UNIXTIME(le.event_epoch) AS event_time,
    le.game_time,
    le.half,
    le.player_id,
    roster.steam_id,
    roster.player_name,
    le.team,
    le.player_slot,
    le.engine_userid,
    le.player_class,
    le.round_live,
    le.boundary_kind,
    le.reason
FROM ktp_life_events le
LEFT JOIN ktp_match_players roster
  ON BINARY roster.match_id = BINARY le.match_id
 AND roster.player_id = le.player_id
WHERE BINARY le.match_id = BINARY {{MATCH_ID}}
  AND le.half > 0
  AND le.game_time >= 0
  AND le.event_epoch > 0
ORDER BY le.half, le.player_id, le.game_time, le.id;
