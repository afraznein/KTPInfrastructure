-- Raw counts used by the Python quality evaluator. This query intentionally
-- does not repair or coalesce inconsistencies.
SELECT
  (SELECT COUNT(*) FROM ktp_matches WHERE match_id = {{MATCH_ID}}) AS match_halves,
  (SELECT COUNT(*) FROM ktp_matches
    WHERE match_id = {{MATCH_ID}} AND end_time IS NULL) AS open_halves,
  (SELECT COUNT(*) FROM ktp_match_players
    WHERE match_id = {{MATCH_ID}}) AS roster_players,
  (SELECT COUNT(DISTINCT player_id) FROM ktp_match_players
    WHERE match_id = {{MATCH_ID}}) AS distinct_roster_players,
  (SELECT COUNT(*) FROM hlstats_Events_Frags
    WHERE match_id = {{MATCH_ID}}) AS frags,
  (SELECT COUNT(*) FROM hlstats_Events_Frags
    WHERE match_id = {{MATCH_ID}} AND half <= 0) AS invalid_half_frags,
  (SELECT COUNT(*) FROM ktp_damage_events
    WHERE match_id = {{MATCH_ID}}) AS damage_events,
  (SELECT COUNT(*) FROM ktp_damage_events
    WHERE match_id = {{MATCH_ID}} AND half <= 0) AS invalid_half_damage,
  (SELECT COUNT(*) FROM hlstats_Events_Statsme
    WHERE match_id = {{MATCH_ID}}) AS statsme_rows,
  (SELECT COUNT(*) FROM hlstats_Events_Statsme2
    WHERE match_id = {{MATCH_ID}}) AS statsme2_rows,
  (SELECT COALESCE(SUM(hits), 0) FROM hlstats_Events_Statsme
    WHERE match_id = {{MATCH_ID}}) AS statsme_hits,
  (SELECT COALESCE(SUM(head + chest + stomach + leftarm + rightarm + leftleg + rightleg), 0)
    FROM hlstats_Events_Statsme2 WHERE match_id = {{MATCH_ID}}) AS located_hits,
  (SELECT COUNT(*) FROM ktp_flag_captures
    WHERE match_id = {{MATCH_ID}}) AS capture_credits,
  (SELECT COUNT(*) FROM (
      SELECT 1 FROM ktp_flag_captures
      WHERE match_id = {{MATCH_ID}}
      GROUP BY half, team, flag_name, event_time
   ) capture_events) AS unique_capture_events,
  (SELECT COUNT(*) FROM ktp_position_samples
    WHERE match_id = {{MATCH_ID}} AND half > 0) AS position_samples,
  (SELECT COUNT(*) FROM ktp_match_stats
    WHERE match_id = {{MATCH_ID}} AND half = 0) AS cached_player_totals,
  (SELECT COALESCE(SUM(kills), 0) FROM ktp_match_stats
    WHERE match_id = {{MATCH_ID}} AND half = 0) AS cached_kills,
  (SELECT COALESCE(SUM(deaths), 0) FROM ktp_match_stats
    WHERE match_id = {{MATCH_ID}} AND half = 0) AS cached_deaths;
