-- Per-client net slice per half (KTP-ReHLDS #48 net_client:, ingested into
-- ktp_net_clients by KTPProfileAggregator) for the roster of this match. One row
-- per client per ktp_net_flush the match plugin issued with this match id: at
-- half end and at match end. The 'prelive' slice closed at match start holds
-- the warmup and is left out here; the report leaves it out as well.
-- Columns are the engine's reductions over the slice: usercmd.msec percentiles
-- are the client's own frame time in ms (1000/fps), arr_* the gap between its
-- move packets as the server saw them, pps and cmds_pkt the effective cmdrate
-- and commands per packet (fps ~ pps * cmds_pkt), stale_delta the deltas built
-- from an ack older than the frame ring (FlushEntityPacket on the client).
-- steam_id there is the engine's STEAM_0:Y:Z; the roster table keeps the bare Y:Z.
-- Read only. {{MATCH_ID}} is replaced with one safely quoted SQL literal by
-- scripts/match_analytics.py.
SELECT
    p.player_id AS player_id,
    c.half AS half,
    c.ts AS ts,
    c.span_s AS span_s,
    c.pkts AS pkts,
    c.cmds AS cmds,
    c.drops AS drops,
    c.pps AS pps,
    c.cmds_pkt AS cmds_pkt,
    c.msec_p50 AS msec_p50,
    c.msec_p95 AS msec_p95,
    c.msec_max AS msec_max,
    c.arr_p50 AS arr_p50,
    c.arr_p95 AS arr_p95,
    c.arr_max AS arr_max,
    c.interp_cap AS interp_cap,
    c.interp_floor AS interp_floor,
    c.stale_delta AS stale_delta
FROM ktp_net_clients c
JOIN (
    SELECT player_id, MIN(steam_id) AS steam_id
    FROM ktp_match_players
    WHERE match_id = {{MATCH_ID}}
    GROUP BY player_id
) p ON c.steam_id = CONCAT('STEAM_0:', p.steam_id)
WHERE c.match_id = {{MATCH_ID}}
  AND (c.half IS NULL OR c.half <> 'prelive')
ORDER BY p.player_id, c.ts
