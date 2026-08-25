-- Canonical one-row-per-(match_id, player_id) descriptive match fact.
-- Read only. {{MATCH_ID}} is replaced with one safely quoted SQL literal by
-- scripts/match_analytics.py.
WITH
match_context AS (
    SELECT
        match_id,
        MAX(map_name) AS map_name,
        MIN(start_time) AS started_at,
        MAX(end_time) AS ended_at,
        SUM(CASE WHEN end_time IS NULL THEN 1 ELSE 0 END) AS open_halves,
        COUNT(*) AS halves_played,
        SUM(CASE WHEN end_time IS NULL THEN 0
                 ELSE GREATEST(TIMESTAMPDIFF(SECOND, start_time, end_time), 0)
            END) AS duration_seconds
    FROM ktp_matches
    WHERE match_id = {{MATCH_ID}}
    GROUP BY match_id
),
roster AS (
    SELECT match_id, player_id, steam_id, player_name, team
    FROM ktp_match_players
    WHERE match_id = {{MATCH_ID}}
),
kills AS (
    SELECT killerId AS player_id, COUNT(*) AS kills,
           COALESCE(SUM(headshot), 0) AS headshots
    FROM hlstats_Events_Frags
    WHERE match_id = {{MATCH_ID}}
    GROUP BY killerId
),
deaths AS (
    SELECT victimId AS player_id, COUNT(*) AS deaths
    FROM hlstats_Events_Frags
    WHERE match_id = {{MATCH_ID}}
    GROUP BY victimId
),
teamkills AS (
    SELECT killerId AS player_id, COUNT(*) AS team_kills
    FROM hlstats_Events_Teamkills
    WHERE match_id = {{MATCH_ID}}
    GROUP BY killerId
),
suicides AS (
    SELECT playerId AS player_id, COUNT(*) AS suicides
    FROM hlstats_Events_Suicides
    WHERE match_id = {{MATCH_ID}}
    GROUP BY playerId
),
assists AS (
    SELECT e.playerId AS player_id, COUNT(*) AS assists
    FROM hlstats_Events_PlayerPlayerActions e
    JOIN hlstats_Actions a ON a.id = e.actionId
    WHERE e.match_id = {{MATCH_ID}} AND a.game = 'dod' AND a.code = 'assist'
    GROUP BY e.playerId
),
breaks AS (
    SELECT e.playerId AS player_id, COUNT(*) AS cap_breaks
    FROM hlstats_Events_PlayerActions e
    JOIN hlstats_Actions a ON a.id = e.actionId
    WHERE e.match_id = {{MATCH_ID}} AND a.game = 'dod' AND a.code = 'cap_break'
    GROUP BY e.playerId
),
damage AS (
    SELECT
        r.player_id,
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
            WHEN d.attacker_id = r.player_id AND d.victim_id = r.player_id
                THEN d.damage_capped ELSE 0 END), 0) AS self_damage
    FROM roster r
    LEFT JOIN ktp_damage_events d
      ON d.match_id = r.match_id
     AND (d.attacker_id = r.player_id OR d.victim_id = r.player_id)
    LEFT JOIN roster attacker ON attacker.player_id = d.attacker_id
    LEFT JOIN roster victim ON victim.player_id = d.victim_id
    GROUP BY r.player_id
),
captures AS (
    SELECT player_id, COUNT(*) AS capture_credits
    FROM ktp_flag_captures
    WHERE match_id = {{MATCH_ID}}
    GROUP BY player_id
),
weapon_totals AS (
    SELECT playerId AS player_id, SUM(shots) AS shots, SUM(hits) AS hits
    FROM hlstats_Events_Statsme
    WHERE match_id = {{MATCH_ID}}
    GROUP BY playerId
),
position_coverage AS (
    SELECT player_id, COUNT(*) AS position_samples
    FROM ktp_position_samples
    WHERE match_id = {{MATCH_ID}} AND half > 0
    GROUP BY player_id
)
SELECT
    r.match_id,
    r.player_id,
    r.steam_id,
    r.player_name AS player_name_at_match,
    r.team,
    mc.map_name,
    mc.started_at,
    mc.ended_at,
    mc.duration_seconds,
    mc.halves_played,
    mc.open_halves,
    CASE WHEN r.match_id LIKE '%-TEST' THEN 1 ELSE 0 END AS is_test_match,
    COALESCE(k.kills, 0) AS kills,
    COALESCE(dth.deaths, 0) AS deaths,
    COALESCE(a.assists, 0) AS assists,
    COALESCE(k.headshots, 0) AS headshots,
    COALESCE(tk.team_kills, 0) AS team_kills,
    COALESCE(s.suicides, 0) AS suicides,
    COALESCE(dmg.damage_dealt, 0) AS damage_dealt,
    COALESCE(dmg.damage_taken, 0) AS damage_taken,
    COALESCE(dmg.team_damage, 0) AS team_damage,
    COALESCE(dmg.self_damage, 0) AS self_damage,
    COALESCE(c.capture_credits, 0) AS capture_credits,
    COALESCE(b.cap_breaks, 0) AS cap_breaks,
    COALESCE(w.shots, 0) AS shots,
    COALESCE(w.hits, 0) AS hits,
    COALESCE(p.position_samples, 0) AS position_samples,
    CASE WHEN COALESCE(dth.deaths, 0) = 0 THEN NULL
         ELSE ROUND(COALESCE(k.kills, 0) / dth.deaths, 3) END AS kd_ratio,
    CASE WHEN COALESCE(dth.deaths, 0) = 0 THEN NULL
         ELSE ROUND((COALESCE(k.kills, 0) + COALESCE(a.assists, 0)) / dth.deaths, 3)
         END AS kda_ratio,
    COALESCE(dmg.damage_dealt, 0) - COALESCE(dmg.damage_taken, 0)
        AS damage_differential,
    CASE WHEN mc.duration_seconds = 0 THEN NULL
         ELSE ROUND(COALESCE(dmg.damage_dealt, 0) * 60.0 / mc.duration_seconds, 2)
         END AS damage_per_minute,
    CASE WHEN COALESCE(dth.deaths, 0) = 0 THEN NULL
         ELSE ROUND(COALESCE(dmg.damage_dealt, 0) / dth.deaths, 2)
         END AS damage_per_life,
    CASE WHEN COALESCE(k.kills, 0) = 0 THEN NULL
         ELSE ROUND(COALESCE(k.headshots, 0) / k.kills, 3) END AS headshot_rate,
    CASE WHEN COALESCE(w.shots, 0) = 0 THEN NULL
         ELSE ROUND(w.hits / w.shots, 3) END AS raw_accuracy
FROM roster r
JOIN match_context mc ON mc.match_id = r.match_id
LEFT JOIN kills k ON k.player_id = r.player_id
LEFT JOIN deaths dth ON dth.player_id = r.player_id
LEFT JOIN teamkills tk ON tk.player_id = r.player_id
LEFT JOIN suicides s ON s.player_id = r.player_id
LEFT JOIN assists a ON a.player_id = r.player_id
LEFT JOIN breaks b ON b.player_id = r.player_id
LEFT JOIN damage dmg ON dmg.player_id = r.player_id
LEFT JOIN captures c ON c.player_id = r.player_id
LEFT JOIN weapon_totals w ON w.player_id = r.player_id
LEFT JOIN position_coverage p ON p.player_id = r.player_id
ORDER BY r.team, kills DESC, damage_dealt DESC, r.player_name;
