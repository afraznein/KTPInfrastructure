-- Per-client engine session counters (KTP-ReHLDS net_session, ingested into
-- ktp_net_sessions) for the roster of this match. One row per session that
-- ENDED while this match was open: match_id on that table is the match open at
-- disconnect, and a session spans everything since SV_ConnectClient (dur_s), so
-- these describe the player's whole connection that night, not this match alone.
-- The report publishes dur_s beside them for that reason. steam_id there is the
-- engine's STEAM_0:Y:Z; the roster table keeps the bare Y:Z.
-- Read only. {{MATCH_ID}} is replaced with one safely quoted SQL literal by
-- scripts/match_analytics.py.
SELECT
    p.player_id AS player_id,
    s.dur_s AS session_seconds,
    s.pkts AS session_packets,
    s.drops AS session_drops,
    s.latency_avg_ms AS session_latency_avg_ms,
    s.latency_max_ms AS session_latency_max_ms,
    s.jitter_avg_ms AS session_jitter_avg_ms,
    s.loss_avg AS session_loss_avg_pct,
    s.loss_max AS session_loss_max_pct
FROM ktp_net_sessions s
JOIN (
    SELECT player_id, MIN(steam_id) AS steam_id
    FROM ktp_match_players
    WHERE match_id = {{MATCH_ID}}
    GROUP BY player_id
) p ON s.steam_id = CONCAT('STEAM_0:', p.steam_id)
WHERE s.match_id = {{MATCH_ID}}
ORDER BY p.player_id, s.dur_s DESC
