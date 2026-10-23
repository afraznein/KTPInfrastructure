-- The net cvars each client DECLARED during this match (KTPCvarChecker 7.43
-- NETOBS_SNAPSHOT, ingested into ktp_client_settings by KTPProfileAggregator),
-- for the roster of this match. One row per snapshot the plugin logged with
-- this match id: at match start (why=start), on any change during it
-- (why=change), at half end and match end. Values are what the client answered
-- query_client_cvar -- declared, not observed; a non-numeric answer is NULL.
-- The report pairs each half's slice with the why=start snapshot of that half,
-- else the latest snapshot at or before the slice closed.
-- steam_id there is the engine's STEAM_0:Y:Z; the roster table keeps the bare Y:Z.
-- Read only. {{MATCH_ID}} is replaced with one safely quoted SQL literal by
-- scripts/match_analytics.py.
SELECT
    p.player_id AS player_id,
    s.half AS half,
    s.why AS why,
    s.ts AS ts,
    s.updaterate AS updaterate,
    s.cmdrate AS cmdrate,
    s.rate AS rate,
    s.interp AS interp,
    s.fps_max AS fps_max,
    s.lc AS lc,
    s.lw AS lw
FROM ktp_client_settings s
JOIN (
    SELECT player_id, MIN(steam_id) AS steam_id
    FROM ktp_match_players
    WHERE match_id = {{MATCH_ID}}
    GROUP BY player_id
) p ON s.steam_id = CONCAT('STEAM_0:', p.steam_id)
WHERE s.match_id = {{MATCH_ID}}
ORDER BY p.player_id, s.ts
