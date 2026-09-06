-- Credited cap participation per player: the share of the team's distinct
-- capture events in which the player received capture credit. Descriptive
-- only; "broke for it" participation needs zone-occupancy telemetry and is
-- deliberately not approximated here.
WITH caps AS (
    SELECT half, event_time, flag_name, team, player_id
    FROM ktp_flag_captures
    WHERE match_id = {{MATCH_ID}}
),
team_events AS (
    SELECT team,
           COUNT(DISTINCT CONCAT(half, '|', event_time, '|', flag_name))
               AS team_caps
    FROM caps
    GROUP BY team
),
player_events AS (
    SELECT player_id, team,
           COUNT(DISTINCT CONCAT(half, '|', event_time, '|', flag_name))
               AS caps_participated
    FROM caps
    GROUP BY player_id, team
)
SELECT
    p.player_id,
    r.player_name AS player_name_at_match,
    p.team,
    p.caps_participated,
    t.team_caps,
    ROUND(p.caps_participated / t.team_caps, 4) AS cap_participation
FROM player_events p
JOIN team_events t ON t.team = p.team
LEFT JOIN ktp_match_players r
  ON r.match_id = {{MATCH_ID}} AND r.player_id = p.player_id
ORDER BY p.team, cap_participation DESC, p.player_id;
