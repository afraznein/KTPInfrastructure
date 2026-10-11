-- Ping at the moment of each shot, per shooter, for this match. The exact
-- per-match connection instrument: it is sampled on the shooter's own packets
-- during play, so it is this match and only this match. Present only where the
-- shot-detail stream was on (ktp_shot_detail_types: 12-mans all season,
-- officials from 2026-10-10); a match without it has no rows here and the block
-- reads null, never zero.
-- Read only. {{MATCH_ID}} is replaced with one safely quoted SQL literal by
-- scripts/match_analytics.py.
SELECT
    player_id,
    COUNT(*) AS shots_with_ping,
    ROUND(AVG(shot_ping), 1) AS shot_ping_avg_ms,
    ROUND(STDDEV(shot_ping), 1) AS shot_ping_sd_ms,
    MAX(shot_ping) AS shot_ping_max_ms,
    SUM(COALESCE(net_dropped, 0)) AS shot_net_dropped
FROM ktp_shot_events
WHERE match_id = {{MATCH_ID}} AND shot_ping IS NOT NULL
GROUP BY player_id
