from __future__ import annotations

from tests.e2e_stats import assertions
from tests.e2e_stats.ephemeral_mysql import EphemeralMysql


def test_target_clock_gates_execute_against_mysql_and_ignore_legacy_rows(tmp_path):
    with EphemeralMysql.start(parent=tmp_path) as db:
        db.sql("""
CREATE TABLE ktp_matches (
  id INT AUTO_INCREMENT PRIMARY KEY, match_id VARCHAR(64), server_id INT,
  map_name VARCHAR(32), half TINYINT, start_time DATETIME, end_time DATETIME
);
CREATE TABLE hlstats_Events_Frags (
  id INT AUTO_INCREMENT PRIMARY KEY, serverId INT, map VARCHAR(32),
  match_id VARCHAR(64) NULL, half TINYINT, frag_context_recorded TINYINT,
  producer_match_id VARCHAR(64) NULL, producer_half TINYINT NULL,
  game_time DECIMAL(10,2) NULL, event_epoch BIGINT UNSIGNED NULL
);
CREATE TABLE ktp_damage_events (
  id INT AUTO_INCREMENT PRIMARY KEY, server_id INT,
  match_id VARCHAR(64) NULL, half TINYINT,
  producer_match_id VARCHAR(64) NULL, producer_half TINYINT NULL,
  game_time DECIMAL(10,2) NULL, event_epoch BIGINT UNSIGNED NULL
);
CREATE TABLE ktp_life_events (
  id INT AUTO_INCREMENT PRIMARY KEY, server_id INT, match_id VARCHAR(64),
  half TINYINT, map_name VARCHAR(32), boundary_kind VARCHAR(8),
  reason VARCHAR(16), team TINYINT, round_live TINYINT NULL,
  game_time DECIMAL(10,2), event_epoch BIGINT UNSIGNED, event_time DATETIME
);
INSERT INTO ktp_matches
  (match_id,server_id,map_name,half,start_time,end_time) VALUES
  ('clock-gate-TEST',2,'dod_anzio',1,
   '2026-08-19 20:00:00','2026-08-19 20:10:00');
INSERT INTO hlstats_Events_Frags
  (serverId,map,match_id,half,frag_context_recorded,producer_match_id,
   producer_half,game_time,event_epoch) VALUES
  (2,'dod_anzio','clock-gate-TEST',1,1,'clock-gate-TEST',1,60,
   UNIX_TIMESTAMP('2026-08-19 20:01:00')),
  (2,'dod_anzio',NULL,0,1,NULL,NULL,NULL,NULL);
INSERT INTO ktp_damage_events
  (server_id,match_id,half,producer_match_id,producer_half,game_time,event_epoch)
VALUES
  (2,'clock-gate-TEST',1,'clock-gate-TEST',1,60,
   UNIX_TIMESTAMP('2026-08-19 20:01:00')),
  (2,NULL,0,NULL,NULL,0,NULL);
INSERT INTO ktp_life_events
  (server_id,match_id,half,map_name,boundary_kind,reason,team,round_live,
   game_time,event_epoch,event_time) VALUES
  (2,'clock-gate-TEST',1,'dod_anzio','start','spawn',1,NULL,5,
   UNIX_TIMESTAMP('2026-08-19 20:00:05'),'2026-08-19 20:00:05'),
  (2,'clock-gate-TEST',1,'dod_anzio','end','death',1,NULL,60,
   UNIX_TIMESTAMP('2026-08-19 20:01:00'),'2026-08-19 20:01:00');
""")

        frag = assertions.check_frag_producer_clocks(
            db, emitted=1, match_id="clock-gate-TEST", half=1
        )
        damage = assertions.check_damage_producer_clocks(
            db, emitted=1, match_id="clock-gate-TEST", half=1
        )
        life = assertions.check_life_event_context(
            db, emitted=2, match_id="clock-gate-TEST", half=1
        )
        assert frag["status"] == damage["status"] == life["status"] == "ok"
        assert frag["candidate_rows"] == damage["candidate_rows"] == 1
        assert frag["clocked_rows"] == damage["clocked_rows"] == 1
        assert life["clocked_rows"] == 2

        db.sql("""
UPDATE hlstats_Events_Frags
SET event_epoch = UNIX_TIMESTAMP('2026-08-19 20:11:00')
WHERE producer_match_id = 'clock-gate-TEST';
UPDATE ktp_damage_events
SET game_time = NULL
WHERE producer_match_id = 'clock-gate-TEST';
UPDATE ktp_life_events
SET event_time = '2026-08-19 20:11:00',
    event_epoch = UNIX_TIMESTAMP('2026-08-19 20:11:00')
WHERE boundary_kind = 'end';
""")

        frag = assertions.check_frag_producer_clocks(
            db, emitted=1, match_id="clock-gate-TEST", half=1
        )
        damage = assertions.check_damage_producer_clocks(
            db, emitted=1, match_id="clock-gate-TEST", half=1
        )
        life = assertions.check_life_event_context(
            db, emitted=2, match_id="clock-gate-TEST", half=1
        )
        assert frag["status"] == "pipeline"
        assert frag["interval_mismatches"] == 1
        assert damage["status"] == "pipeline"
        assert damage["invalid_clocks"] == 1
        assert life["status"] == "pipeline"
        assert life["interval_mismatches"] == 1
