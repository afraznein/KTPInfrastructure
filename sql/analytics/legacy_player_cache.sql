-- Per-player damage for archives that predate ktp_damage_events.
--
-- Two sources, both returned, because neither is trustworthy on its own and the
-- caller has to be able to tell which. `ktp_match_stats` half=0 is a derived
-- sum (half0 == half1 + half2 on 288 of 288 S9 matches carrying both sources),
-- so a fault in either half row lands in it silently -- and one did: on every
-- match played 2026-03-11..03-18 the half=1 damage is booked twice, per player
-- at exactly 2.000x, while kills are correct. Statsme's half-2 damage agrees
-- with the cache on all 288, so Statsme is the reference where its own event
-- coverage corroborates it.
--
-- Kills come back alongside the damage as the coverage test: Statsme carrying
-- materially more frags than the cache means its rows span more than this
-- match (match_id reuse), and then neither source may be published.
--
-- `half > 0` on the Statsme side, deliberately: on `1.3-confirm-NY1`, the one
-- S9 match holding both half=0 and half>0 Statsme rows, `half > 0` reproduces
-- the cache total exactly (312,020) while including half=0 would add 93,437 of
-- another session's damage.
SELECT
    c.player_id,
    c.legacy_damage_dealt,
    c.legacy_kills,
    s.statsme_damage_dealt,
    s.statsme_frags
FROM (
    SELECT
        player_id,
        COALESCE(SUM(damage), 0) AS legacy_damage_dealt,
        COALESCE(SUM(kills), 0) AS legacy_kills
    FROM ktp_match_stats
    WHERE match_id = {{MATCH_ID}} AND half = 0
    GROUP BY player_id
) c
LEFT JOIN (
    SELECT
        playerId AS player_id,
        SUM(damage) AS statsme_damage_dealt,
        SUM(kills) AS statsme_frags
    FROM hlstats_Events_Statsme
    WHERE match_id = {{MATCH_ID}} AND half > 0
    GROUP BY playerId
) s ON s.player_id = c.player_id;
