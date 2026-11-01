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
  -- Both counts exclude warmup bleed-through, matching what the report
  -- actually displays -- see capture_credit_fact.sql.
  (SELECT COUNT(*) FROM ktp_flag_captures c
    LEFT JOIN ktp_matches m ON m.match_id = c.match_id AND m.half = c.half
    WHERE c.match_id = {{MATCH_ID}}
      AND (m.start_time IS NULL OR c.event_time > m.start_time)) AS capture_credits,
  (SELECT COUNT(*) FROM (
      SELECT 1 FROM ktp_flag_captures c
      LEFT JOIN ktp_matches m ON m.match_id = c.match_id AND m.half = c.half
      WHERE c.match_id = {{MATCH_ID}}
        AND (m.start_time IS NULL OR c.event_time > m.start_time)
      GROUP BY c.half, c.team, c.flag_name, c.event_time
   ) capture_events) AS unique_capture_events,
  (SELECT COUNT(*) FROM ktp_position_samples
    WHERE match_id = {{MATCH_ID}} AND half > 0) AS position_samples,
  (SELECT COUNT(*) FROM ktp_match_stats
    WHERE match_id = {{MATCH_ID}} AND half = 0) AS cached_player_totals,
  (SELECT COALESCE(SUM(kills), 0) FROM ktp_match_stats
    WHERE match_id = {{MATCH_ID}} AND half = 0) AS cached_kills,
  (SELECT COALESCE(SUM(deaths), 0) FROM ktp_match_stats
    WHERE match_id = {{MATCH_ID}} AND half = 0) AS cached_deaths,
  -- Every hit the attacker landed: the ingest query groups ktp_damage_events
  -- by attacker_id with no victim join and no team predicate. So the report
  -- side comparable with it is damage_dealt + team_damage + self_damage.
  (SELECT COALESCE(SUM(damage), 0) FROM ktp_match_stats
    WHERE match_id = {{MATCH_ID}} AND half = 0) AS cached_damage,
  -- COUNT ignores NULL, and the daemon writes NULL for a half with no ledger
  -- rows -- so zero here is "no cached figure", not a cached zero.
  (SELECT COUNT(damage) FROM ktp_match_stats
    WHERE match_id = {{MATCH_ID}} AND half = 0) AS cached_damage_rows,
  -- A cache row for a player the roster no longer carries is in cached_damage
  -- and in no report row. ktp_match_players drives the ingest side, so
  -- this can only be a cache that outlived a roster row.
  (SELECT COALESCE(SUM(ms.damage), 0) FROM ktp_match_stats ms
    WHERE ms.match_id = {{MATCH_ID}} AND ms.half = 0
      AND NOT EXISTS (SELECT 1 FROM ktp_match_players mp
                       WHERE mp.match_id = ms.match_id
                         AND mp.player_id = ms.player_id)) AS cached_damage_off_roster,
  -- player_match_fact.sql reads both teams through LEFT JOIN roster, so an
  -- unresolvable team leaves `victim.team <> r.team` and `victim.team = r.team`
  -- both NULL: no arm fires and the hit reaches no column. <=> keeps a NULL
  -- victim_id in this count instead of dropping it three-valued.
  (SELECT COALESCE(SUM(d.damage_capped), 0) FROM ktp_damage_events d
     JOIN ktp_match_players a
       ON a.match_id = d.match_id AND a.player_id = d.attacker_id
    WHERE d.match_id = {{MATCH_ID}}
      AND NOT (d.victim_id <=> d.attacker_id)
      AND NOT EXISTS (SELECT 1 FROM ktp_match_players v
                       WHERE v.match_id = d.match_id
                         AND v.player_id = d.victim_id
                         AND v.team IS NOT NULL
                         AND a.team IS NOT NULL)) AS unpartitioned_damage_dealt,
  (SELECT COUNT(*) FROM ktp_damage_events d
     JOIN ktp_match_players a
       ON a.match_id = d.match_id AND a.player_id = d.attacker_id
    WHERE d.match_id = {{MATCH_ID}}
      AND NOT (d.victim_id <=> d.attacker_id)
      AND NOT EXISTS (SELECT 1 FROM ktp_match_players v
                       WHERE v.match_id = d.match_id
                         AND v.player_id = d.victim_id
                         AND v.team IS NOT NULL
                         AND a.team IS NOT NULL)) AS unpartitioned_hits_dealt,
  -- The mirror hole, through LEFT JOIN roster attacker. Same-team damage
  -- received is not unpartitioned: it is held on the attacker's team_damage.
  (SELECT COALESCE(SUM(d.damage_capped), 0) FROM ktp_damage_events d
     JOIN ktp_match_players v
       ON v.match_id = d.match_id AND v.player_id = d.victim_id
    WHERE d.match_id = {{MATCH_ID}}
      AND NOT (d.victim_id <=> d.attacker_id)
      AND NOT EXISTS (SELECT 1 FROM ktp_match_players a
                       WHERE a.match_id = d.match_id
                         AND a.player_id = d.attacker_id
                         AND a.team IS NOT NULL
                         AND v.team IS NOT NULL)) AS unpartitioned_damage_taken,
  (SELECT COUNT(*) FROM ktp_damage_events d
     JOIN ktp_match_players v
       ON v.match_id = d.match_id AND v.player_id = d.victim_id
    WHERE d.match_id = {{MATCH_ID}}
      AND NOT (d.victim_id <=> d.attacker_id)
      AND NOT EXISTS (SELECT 1 FROM ktp_match_players a
                       WHERE a.match_id = d.match_id
                         AND a.player_id = d.attacker_id
                         AND a.team IS NOT NULL
                         AND v.team IS NOT NULL)) AS unpartitioned_hits_taken;
