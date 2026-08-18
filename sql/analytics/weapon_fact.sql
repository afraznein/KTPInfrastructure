-- One row per match/player/weapon. Accuracy is raw and descriptive; do not use
-- it as a cross-role rating input (notably because of Garand reload clearing).
WITH
roster AS (
    SELECT match_id, player_id, player_name, team
    FROM ktp_match_players WHERE match_id = {{MATCH_ID}}
),
weapon_keys AS (
    SELECT playerId AS player_id,
           weapon COLLATE utf8mb4_unicode_ci AS weapon
      FROM hlstats_Events_Statsme
      WHERE match_id = {{MATCH_ID}}
    UNION
    SELECT playerId AS player_id,
           weapon COLLATE utf8mb4_unicode_ci AS weapon
      FROM hlstats_Events_Statsme2
      WHERE match_id = {{MATCH_ID}}
    UNION
    SELECT killerId AS player_id,
           weapon COLLATE utf8mb4_unicode_ci AS weapon
      FROM hlstats_Events_Frags
      WHERE match_id = {{MATCH_ID}}
    UNION
    SELECT attacker_id AS player_id,
           weapon COLLATE utf8mb4_unicode_ci AS weapon
      FROM ktp_damage_events
      WHERE match_id = {{MATCH_ID}}
),
sm AS (
    SELECT playerId AS player_id,
           weapon COLLATE utf8mb4_unicode_ci AS weapon,
           SUM(shots) AS shots, SUM(hits) AS hits,
           SUM(headshots) AS statsme_headshots, SUM(kills) AS statsme_kills,
           SUM(deaths) AS statsme_deaths, SUM(damage) AS statsme_damage
    FROM hlstats_Events_Statsme
    WHERE match_id = {{MATCH_ID}}
    GROUP BY playerId, weapon COLLATE utf8mb4_unicode_ci
),
sm2 AS (
    SELECT playerId AS player_id,
           weapon COLLATE utf8mb4_unicode_ci AS weapon,
           SUM(head) AS head, SUM(chest) AS chest, SUM(stomach) AS stomach,
           SUM(leftarm) + SUM(rightarm) AS arms,
           SUM(leftleg) + SUM(rightleg) AS legs
    FROM hlstats_Events_Statsme2
    WHERE match_id = {{MATCH_ID}}
    GROUP BY playerId, weapon COLLATE utf8mb4_unicode_ci
),
frag AS (
    SELECT killerId AS player_id,
           weapon COLLATE utf8mb4_unicode_ci AS weapon,
           COUNT(*) AS kills,
           SUM(headshot) AS headshot_kills
    FROM hlstats_Events_Frags
    WHERE match_id = {{MATCH_ID}}
    GROUP BY killerId, weapon COLLATE utf8mb4_unicode_ci
),
damage AS (
    SELECT de.attacker_id AS player_id,
           de.weapon COLLATE utf8mb4_unicode_ci AS weapon,
           SUM(CASE WHEN victim.team <> attacker.team
                    THEN de.damage_capped ELSE 0 END) AS damage_dealt
    FROM ktp_damage_events de
    JOIN roster attacker ON attacker.player_id = de.attacker_id
    JOIN roster victim ON victim.player_id = de.victim_id
    WHERE de.match_id = {{MATCH_ID}} AND de.attacker_id <> de.victim_id
    GROUP BY de.attacker_id, de.weapon COLLATE utf8mb4_unicode_ci
)
SELECT
    r.match_id,
    r.player_id,
    r.player_name AS player_name_at_match,
    r.team,
    wk.weapon,
    COALESCE(f.kills, 0) AS kills,
    COALESCE(f.headshot_kills, 0) AS headshot_kills,
    COALESCE(d.damage_dealt, 0) AS damage_dealt,
    COALESCE(sm.shots, 0) AS shots,
    COALESCE(sm.hits, 0) AS hits,
    CASE WHEN COALESCE(sm.shots, 0) = 0 THEN NULL
         ELSE ROUND(sm.hits / sm.shots, 3) END AS raw_accuracy,
    COALESCE(sm2.head, 0) AS head_hits,
    COALESCE(sm2.chest, 0) AS chest_hits,
    COALESCE(sm2.stomach, 0) AS stomach_hits,
    COALESCE(sm2.arms, 0) AS arm_hits,
    COALESCE(sm2.legs, 0) AS leg_hits,
    COALESCE(sm2.head, 0) + COALESCE(sm2.chest, 0)
      + COALESCE(sm2.stomach, 0) + COALESCE(sm2.arms, 0)
      + COALESCE(sm2.legs, 0) AS located_hits,
    COALESCE(sm.statsme_kills, 0) AS statsme_kills,
    COALESCE(sm.statsme_deaths, 0) AS statsme_deaths,
    COALESCE(sm.statsme_damage, 0) AS statsme_damage
FROM weapon_keys wk
JOIN roster r ON r.player_id = wk.player_id
LEFT JOIN sm ON sm.player_id = wk.player_id AND sm.weapon = wk.weapon
LEFT JOIN sm2 ON sm2.player_id = wk.player_id AND sm2.weapon = wk.weapon
LEFT JOIN frag f ON f.player_id = wk.player_id AND f.weapon = wk.weapon
LEFT JOIN damage d ON d.player_id = wk.player_id AND d.weapon = wk.weapon
ORDER BY r.team, r.player_name, kills DESC, damage_dealt DESC, wk.weapon;
