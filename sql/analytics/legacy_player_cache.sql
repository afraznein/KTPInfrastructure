SELECT
    player_id,
    COALESCE(SUM(damage), 0) AS legacy_damage_dealt
FROM ktp_match_stats
WHERE match_id = {{MATCH_ID}} AND half = 0
GROUP BY player_id;
