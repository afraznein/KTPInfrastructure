-- One row per (match_id, player_id, half) for every closed half, carrying the
-- additive box-score columns of player_match_fact.sql split by half. Read only.
-- {{MATCH_ID}} is replaced with one safely quoted SQL literal by
-- scripts/match_analytics.py. Assists have no half column, so they are placed
-- by eventTime: a row belongs to the latest half that had started by then
-- (events carry a match_id only while a half is live). Cap breaks take their
-- producer half where the archive carries one (the BREAK_HALF token), else the
-- same eventTime placement.
WITH
halves AS (
    SELECT half, start_time, end_time,
           GREATEST(TIMESTAMPDIFF(SECOND, start_time, end_time), 0) AS duration_seconds
    FROM ktp_matches
    WHERE match_id = {{MATCH_ID}} AND half > 0 AND end_time IS NOT NULL
),
producer_coverage AS (
    -- Per half, as player_match_fact.sql: a producer with no event anywhere
    -- by the half's end did not exist for it, so its count is unknown.
    SELECT
        h.half,
        EXISTS(SELECT 1 FROM hlstats_Events_PlayerPlayerActions e
               JOIN hlstats_Actions a ON a.id = e.actionId
               WHERE a.game = 'dod' AND a.code = 'assist'
                 AND e.eventTime <= h.end_time) AS assists_covered,
        EXISTS(SELECT 1 FROM hlstats_Events_PlayerActions e
               JOIN hlstats_Actions a ON a.id = e.actionId
               WHERE a.game = 'dod' AND a.code = 'cap_break'
                 AND e.eventTime <= h.end_time) AS breaks_covered,
        EXISTS(SELECT 1 FROM ktp_flag_captures c
               WHERE c.event_time <= h.end_time) AS captures_covered
    FROM halves h
),
roster AS (
    SELECT match_id, player_id, player_name, team
    FROM ktp_match_players
    WHERE match_id = {{MATCH_ID}}
),
kills AS (
    SELECT killerId AS player_id, half, COUNT(*) AS kills,
           COALESCE(SUM(headshot), 0) AS headshots,
           SUM(CASE WHEN weapon IN ('grenade', 'grenade2', 'mills_bomb')
                    THEN 1 ELSE 0 END) AS grenade_kills
    FROM hlstats_Events_Frags
    WHERE match_id = {{MATCH_ID}}
    GROUP BY killerId, half
),
deaths AS (
    SELECT victimId AS player_id, half, COUNT(*) AS deaths
    FROM hlstats_Events_Frags
    WHERE match_id = {{MATCH_ID}}
    GROUP BY victimId, half
),
teamkills AS (
    SELECT killerId AS player_id, half, COUNT(*) AS team_kills
    FROM hlstats_Events_Teamkills
    WHERE match_id = {{MATCH_ID}}
    GROUP BY killerId, half
),
suicides AS (
    SELECT playerId AS player_id, half, COUNT(*) AS suicides
    FROM hlstats_Events_Suicides
    WHERE match_id = {{MATCH_ID}}
    GROUP BY playerId, half
),
assists AS (
    SELECT e.playerId AS player_id,
           (SELECT MAX(h.half) FROM halves h WHERE h.start_time <= e.eventTime) AS half,
           COUNT(*) AS assists
    FROM hlstats_Events_PlayerPlayerActions e
    JOIN hlstats_Actions a ON a.id = e.actionId
    WHERE e.match_id = {{MATCH_ID}} AND a.game = 'dod' AND a.code = 'assist'
    GROUP BY e.playerId, 2
),
breaks AS (
    SELECT e.playerId AS player_id,
           {{BREAK_HALF}} AS half,
           COUNT(*) AS cap_breaks
    FROM hlstats_Events_PlayerActions e
    JOIN hlstats_Actions a ON a.id = e.actionId
    WHERE e.match_id = {{MATCH_ID}} AND a.game = 'dod' AND a.code = 'cap_break'
    GROUP BY e.playerId, 2
),
damage AS (
    SELECT
        r.player_id, d.half,
        COALESCE(SUM(CASE
            WHEN d.attacker_id = r.player_id AND d.victim_id <> r.player_id
                 AND victim.team <> r.team THEN d.damage_capped ELSE 0 END), 0)
            AS damage_dealt,
        COALESCE(SUM(CASE
            WHEN d.victim_id = r.player_id AND d.attacker_id <> r.player_id
                 AND attacker.team <> r.team THEN d.damage_capped ELSE 0 END), 0)
            AS damage_taken,
        COALESCE(SUM(CASE
            WHEN d.attacker_id = r.player_id AND d.victim_id <> r.player_id
                 AND victim.team = r.team THEN d.damage_capped ELSE 0 END), 0)
            AS team_damage,
        COALESCE(SUM(CASE
            WHEN d.attacker_id = r.player_id AND d.victim_id <> r.player_id
                 AND victim.team <> r.team
                 AND d.weapon IN ('grenade', 'grenade2', 'mills_bomb')
                THEN d.damage_capped ELSE 0 END), 0) AS grenade_damage,
        COALESCE(SUM(CASE
            WHEN d.victim_id = r.player_id AND d.attacker_id <> r.player_id
                 AND attacker.team <> r.team
                 AND d.weapon IN ('grenade', 'grenade2', 'mills_bomb')
                THEN d.damage_capped ELSE 0 END), 0) AS grenade_damage_taken
    FROM roster r
    JOIN ktp_damage_events d
      ON d.match_id = r.match_id
     AND (d.attacker_id = r.player_id OR d.victim_id = r.player_id)
    LEFT JOIN roster attacker ON attacker.player_id = d.attacker_id
    LEFT JOIN roster victim ON victim.player_id = d.victim_id
    GROUP BY r.player_id, d.half
),
scores AS (
    -- Per-half objective points, updated directly by the daemon (see
    -- player_match_fact.sql's half=0 note for the semantics).
    SELECT player_id, half, score
    FROM ktp_match_stats
    WHERE match_id = {{MATCH_ID}} AND half > 0
),
captures AS (
    -- Excludes warmup bleed-through -- see capture_credit_fact.sql.
    SELECT c.player_id, c.half, COUNT(*) AS capture_credits
    FROM ktp_flag_captures c
    JOIN halves h ON h.half = c.half
    WHERE c.match_id = {{MATCH_ID}} AND c.event_time > h.start_time
    GROUP BY c.player_id, c.half
),
weapon_totals AS (
    SELECT playerId AS player_id, half, SUM(shots) AS shots, SUM(hits) AS hits
    FROM hlstats_Events_Statsme
    WHERE match_id = {{MATCH_ID}}
    GROUP BY playerId, half
),
presence AS (
    SELECT player_id, half, COUNT(*) AS position_samples
    FROM ktp_position_samples
    WHERE match_id = {{MATCH_ID}} AND half > 0
    GROUP BY player_id, half
)
SELECT
    r.player_id,
    r.player_name AS player_name_at_match,
    r.team,
    h.half,
    h.duration_seconds,
    COALESCE(k.kills, 0) AS kills,
    COALESCE(dth.deaths, 0) AS deaths,
    CASE WHEN pc.assists_covered THEN COALESCE(a.assists, 0) END AS assists,
    COALESCE(k.headshots, 0) AS headshots,
    COALESCE(k.grenade_kills, 0) AS grenade_kills,
    COALESCE(tk.team_kills, 0) AS team_kills,
    COALESCE(s.suicides, 0) AS suicides,
    COALESCE(dmg.damage_dealt, 0) AS damage_dealt,
    COALESCE(dmg.damage_taken, 0) AS damage_taken,
    COALESCE(dmg.team_damage, 0) AS team_damage,
    COALESCE(dmg.grenade_damage, 0) AS grenade_damage,
    COALESCE(dmg.grenade_damage_taken, 0) AS grenade_damage_taken,
    COALESCE(sc.score, 0) AS score,
    CASE WHEN h.duration_seconds = 0 THEN NULL
         ELSE ROUND(COALESCE(sc.score, 0) * 60.0 / h.duration_seconds, 3)
         END AS points_per_minute,
    CASE WHEN pc.captures_covered THEN COALESCE(c.capture_credits, 0) END
        AS capture_credits,
    CASE WHEN pc.breaks_covered THEN COALESCE(b.cap_breaks, 0) END AS cap_breaks,
    COALESCE(w.shots, 0) AS shots,
    COALESCE(w.hits, 0) AS hits,
    COALESCE(p.position_samples, 0) AS position_samples
FROM roster r
CROSS JOIN halves h
JOIN producer_coverage pc ON pc.half = h.half
LEFT JOIN kills k ON k.player_id = r.player_id AND k.half = h.half
LEFT JOIN deaths dth ON dth.player_id = r.player_id AND dth.half = h.half
LEFT JOIN teamkills tk ON tk.player_id = r.player_id AND tk.half = h.half
LEFT JOIN suicides s ON s.player_id = r.player_id AND s.half = h.half
LEFT JOIN assists a ON a.player_id = r.player_id AND a.half = h.half
LEFT JOIN breaks b ON b.player_id = r.player_id AND b.half = h.half
LEFT JOIN damage dmg ON dmg.player_id = r.player_id AND dmg.half = h.half
LEFT JOIN scores sc ON sc.player_id = r.player_id AND sc.half = h.half
LEFT JOIN captures c ON c.player_id = r.player_id AND c.half = h.half
LEFT JOIN weapon_totals w ON w.player_id = r.player_id AND w.half = h.half
LEFT JOIN presence p ON p.player_id = r.player_id AND p.half = h.half
ORDER BY h.half, r.team, kills DESC, r.player_name;
