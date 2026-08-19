-- Deterministic query-contract fixture for scripts/match_analytics.py.
-- This is not a performance or bot-behaviour fixture. The older full Lane B
-- fixtures predate roster-width and bot StatsMe fixes; they remain useful for
-- proving the quality gate rejects incomplete source data.

CREATE TABLE ktp_matches (
  match_id varchar(64), server_id int, map_name varchar(32), half tinyint,
  match_type tinyint, start_time datetime, end_time datetime
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE ktp_match_players (
  match_id varchar(64), player_id int, steam_id varchar(64),
  player_name varchar(64), team tinyint, joined_at datetime
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE hlstats_Actions (
  id int, game varchar(32), code varchar(64)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE hlstats_Events_Frags (
  id int NOT NULL AUTO_INCREMENT PRIMARY KEY, eventTime datetime,
  match_id varchar(64), killerId int, victimId int, weapon varchar(64),
  headshot tinyint, half tinyint
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE hlstats_Events_Teamkills (
  match_id varchar(64), killerId int, victimId int
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE hlstats_Events_Suicides (
  match_id varchar(64), playerId int
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE hlstats_Events_PlayerPlayerActions (
  match_id varchar(64), playerId int, victimId int, actionId int
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE hlstats_Events_PlayerActions (
  match_id varchar(64), playerId int, actionId int
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE ktp_damage_events (
  match_id varchar(64), half tinyint, attacker_id int, victim_id int,
  weapon varchar(32), damage_capped int
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE ktp_flag_captures (
  match_id varchar(64), half tinyint, player_id int, team varchar(16),
  flag_name varchar(64), event_time datetime
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE hlstats_Events_Statsme (
  match_id varchar(64), half tinyint, playerId int, weapon varchar(64),
  shots int, hits int, headshots int, damage int, kills int, deaths int
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE hlstats_Events_Statsme2 (
  match_id varchar(64), playerId int, weapon varchar(64), head int, chest int,
  stomach int, leftarm int, rightarm int, leftleg int, rightleg int
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE ktp_position_samples (
  match_id varchar(64), half tinyint, player_id int
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE ktp_match_stats (
  match_id varchar(64), player_id int, half tinyint, kills int, deaths int
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE ktp_flag_state_events (
  id bigint NOT NULL AUTO_INCREMENT PRIMARY KEY, server_id int,
  match_id varchar(64), half tinyint, map_name varchar(32), flag_index tinyint,
  flag_name varchar(64), owner_team tinyint, is_initial tinyint,
  game_time decimal(10,2), event_time datetime
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO hlstats_Actions VALUES
  (1,'dod','assist'),(2,'dod','cap_break');
INSERT INTO ktp_matches VALUES
  ('phase-a-contract-TEST',2,'dod_anzio',1,0,'2026-08-16 20:00:00','2026-08-16 20:10:00'),
  ('phase-a-contract-TEST',2,'dod_anzio',2,0,'2026-08-16 20:11:00','2026-08-16 20:21:00');
INSERT INTO ktp_match_players VALUES
  ('phase-a-contract-TEST',1,'BOT:0001','Allies 1',1,'2026-08-16 20:00:00'),
  ('phase-a-contract-TEST',2,'BOT:0002','Allies 2',1,'2026-08-16 20:00:00'),
  ('phase-a-contract-TEST',3,'BOT:0003','Allies 3',1,'2026-08-16 20:00:00'),
  ('phase-a-contract-TEST',4,'BOT:0004','Allies 4',1,'2026-08-16 20:00:00'),
  ('phase-a-contract-TEST',5,'BOT:0005','Allies 5',1,'2026-08-16 20:00:00'),
  ('phase-a-contract-TEST',6,'BOT:0006','Allies 6',1,'2026-08-16 20:00:00'),
  ('phase-a-contract-TEST',7,'BOT:0007','Axis 1',2,'2026-08-16 20:00:00'),
  ('phase-a-contract-TEST',8,'BOT:0008','Axis 2',2,'2026-08-16 20:00:00'),
  ('phase-a-contract-TEST',9,'BOT:0009','Axis 3',2,'2026-08-16 20:00:00'),
  ('phase-a-contract-TEST',10,'BOT:0010','Axis 4',2,'2026-08-16 20:00:00'),
  ('phase-a-contract-TEST',11,'BOT:0011','Axis 5',2,'2026-08-16 20:00:00'),
  ('phase-a-contract-TEST',12,'BOT:0012','Axis 6',2,'2026-08-16 20:00:00');

INSERT INTO hlstats_Events_Frags
  (match_id, killerId, victimId, weapon, headshot, half) VALUES
  ('phase-a-contract-TEST',1,7,'garand',1,1),
  ('phase-a-contract-TEST',2,8,'garand',0,1),
  ('phase-a-contract-TEST',3,9,'thompson',0,1),
  ('phase-a-contract-TEST',4,10,'bar',1,1),
  ('phase-a-contract-TEST',5,11,'spring',1,1),
  ('phase-a-contract-TEST',6,12,'30cal',0,1),
  ('phase-a-contract-TEST',7,1,'k98',1,2),
  ('phase-a-contract-TEST',8,2,'k98',0,2),
  ('phase-a-contract-TEST',9,3,'mp40',0,2),
  ('phase-a-contract-TEST',10,4,'mp44',1,2),
  ('phase-a-contract-TEST',11,5,'scopedkar',1,2),
  ('phase-a-contract-TEST',12,6,'mg42',0,2);
UPDATE hlstats_Events_Frags
SET eventTime = DATE_ADD('2026-08-16 20:00:00', INTERVAL id * 20 SECOND);
INSERT INTO hlstats_Events_Teamkills VALUES
  ('phase-a-contract-TEST',1,2);
INSERT INTO hlstats_Events_Suicides VALUES
  ('phase-a-contract-TEST',2);
INSERT INTO hlstats_Events_PlayerPlayerActions VALUES
  ('phase-a-contract-TEST',2,7,1),
  ('phase-a-contract-TEST',3,8,1),
  ('phase-a-contract-TEST',9,1,1);
INSERT INTO hlstats_Events_PlayerActions VALUES
  ('phase-a-contract-TEST',4,2),
  ('phase-a-contract-TEST',10,2);

INSERT INTO ktp_damage_events VALUES
  ('phase-a-contract-TEST',1,1,7,'garand',100),
  ('phase-a-contract-TEST',1,2,8,'garand',80),
  ('phase-a-contract-TEST',1,3,9,'thompson',90),
  ('phase-a-contract-TEST',1,4,10,'bar',100),
  ('phase-a-contract-TEST',1,5,11,'spring',100),
  ('phase-a-contract-TEST',1,6,12,'30cal',70),
  ('phase-a-contract-TEST',2,7,1,'k98',100),
  ('phase-a-contract-TEST',2,8,2,'k98',80),
  ('phase-a-contract-TEST',2,9,3,'mp40',90),
  ('phase-a-contract-TEST',2,10,4,'mp44',100),
  ('phase-a-contract-TEST',2,11,5,'scopedkar',100),
  ('phase-a-contract-TEST',2,12,6,'mg42',70),
  ('phase-a-contract-TEST',1,1,2,'garand',20),
  ('phase-a-contract-TEST',1,3,3,'thompson',5);

INSERT INTO ktp_flag_captures VALUES
  ('phase-a-contract-TEST',1,1,'Allies','POINT_ANZIO_STREET','2026-08-16 20:05:00'),
  ('phase-a-contract-TEST',1,2,'Allies','POINT_ANZIO_STREET','2026-08-16 20:05:00'),
  ('phase-a-contract-TEST',2,8,'Axis','POINT_ANZIO_PLAZA','2026-08-16 20:16:00');

INSERT INTO hlstats_Events_Statsme VALUES
  ('phase-a-contract-TEST',1,1,'garand',20,8,2,100,1,1),
  ('phase-a-contract-TEST',1,2,'garand',22,7,0,80,1,1),
  ('phase-a-contract-TEST',1,3,'thompson',30,9,0,90,1,1),
  ('phase-a-contract-TEST',1,4,'bar',25,8,1,100,1,1),
  ('phase-a-contract-TEST',1,5,'spring',10,4,1,100,1,1),
  ('phase-a-contract-TEST',1,6,'30cal',40,7,0,70,1,1),
  ('phase-a-contract-TEST',2,7,'k98',18,8,2,100,1,1),
  ('phase-a-contract-TEST',2,8,'k98',20,7,0,80,1,1),
  ('phase-a-contract-TEST',2,9,'mp40',30,9,0,90,1,1),
  ('phase-a-contract-TEST',2,10,'mp44',25,8,1,100,1,1),
  ('phase-a-contract-TEST',2,11,'scopedkar',10,4,1,100,1,1),
  ('phase-a-contract-TEST',2,12,'mg42',40,7,0,70,1,1);
INSERT INTO hlstats_Events_Statsme2 VALUES
  ('phase-a-contract-TEST',1,'garand',2,3,1,1,1,0,0),
  ('phase-a-contract-TEST',2,'garand',0,3,2,1,0,1,0),
  ('phase-a-contract-TEST',3,'thompson',0,4,2,1,1,1,0),
  ('phase-a-contract-TEST',4,'bar',1,3,1,1,1,1,0),
  ('phase-a-contract-TEST',5,'spring',1,2,1,0,0,0,0),
  ('phase-a-contract-TEST',6,'30cal',0,3,1,1,1,1,0),
  ('phase-a-contract-TEST',7,'k98',2,3,1,1,1,0,0),
  ('phase-a-contract-TEST',8,'k98',0,3,2,1,0,1,0),
  ('phase-a-contract-TEST',9,'mp40',0,4,2,1,1,1,0),
  ('phase-a-contract-TEST',10,'mp44',1,3,1,1,1,1,0),
  ('phase-a-contract-TEST',11,'scopedkar',1,2,1,0,0,0,0),
  ('phase-a-contract-TEST',12,'mg42',0,3,1,1,1,1,0);

INSERT INTO ktp_position_samples VALUES
  ('phase-a-contract-TEST',1,1),('phase-a-contract-TEST',1,2),
  ('phase-a-contract-TEST',1,3),('phase-a-contract-TEST',1,4),
  ('phase-a-contract-TEST',1,5),('phase-a-contract-TEST',1,6),
  ('phase-a-contract-TEST',2,7),('phase-a-contract-TEST',2,8),
  ('phase-a-contract-TEST',2,9),('phase-a-contract-TEST',2,10),
  ('phase-a-contract-TEST',2,11),('phase-a-contract-TEST',2,12);
INSERT INTO ktp_match_stats VALUES
  ('phase-a-contract-TEST',1,0,1,1),('phase-a-contract-TEST',2,0,1,1),
  ('phase-a-contract-TEST',3,0,1,1),('phase-a-contract-TEST',4,0,1,1),
  ('phase-a-contract-TEST',5,0,1,1),('phase-a-contract-TEST',6,0,1,1),
  ('phase-a-contract-TEST',7,0,1,1),('phase-a-contract-TEST',8,0,1,1),
  ('phase-a-contract-TEST',9,0,1,1),('phase-a-contract-TEST',10,0,1,1),
  ('phase-a-contract-TEST',11,0,1,1),('phase-a-contract-TEST',12,0,1,1);

INSERT INTO ktp_flag_state_events
  (server_id,match_id,half,map_name,flag_index,flag_name,owner_team,is_initial,game_time,event_time)
VALUES
  (2,'phase-a-contract-TEST',1,'dod_anzio',0,'POINT_ANZIO_STREET',0,1,0,'2026-08-16 20:00:00'),
  (2,'phase-a-contract-TEST',1,'dod_anzio',0,'POINT_ANZIO_STREET',1,0,300,'2026-08-16 20:05:00'),
  (2,'phase-a-contract-TEST',2,'dod_anzio',0,'POINT_ANZIO_STREET',0,1,0,'2026-08-16 20:11:00'),
  (2,'phase-a-contract-TEST',2,'dod_anzio',0,'POINT_ANZIO_STREET',2,0,300,'2026-08-16 20:16:00');
