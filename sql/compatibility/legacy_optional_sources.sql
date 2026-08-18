-- Compatibility objects for an OLD dump restored into an EPHEMERAL local DB.
-- Never apply this file to a shared or production database. These empty tables
-- let the canonical SELECTs run while source_coverage records that the original
-- archive did not contain the corresponding telemetry.
-- SELECT ... WHERE 0 deliberately inherits match_id's exact character set and
-- collation from the archive. Hard-coding the current default breaks older
-- MySQL 8 dumps when they are restored under MariaDB.
CREATE TABLE IF NOT EXISTS ktp_damage_events AS
SELECT match_id, player_id AS attacker_id, player_id AS victim_id,
       CAST('' AS CHAR(64)) AS weapon, 0 AS damage_capped, 0 AS half
FROM ktp_match_players WHERE 0;
CREATE TABLE IF NOT EXISTS ktp_flag_captures AS
SELECT match_id, player_id, 0 AS half, team, CAST('' AS CHAR(64)) AS flag_name,
       joined_at AS event_time
FROM ktp_match_players WHERE 0;
CREATE TABLE IF NOT EXISTS ktp_position_samples AS
SELECT match_id, player_id, 0 AS half
FROM ktp_match_players WHERE 0;
