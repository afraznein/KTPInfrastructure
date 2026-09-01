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
  match_id varchar(64), map varchar(64) NOT NULL DEFAULT 'dod_anzio',
  killerId int, victimId int, weapon varchar(64),
  headshot tinyint, half tinyint,
  killerRole varchar(64) NOT NULL DEFAULT '',
  victimRole varchar(64) NOT NULL DEFAULT '',
  pos_x mediumint DEFAULT NULL, pos_y mediumint DEFAULT NULL,
  pos_z mediumint DEFAULT NULL, pos_victim_x mediumint DEFAULT NULL,
  pos_victim_y mediumint DEFAULT NULL, pos_victim_z mediumint DEFAULT NULL,
  k_prone tinyint NOT NULL DEFAULT 0, v_prone tinyint NOT NULL DEFAULT 0,
  k_scope tinyint NOT NULL DEFAULT 0, v_scope tinyint NOT NULL DEFAULT 0,
  k_clip smallint NOT NULL DEFAULT -1, k_ammo smallint NOT NULL DEFAULT -1,
  v_clip smallint NOT NULL DEFAULT -1, v_ammo smallint NOT NULL DEFAULT -1,
  is_last_flag_defense tinyint NOT NULL DEFAULT 0,
  frag_context_recorded tinyint NOT NULL DEFAULT 0,
  producer_match_id varchar(64) DEFAULT NULL,
  producer_half tinyint DEFAULT NULL,
  game_time decimal(10,2) DEFAULT NULL,
  event_epoch bigint unsigned DEFAULT NULL
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE hlstats_Events_Teamkills (
  match_id varchar(64), killerId int, victimId int
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE hlstats_Events_Suicides (
  match_id varchar(64), playerId int
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE hlstats_Events_PlayerPlayerActions (
  id int NOT NULL AUTO_INCREMENT PRIMARY KEY, eventTime datetime,
  match_id varchar(64), playerId int, victimId int, actionId int
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE hlstats_Events_PlayerActions (
  match_id varchar(64), playerId int, actionId int
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE ktp_damage_events (
  id int NOT NULL AUTO_INCREMENT PRIMARY KEY, match_id varchar(64),
  half tinyint, attacker_id int, victim_id int, weapon varchar(32),
  damage_capped int, hitplace tinyint, game_time float, event_time datetime,
  producer_match_id varchar(64) DEFAULT NULL,
  producer_half tinyint DEFAULT NULL,
  event_epoch bigint unsigned DEFAULT NULL
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
  id int NOT NULL AUTO_INCREMENT PRIMARY KEY, match_id varchar(64),
  half tinyint, player_id int, team tinyint, pos_x mediumint,
  pos_y mediumint, pos_z mediumint, is_alive tinyint unsigned DEFAULT NULL,
  is_spectator tinyint unsigned DEFAULT NULL,
  map_revision_sha256 char(64) DEFAULT NULL,
  game_time float, event_time datetime
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE ktp_flag_positions (
  server_id int, map_name varchar(32), flag_index tinyint,
  flag_name varchar(64), origin_x mediumint, origin_y mediumint
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
CREATE TABLE ktp_life_events (
  id bigint unsigned NOT NULL AUTO_INCREMENT PRIMARY KEY,
  server_id int unsigned NOT NULL, match_id varchar(64) NOT NULL,
  half tinyint unsigned NOT NULL, map_name varchar(32) NOT NULL,
  player_id int NOT NULL, player_slot tinyint unsigned DEFAULT NULL,
  engine_userid int unsigned DEFAULT NULL, boundary_kind varchar(8) NOT NULL,
  reason varchar(16) NOT NULL, team tinyint unsigned NOT NULL,
  player_class tinyint unsigned DEFAULT NULL, round_live tinyint(1) DEFAULT NULL,
  game_time decimal(10,2) NOT NULL, event_epoch bigint unsigned NOT NULL,
  event_time datetime NOT NULL
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE ktp_assist_events (
  id bigint unsigned NOT NULL AUTO_INCREMENT PRIMARY KEY,
  server_id int unsigned NOT NULL, match_id varchar(64) NOT NULL,
  half tinyint unsigned NOT NULL, map_name varchar(32) NOT NULL,
  assister_id int NOT NULL, victim_id int NOT NULL,
  assister_pos_x mediumint DEFAULT NULL, assister_pos_y mediumint DEFAULT NULL,
  assister_pos_z mediumint DEFAULT NULL, victim_pos_x mediumint DEFAULT NULL,
  victim_pos_y mediumint DEFAULT NULL, victim_pos_z mediumint DEFAULT NULL,
  game_time decimal(10,2) NOT NULL, event_epoch bigint unsigned NOT NULL,
  event_time datetime NOT NULL, created_at timestamp DEFAULT CURRENT_TIMESTAMP
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
SET eventTime = DATE_ADD(
      IF(half = 1, '2026-08-16 20:00:00', '2026-08-16 20:11:00'),
      INTERVAL (((id - 1) % 6) + 1) * 20 SECOND
    ),
    producer_match_id = 'phase-a-contract-TEST', producer_half = half,
    game_time = (((id - 1) % 6) + 1) * 20,
    killerRole = 'rifleman', victimRole = 'rifleman',
    pos_x = id * 100, pos_y = id * 10, pos_z = 0,
    pos_victim_x = id * 100 + 300, pos_victim_y = id * 10 + 400,
    pos_victim_z = 0, k_clip = 4, k_ammo = 40;
UPDATE hlstats_Events_Frags
SET frag_context_recorded = 1, event_epoch = UNIX_TIMESTAMP(eventTime);
INSERT INTO hlstats_Events_Teamkills VALUES
  ('phase-a-contract-TEST',1,2);
INSERT INTO hlstats_Events_Suicides VALUES
  ('phase-a-contract-TEST',2);
INSERT INTO hlstats_Events_PlayerPlayerActions
  (eventTime,match_id,playerId,victimId,actionId) VALUES
  ('2026-08-16 20:00:20','phase-a-contract-TEST',2,7,1),
  ('2026-08-16 20:00:40','phase-a-contract-TEST',3,8,1),
  ('2026-08-16 20:11:20','phase-a-contract-TEST',9,1,1);
INSERT INTO hlstats_Events_PlayerActions VALUES
  ('phase-a-contract-TEST',4,2),
  ('phase-a-contract-TEST',10,2);

-- Canonical assist clocks are producer-authored. Generic action receipt rows
-- above remain the public box-score source, but are not used for life timing.
INSERT INTO ktp_assist_events
  (server_id,match_id,half,map_name,assister_id,victim_id,
   game_time,event_epoch,event_time)
VALUES
  (2,'phase-a-contract-TEST',1,'dod_anzio',2,7,15,
   UNIX_TIMESTAMP('2026-08-16 20:00:15'),'2026-08-16 20:00:15'),
  (2,'phase-a-contract-TEST',1,'dod_anzio',3,8,35,
   UNIX_TIMESTAMP('2026-08-16 20:00:35'),'2026-08-16 20:00:35'),
  (2,'phase-a-contract-TEST',2,'dod_anzio',9,1,15,
   UNIX_TIMESTAMP('2026-08-16 20:11:15'),'2026-08-16 20:11:15');

INSERT INTO ktp_damage_events
  (match_id,half,attacker_id,victim_id,weapon,damage_capped,hitplace,
   game_time,event_time,producer_match_id,producer_half,event_epoch) VALUES
  ('phase-a-contract-TEST',1,1,7,'garand',100,1,19,'2026-08-16 20:00:19','phase-a-contract-TEST',1,UNIX_TIMESTAMP('2026-08-16 20:00:19')),
  ('phase-a-contract-TEST',1,2,8,'garand',80,2,39,'2026-08-16 20:00:39','phase-a-contract-TEST',1,UNIX_TIMESTAMP('2026-08-16 20:00:39')),
  ('phase-a-contract-TEST',1,3,9,'thompson',90,2,59,'2026-08-16 20:00:59','phase-a-contract-TEST',1,UNIX_TIMESTAMP('2026-08-16 20:00:59')),
  ('phase-a-contract-TEST',1,4,10,'bar',100,1,79,'2026-08-16 20:01:19','phase-a-contract-TEST',1,UNIX_TIMESTAMP('2026-08-16 20:01:19')),
  ('phase-a-contract-TEST',1,5,11,'spring',100,1,99,'2026-08-16 20:01:39','phase-a-contract-TEST',1,UNIX_TIMESTAMP('2026-08-16 20:01:39')),
  ('phase-a-contract-TEST',1,6,12,'30cal',70,3,119,'2026-08-16 20:01:59','phase-a-contract-TEST',1,UNIX_TIMESTAMP('2026-08-16 20:01:59')),
  -- Stored half 1 simulates delayed receipt across halftime. Producer half 2
  -- is authoritative for every timed join and matches the death boundary.
  ('phase-a-contract-TEST',1,7,1,'k98',100,1,19,'2026-08-16 20:11:19','phase-a-contract-TEST',2,UNIX_TIMESTAMP('2026-08-16 20:11:19')),
  ('phase-a-contract-TEST',2,8,2,'k98',80,2,39,'2026-08-16 20:11:39','phase-a-contract-TEST',2,UNIX_TIMESTAMP('2026-08-16 20:11:39')),
  ('phase-a-contract-TEST',2,9,3,'mp40',90,2,59,'2026-08-16 20:11:59','phase-a-contract-TEST',2,UNIX_TIMESTAMP('2026-08-16 20:11:59')),
  ('phase-a-contract-TEST',2,10,4,'mp44',100,1,79,'2026-08-16 20:12:19','phase-a-contract-TEST',2,UNIX_TIMESTAMP('2026-08-16 20:12:19')),
  ('phase-a-contract-TEST',2,11,5,'scopedkar',100,1,99,'2026-08-16 20:12:39','phase-a-contract-TEST',2,UNIX_TIMESTAMP('2026-08-16 20:12:39')),
  ('phase-a-contract-TEST',2,12,6,'mg42',70,3,119,'2026-08-16 20:12:59','phase-a-contract-TEST',2,UNIX_TIMESTAMP('2026-08-16 20:12:59')),
  ('phase-a-contract-TEST',1,1,2,'garand',20,2,250,'2026-08-16 20:04:10','phase-a-contract-TEST',1,UNIX_TIMESTAMP('2026-08-16 20:04:10')),
  ('phase-a-contract-TEST',1,3,3,'thompson',5,2,251,'2026-08-16 20:04:11','phase-a-contract-TEST',1,UNIX_TIMESTAMP('2026-08-16 20:04:11'));

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

INSERT INTO ktp_position_samples
  (match_id,half,player_id,team,pos_x,pos_y,pos_z,game_time,event_time) VALUES
  ('phase-a-contract-TEST',1,1,1,110,100,0,100,'2026-08-16 20:01:40'),
  ('phase-a-contract-TEST',1,2,1,120,100,0,100,'2026-08-16 20:01:40'),
  ('phase-a-contract-TEST',1,3,1,130,100,0,100,'2026-08-16 20:01:40'),
  ('phase-a-contract-TEST',1,4,1,140,100,0,100,'2026-08-16 20:01:40'),
  ('phase-a-contract-TEST',1,5,1,150,100,0,100,'2026-08-16 20:01:40'),
  ('phase-a-contract-TEST',1,6,1,160,100,0,100,'2026-08-16 20:01:40'),
  ('phase-a-contract-TEST',2,7,2,90,100,0,100,'2026-08-16 20:12:40'),
  ('phase-a-contract-TEST',2,8,2,80,100,0,100,'2026-08-16 20:12:40'),
  ('phase-a-contract-TEST',2,9,2,70,100,0,100,'2026-08-16 20:12:40'),
  ('phase-a-contract-TEST',2,10,2,60,100,0,100,'2026-08-16 20:12:40'),
  ('phase-a-contract-TEST',2,11,2,50,100,0,100,'2026-08-16 20:12:40'),
  ('phase-a-contract-TEST',2,12,2,40,100,0,100,'2026-08-16 20:12:40');
INSERT INTO ktp_flag_positions VALUES
  (2,'dod_anzio',0,'POINT_ANZIO_STREET',100,100);
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

-- Physical life boundaries deliberately retain NULL round_live. The emitter
-- cannot truthfully observe MatchHandler's private DODX pause flag in v1.
INSERT INTO ktp_life_events
  (server_id,match_id,half,map_name,player_id,player_slot,engine_userid,
   boundary_kind,reason,team,player_class,round_live,game_time,event_epoch,event_time)
VALUES
  (2,'phase-a-contract-TEST',1,'dod_anzio',7,7,107,'start','spawn',2,1,NULL,5,UNIX_TIMESTAMP('2026-08-16 20:00:05'),'2026-08-16 20:00:05'),
  (2,'phase-a-contract-TEST',1,'dod_anzio',7,7,107,'end','death',2,1,NULL,20,UNIX_TIMESTAMP('2026-08-16 20:00:20'),'2026-08-16 20:00:20'),
  (2,'phase-a-contract-TEST',1,'dod_anzio',8,8,108,'start','spawn',2,1,NULL,5,UNIX_TIMESTAMP('2026-08-16 20:00:05'),'2026-08-16 20:00:05'),
  (2,'phase-a-contract-TEST',1,'dod_anzio',8,8,108,'end','death',2,1,NULL,40,UNIX_TIMESTAMP('2026-08-16 20:00:40'),'2026-08-16 20:00:40'),
  (2,'phase-a-contract-TEST',1,'dod_anzio',9,9,109,'start','spawn',2,1,NULL,5,UNIX_TIMESTAMP('2026-08-16 20:00:05'),'2026-08-16 20:00:05'),
  (2,'phase-a-contract-TEST',1,'dod_anzio',9,9,109,'end','death',2,1,NULL,60,UNIX_TIMESTAMP('2026-08-16 20:01:00'),'2026-08-16 20:01:00'),
  (2,'phase-a-contract-TEST',1,'dod_anzio',10,10,110,'start','spawn',2,1,NULL,5,UNIX_TIMESTAMP('2026-08-16 20:00:05'),'2026-08-16 20:00:05'),
  (2,'phase-a-contract-TEST',1,'dod_anzio',10,10,110,'end','death',2,1,NULL,80,UNIX_TIMESTAMP('2026-08-16 20:01:20'),'2026-08-16 20:01:20'),
  (2,'phase-a-contract-TEST',1,'dod_anzio',11,11,111,'start','spawn',2,1,NULL,5,UNIX_TIMESTAMP('2026-08-16 20:00:05'),'2026-08-16 20:00:05'),
  (2,'phase-a-contract-TEST',1,'dod_anzio',11,11,111,'end','death',2,1,NULL,100,UNIX_TIMESTAMP('2026-08-16 20:01:40'),'2026-08-16 20:01:40'),
  (2,'phase-a-contract-TEST',1,'dod_anzio',12,12,112,'start','spawn',2,1,NULL,5,UNIX_TIMESTAMP('2026-08-16 20:00:05'),'2026-08-16 20:00:05'),
  (2,'phase-a-contract-TEST',1,'dod_anzio',12,12,112,'end','death',2,1,NULL,120,UNIX_TIMESTAMP('2026-08-16 20:02:00'),'2026-08-16 20:02:00'),
  (2,'phase-a-contract-TEST',2,'dod_anzio',1,1,101,'start','spawn',1,1,NULL,5,UNIX_TIMESTAMP('2026-08-16 20:11:05'),'2026-08-16 20:11:05'),
  (2,'phase-a-contract-TEST',2,'dod_anzio',1,1,101,'end','death',1,1,NULL,20,UNIX_TIMESTAMP('2026-08-16 20:11:20'),'2026-08-16 20:11:20'),
  (2,'phase-a-contract-TEST',2,'dod_anzio',2,2,102,'start','spawn',1,1,NULL,5,UNIX_TIMESTAMP('2026-08-16 20:11:05'),'2026-08-16 20:11:05'),
  (2,'phase-a-contract-TEST',2,'dod_anzio',2,2,102,'end','death',1,1,NULL,40,UNIX_TIMESTAMP('2026-08-16 20:11:40'),'2026-08-16 20:11:40'),
  (2,'phase-a-contract-TEST',2,'dod_anzio',3,3,103,'start','spawn',1,1,NULL,5,UNIX_TIMESTAMP('2026-08-16 20:11:05'),'2026-08-16 20:11:05'),
  (2,'phase-a-contract-TEST',2,'dod_anzio',3,3,103,'end','death',1,1,NULL,60,UNIX_TIMESTAMP('2026-08-16 20:12:00'),'2026-08-16 20:12:00'),
  (2,'phase-a-contract-TEST',2,'dod_anzio',4,4,104,'start','spawn',1,1,NULL,5,UNIX_TIMESTAMP('2026-08-16 20:11:05'),'2026-08-16 20:11:05'),
  (2,'phase-a-contract-TEST',2,'dod_anzio',4,4,104,'end','death',1,1,NULL,80,UNIX_TIMESTAMP('2026-08-16 20:12:20'),'2026-08-16 20:12:20'),
  (2,'phase-a-contract-TEST',2,'dod_anzio',5,5,105,'start','spawn',1,1,NULL,5,UNIX_TIMESTAMP('2026-08-16 20:11:05'),'2026-08-16 20:11:05'),
  (2,'phase-a-contract-TEST',2,'dod_anzio',5,5,105,'end','death',1,1,NULL,100,UNIX_TIMESTAMP('2026-08-16 20:12:40'),'2026-08-16 20:12:40'),
  (2,'phase-a-contract-TEST',2,'dod_anzio',6,6,106,'start','spawn',1,1,NULL,5,UNIX_TIMESTAMP('2026-08-16 20:11:05'),'2026-08-16 20:11:05'),
  (2,'phase-a-contract-TEST',2,'dod_anzio',6,6,106,'end','death',1,1,NULL,120,UNIX_TIMESTAMP('2026-08-16 20:13:00'),'2026-08-16 20:13:00');
