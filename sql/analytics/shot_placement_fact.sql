-- Crosshair placement on ALL shots, computed (shadow, coarse). One row per
-- roster player who fired. Read only; {{MATCH_ID}} is replaced with one
-- safely quoted SQL literal by scripts/match_analytics.py.
--
-- Per hitscan shot in ktp_shot_events: the angle between the shooter's view
-- vector (yaw/pitch = v.v_angle, migration 027) and the vector to each alive
-- enemy's nearest-in-time position sample (ktp_position_samples, 2 s cadence,
-- window +/-1.0 s); the shot's placement error is the smallest such angle --
-- the enemy the shooter was most plausibly engaging. Coarse by construction:
-- an enemy can move ~200 units in a second, so treat this as a distribution,
-- never a per-shot verdict. "Precision on hits" (ktp_ac_weapon_fires.err_udeg)
-- is the exact complement for shots that hit a hitbox; see ac_precision_fact.
--
-- GoldSrc angles: yaw counter-clockwise from +x, pitch positive = looking
-- DOWN, so forward = (cos p cos y, cos p sin y, -sin p). Both origins are
-- entity origins, so the eye-height offset cancels to first order.
WITH
roster AS (
    SELECT player_id, team
    FROM ktp_match_players
    WHERE match_id = {{MATCH_ID}}
),
shots AS (
    SELECT s.id AS shot_id, s.match_id, s.player_id, s.half, s.game_time,
           s.pos_x, s.pos_y, s.pos_z,
           COS(RADIANS(s.pitch)) * COS(RADIANS(s.yaw)) AS fx,
           COS(RADIANS(s.pitch)) * SIN(RADIANS(s.yaw)) AS fy,
           -SIN(RADIANS(s.pitch)) AS fz,
           r.team
    FROM ktp_shot_events s
    JOIN roster r ON r.player_id = s.player_id
    WHERE s.match_id = {{MATCH_ID}} AND s.half > 0
),
candidates AS (
    SELECT sh.shot_id, sh.player_id,
           DEGREES(ACOS(LEAST(1.0, GREATEST(-1.0,
               (sh.fx * (p.pos_x - sh.pos_x) + sh.fy * (p.pos_y - sh.pos_y)
                + sh.fz * (p.pos_z - sh.pos_z))
               / NULLIF(SQRT(POW(p.pos_x - sh.pos_x, 2) + POW(p.pos_y - sh.pos_y, 2)
                             + POW(p.pos_z - sh.pos_z, 2)), 0)
           )))) AS err_deg,
           ABS(p.game_time - sh.game_time) AS dt
    FROM shots sh
    JOIN ktp_position_samples p
      -- Bounds, not equalities: an equality lets MySQL pick a ref on (match_id, half)
      -- and scan the whole half per shot; bounds force a per-shot range on game_time.
      ON p.match_id >= sh.match_id AND p.match_id <= sh.match_id
     AND p.half >= sh.half AND p.half <= sh.half
     AND p.team <> sh.team AND p.is_alive = 1
     AND p.game_time BETWEEN sh.game_time - 1.0 AND sh.game_time + 1.0
),
per_shot AS (
    SELECT shot_id, player_id, MIN(err_deg) AS err_deg
    FROM candidates
    GROUP BY shot_id, player_id
)
SELECT
    player_id,
    COUNT(*) AS placement_shots,
    ROUND(AVG(err_deg), 2) AS placement_avg_deg,
    ROUND(100.0 * SUM(err_deg < 5) / COUNT(*), 1) AS placement_under5_pct,
    ROUND(100.0 * SUM(err_deg < 15) / COUNT(*), 1) AS placement_under15_pct
FROM per_shot
GROUP BY player_id
ORDER BY player_id
