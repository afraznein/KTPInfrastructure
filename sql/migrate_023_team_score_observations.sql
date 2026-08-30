-- KTP Infrastructure Migration 023: settled observer team-score ledger.
-- Import, projection, and retention serialize on ktp_team_score_ledger_v1.

CREATE TABLE IF NOT EXISTS `ktp_team_score_ingest_manifests` (
  `match_id` VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `map_name` VARCHAR(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `match_type` TINYINT UNSIGNED NOT NULL,
  `source_server` VARCHAR(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `observer_started_at` DATETIME(3) NOT NULL,
  `observer_ended_at` DATETIME(3) NOT NULL,
  `terminal_half` SMALLINT UNSIGNED NOT NULL,
  `event_count` BIGINT UNSIGNED NOT NULL,
  `official_row_count` INT UNSIGNED NOT NULL,
  `retained_row_count` INT UNSIGNED NOT NULL,
  `lifecycle_complete` TINYINT UNSIGNED NOT NULL,
  `settlement_seconds` SMALLINT UNSIGNED NOT NULL,
  `events_file_sha256` BINARY(32) NOT NULL,
  `metadata_file_sha256` BINARY(32) NOT NULL,
  `events_path_sha256` BINARY(32) NOT NULL,
  `metadata_path_sha256` BINARY(32) NOT NULL,
  `manifest_content_sha256` BINARY(32) NOT NULL,
  `match_end_allies_score` INT UNSIGNED NULL,
  `match_end_axis_score` INT UNSIGNED NULL,
  `retention_class` ENUM('retained','ephemeral-14d') NOT NULL,
  `ingested_at` TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`match_id`),
  UNIQUE KEY `uq_team_score_events_path` (`events_path_sha256`),
  UNIQUE KEY `uq_team_score_metadata_path` (`metadata_path_sha256`),
  KEY `idx_team_score_manifest_retention` (`retention_class`,`match_id`),
  CONSTRAINT `chk_team_score_terminal_half`
    CHECK (`terminal_half` IN (1,2) OR `terminal_half` >= 101),
  CONSTRAINT `chk_team_score_lifecycle_complete` CHECK (`lifecycle_complete` = 1),
  CONSTRAINT `chk_team_score_settlement` CHECK (`settlement_seconds` >= 30)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
COMMENT='Closed settled observer-file identity and finality evidence';

CREATE TABLE IF NOT EXISTS `ktp_team_score_observations` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `match_id` VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `map_name` VARCHAR(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `match_type` TINYINT UNSIGNED NOT NULL,
  `half` SMALLINT UNSIGNED NOT NULL,
  `tick_seconds` DECIMAL(20,9) UNSIGNED NOT NULL,
  `event_sequence` BIGINT UNSIGNED NOT NULL,
  `observed_at` DATETIME(3) NULL,
  `allies_score` INT UNSIGNED NOT NULL,
  `axis_score` INT UNSIGNED NOT NULL,
  `allies_team_id` TINYINT UNSIGNED NOT NULL,
  `axis_team_id` TINYINT UNSIGNED NOT NULL,
  `source_server` VARCHAR(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `source` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `source_version` SMALLINT UNSIGNED NOT NULL,
  `observation_kind` ENUM('baseline','change','final') NOT NULL,
  `retention_class` ENUM('retained','ephemeral-14d') NOT NULL,
  `manifest_content_sha256` BINARY(32) NOT NULL,
  `raw_event_json` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `raw_event_sha256` BINARY(32) NOT NULL,
  `source_file_sha256` BINARY(32) NOT NULL,
  `source_path_sha256` BINARY(32) NOT NULL,
  `source_line_number` BIGINT UNSIGNED NOT NULL,
  `ingested_at` TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_team_score_order` (`match_id`,`half`,`tick_seconds`,`event_sequence`),
  KEY `idx_team_score_match_order` (`match_id`,`half`,`tick_seconds`,`event_sequence`),
  KEY `idx_team_score_retention` (`retention_class`,`match_id`),
  CONSTRAINT `fk_team_score_observation_manifest` FOREIGN KEY (`match_id`)
    REFERENCES `ktp_team_score_ingest_manifests` (`match_id`)
    ON UPDATE RESTRICT ON DELETE RESTRICT,
  CONSTRAINT `chk_team_score_side_ids`
    CHECK (`allies_team_id` IN (1,2) AND `axis_team_id` IN (1,2)
           AND `allies_team_id` <> `axis_team_id`),
  CONSTRAINT `chk_team_score_half` CHECK (`half` IN (1,2) OR `half` >= 101),
  CONSTRAINT `chk_team_score_source_version` CHECK (`source_version` = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
COMMENT='Append-only official engine team-score observations';

CREATE TABLE IF NOT EXISTS `ktp_team_score_ingest_conflicts` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `match_id` VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `half` SMALLINT UNSIGNED NOT NULL,
  `tick_seconds` DECIMAL(20,9) UNSIGNED NOT NULL,
  `event_sequence` BIGINT UNSIGNED NOT NULL,
  `manifest_content_sha256` BINARY(32) NOT NULL,
  `incumbent_raw_sha256` BINARY(32) NOT NULL,
  `rejected_raw_sha256` BINARY(32) NOT NULL,
  `incumbent_raw_event_json` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `rejected_raw_event_json` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `source_file_sha256` BINARY(32) NOT NULL,
  `source_path_sha256` BINARY(32) NOT NULL,
  `source_line_number` BIGINT UNSIGNED NOT NULL,
  `conflict_kind` ENUM('batch','existing') NOT NULL,
  `detected_at` TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_team_score_conflict`
    (`match_id`,`half`,`tick_seconds`,`event_sequence`,
     `incumbent_raw_sha256`,`rejected_raw_sha256`),
  KEY `idx_team_score_conflict_match`
    (`match_id`,`half`,`tick_seconds`,`event_sequence`),
  CONSTRAINT `fk_team_score_conflict_manifest` FOREIGN KEY (`match_id`)
    REFERENCES `ktp_team_score_ingest_manifests` (`match_id`)
    ON UPDATE RESTRICT ON DELETE RESTRICT,
  CONSTRAINT `chk_team_score_conflict_hashes`
    CHECK (`incumbent_raw_sha256` <> `rejected_raw_sha256`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
COMMENT='Durable rejected team-score order-key variants';

CREATE TABLE IF NOT EXISTS `ktp_team_score_ingest_audits` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `match_id` VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `audit_kind` ENUM('manifest-mismatch','path-reuse','context-mismatch') NOT NULL,
  `accepted_match_id` VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL,
  `accepted_manifest_sha256` BINARY(32) NULL,
  `attempted_manifest_sha256` BINARY(32) NOT NULL,
  `attempted_events_file_sha256` BINARY(32) NOT NULL,
  `attempted_metadata_file_sha256` BINARY(32) NOT NULL,
  `attempted_events_path_sha256` BINARY(32) NOT NULL,
  `attempted_metadata_path_sha256` BINARY(32) NOT NULL,
  `map_name` VARCHAR(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `source_server` VARCHAR(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `match_type` TINYINT UNSIGNED NOT NULL,
  `terminal_half` SMALLINT UNSIGNED NOT NULL,
  `event_count` BIGINT UNSIGNED NOT NULL,
  `official_row_count` INT UNSIGNED NOT NULL,
  `detected_at` TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_team_score_ingest_audit`
    (`match_id`,`audit_kind`,`attempted_manifest_sha256`,
     `attempted_events_path_sha256`,`attempted_metadata_path_sha256`),
  KEY `idx_team_score_ingest_audit_match` (`match_id`,`detected_at`),
  CONSTRAINT `chk_team_score_audit_terminal_half`
    CHECK (`terminal_half` IN (1,2) OR `terminal_half` >= 101)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
COMMENT='Durable rejected manifest/path/context attempts; deliberately no parent FK';

-- CREATE TABLE IF NOT EXISTS cannot validate a partial pre-existing table.
-- Fail before repair unless all required columns, collations, primary keys,
-- and existing named/extra unique indexes are compatible. A wholly missing
-- named index is repaired after the preflight.

SET @m23_manifest_columns := (
 SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE()
 AND TABLE_NAME='ktp_team_score_ingest_manifests' AND COLUMN_NAME IN
 ('match_id','map_name','match_type','source_server','observer_started_at',
 'observer_ended_at','terminal_half','event_count','official_row_count',
 'retained_row_count',
 'lifecycle_complete','settlement_seconds','events_file_sha256',
 'metadata_file_sha256','events_path_sha256','metadata_path_sha256',
 'manifest_content_sha256','match_end_allies_score','match_end_axis_score',
 'retention_class','ingested_at'));
SET @m23_manifest_total_columns := (
 SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE()
 AND TABLE_NAME='ktp_team_score_ingest_manifests');
SET @m23_manifest_bad := (
 SELECT COALESCE(SUM(CASE COLUMN_NAME
 WHEN 'match_id' THEN NOT(DATA_TYPE='varchar' AND CHARACTER_MAXIMUM_LENGTH=64 AND COLLATION_NAME='utf8mb4_bin' AND IS_NULLABLE='NO')
 WHEN 'map_name' THEN NOT(DATA_TYPE='varchar' AND CHARACTER_MAXIMUM_LENGTH=32 AND COLLATION_NAME='utf8mb4_bin' AND IS_NULLABLE='NO')
 WHEN 'match_type' THEN NOT(DATA_TYPE='tinyint' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='NO')
 WHEN 'source_server' THEN NOT(DATA_TYPE='varchar' AND CHARACTER_MAXIMUM_LENGTH=128 AND COLLATION_NAME='utf8mb4_bin' AND IS_NULLABLE='NO')
 WHEN 'observer_started_at' THEN NOT(DATA_TYPE='datetime' AND DATETIME_PRECISION=3 AND IS_NULLABLE='NO')
 WHEN 'observer_ended_at' THEN NOT(DATA_TYPE='datetime' AND DATETIME_PRECISION=3 AND IS_NULLABLE='NO')
 WHEN 'terminal_half' THEN NOT(DATA_TYPE='smallint' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='NO')
 WHEN 'event_count' THEN NOT(DATA_TYPE='bigint' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='NO')
 WHEN 'official_row_count' THEN NOT(DATA_TYPE='int' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='NO')
 WHEN 'retained_row_count' THEN NOT(DATA_TYPE='int' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='NO')
 WHEN 'lifecycle_complete' THEN NOT(DATA_TYPE='tinyint' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='NO')
 WHEN 'settlement_seconds' THEN NOT(DATA_TYPE='smallint' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='NO')
 WHEN 'events_file_sha256' THEN NOT(DATA_TYPE='binary' AND CHARACTER_MAXIMUM_LENGTH=32 AND IS_NULLABLE='NO')
 WHEN 'metadata_file_sha256' THEN NOT(DATA_TYPE='binary' AND CHARACTER_MAXIMUM_LENGTH=32 AND IS_NULLABLE='NO')
 WHEN 'events_path_sha256' THEN NOT(DATA_TYPE='binary' AND CHARACTER_MAXIMUM_LENGTH=32 AND IS_NULLABLE='NO')
 WHEN 'metadata_path_sha256' THEN NOT(DATA_TYPE='binary' AND CHARACTER_MAXIMUM_LENGTH=32 AND IS_NULLABLE='NO')
 WHEN 'manifest_content_sha256' THEN NOT(DATA_TYPE='binary' AND CHARACTER_MAXIMUM_LENGTH=32 AND IS_NULLABLE='NO')
 WHEN 'match_end_allies_score' THEN NOT(DATA_TYPE='int' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='YES')
 WHEN 'match_end_axis_score' THEN NOT(DATA_TYPE='int' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='YES')
 WHEN 'retention_class' THEN NOT(COLUMN_TYPE='enum(''retained'',''ephemeral-14d'')' AND IS_NULLABLE='NO')
 WHEN 'ingested_at' THEN NOT(DATA_TYPE='timestamp' AND DATETIME_PRECISION=3 AND IS_NULLABLE='NO')
 ELSE 0 END),0) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE()
 AND TABLE_NAME='ktp_team_score_ingest_manifests');
SET @m23_manifest_table := (SELECT COUNT(*)=1 FROM information_schema.TABLES
 WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ktp_team_score_ingest_manifests'
 AND ENGINE='InnoDB' AND TABLE_COLLATION='utf8mb4_bin');
SET @m23_manifest_primary := (SELECT COUNT(*)=1 AND MIN(NON_UNIQUE)=0 AND
 GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX)='match_id' AND SUM(SUB_PART IS NOT NULL)=0
 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE()
 AND TABLE_NAME='ktp_team_score_ingest_manifests' AND INDEX_NAME='PRIMARY');
SET @m23_manifest_bad_named := (SELECT COUNT(*) FROM (
 SELECT INDEX_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE()
 AND TABLE_NAME='ktp_team_score_ingest_manifests' AND INDEX_NAME IN
 ('uq_team_score_events_path','uq_team_score_metadata_path','idx_team_score_manifest_retention')
 GROUP BY INDEX_NAME HAVING NOT (
 (INDEX_NAME='uq_team_score_events_path' AND MIN(NON_UNIQUE)=0 AND COUNT(*)=1 AND GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX)='events_path_sha256' AND SUM(SUB_PART IS NOT NULL)=0) OR
 (INDEX_NAME='uq_team_score_metadata_path' AND MIN(NON_UNIQUE)=0 AND COUNT(*)=1 AND GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX)='metadata_path_sha256' AND SUM(SUB_PART IS NOT NULL)=0) OR
 (INDEX_NAME='idx_team_score_manifest_retention' AND MIN(NON_UNIQUE)=1 AND COUNT(*)=2 AND GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX)='retention_class,match_id' AND SUM(SUB_PART IS NOT NULL)=0))) bad_i);
SET @m23_manifest_extra_unique := (SELECT COUNT(*) FROM (
 SELECT INDEX_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE()
 AND TABLE_NAME='ktp_team_score_ingest_manifests' AND NON_UNIQUE=0
 AND INDEX_NAME NOT IN ('PRIMARY','uq_team_score_events_path','uq_team_score_metadata_path')
 GROUP BY INDEX_NAME) extra_i);
SET @m23_ok := (@m23_manifest_columns=21 AND @m23_manifest_total_columns=21 AND @m23_manifest_bad=0 AND
 @m23_manifest_table=1 AND @m23_manifest_primary=1 AND
 @m23_manifest_bad_named=0 AND @m23_manifest_extra_unique=0);
SET @m23_ddl := IF(@m23_ok,'DO 0','SELECT * FROM ERROR_023_team_score_manifest_partial_or_incompatible');
PREPARE m23_stmt FROM @m23_ddl; EXECUTE m23_stmt; DEALLOCATE PREPARE m23_stmt;

SET @m23_observation_columns := (SELECT COUNT(*) FROM information_schema.COLUMNS
 WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ktp_team_score_observations'
 AND COLUMN_NAME IN ('id','match_id','map_name','match_type','half','tick_seconds',
 'event_sequence','observed_at','allies_score','axis_score','allies_team_id',
 'axis_team_id','source_server','source','source_version','observation_kind',
 'retention_class','manifest_content_sha256','raw_event_json','raw_event_sha256',
 'source_file_sha256','source_path_sha256','source_line_number','ingested_at'));
SET @m23_observation_total_columns := (SELECT COUNT(*) FROM information_schema.COLUMNS
 WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ktp_team_score_observations');
SET @m23_observation_bad := (SELECT COALESCE(SUM(CASE COLUMN_NAME
 WHEN 'id' THEN NOT(DATA_TYPE='bigint' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND LOCATE('auto_increment',EXTRA)>0 AND IS_NULLABLE='NO')
 WHEN 'match_id' THEN NOT(DATA_TYPE='varchar' AND CHARACTER_MAXIMUM_LENGTH=64 AND COLLATION_NAME='utf8mb4_bin' AND IS_NULLABLE='NO')
 WHEN 'map_name' THEN NOT(DATA_TYPE='varchar' AND CHARACTER_MAXIMUM_LENGTH=32 AND COLLATION_NAME='utf8mb4_bin' AND IS_NULLABLE='NO')
 WHEN 'match_type' THEN NOT(DATA_TYPE='tinyint' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='NO')
 WHEN 'half' THEN NOT(DATA_TYPE='smallint' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='NO')
 WHEN 'tick_seconds' THEN NOT(DATA_TYPE='decimal' AND NUMERIC_PRECISION=20 AND NUMERIC_SCALE=9 AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='NO')
 WHEN 'event_sequence' THEN NOT(DATA_TYPE='bigint' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='NO')
 WHEN 'observed_at' THEN NOT(DATA_TYPE='datetime' AND DATETIME_PRECISION=3 AND IS_NULLABLE='YES')
 WHEN 'allies_score' THEN NOT(DATA_TYPE='int' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='NO')
 WHEN 'axis_score' THEN NOT(DATA_TYPE='int' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='NO')
 WHEN 'allies_team_id' THEN NOT(DATA_TYPE='tinyint' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='NO')
 WHEN 'axis_team_id' THEN NOT(DATA_TYPE='tinyint' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='NO')
 WHEN 'source_server' THEN NOT(DATA_TYPE='varchar' AND CHARACTER_MAXIMUM_LENGTH=128 AND COLLATION_NAME='utf8mb4_bin' AND IS_NULLABLE='NO')
 WHEN 'source' THEN NOT(DATA_TYPE='varchar' AND CHARACTER_MAXIMUM_LENGTH=64 AND COLLATION_NAME='ascii_bin' AND IS_NULLABLE='NO')
 WHEN 'source_version' THEN NOT(DATA_TYPE='smallint' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='NO')
 WHEN 'observation_kind' THEN NOT(COLUMN_TYPE='enum(''baseline'',''change'',''final'')' AND IS_NULLABLE='NO')
 WHEN 'retention_class' THEN NOT(COLUMN_TYPE='enum(''retained'',''ephemeral-14d'')' AND IS_NULLABLE='NO')
 WHEN 'manifest_content_sha256' THEN NOT(DATA_TYPE='binary' AND CHARACTER_MAXIMUM_LENGTH=32 AND IS_NULLABLE='NO')
 WHEN 'raw_event_json' THEN NOT(DATA_TYPE='longtext' AND COLLATION_NAME='utf8mb4_bin' AND IS_NULLABLE='NO')
 WHEN 'raw_event_sha256' THEN NOT(DATA_TYPE='binary' AND CHARACTER_MAXIMUM_LENGTH=32 AND IS_NULLABLE='NO')
 WHEN 'source_file_sha256' THEN NOT(DATA_TYPE='binary' AND CHARACTER_MAXIMUM_LENGTH=32 AND IS_NULLABLE='NO')
 WHEN 'source_path_sha256' THEN NOT(DATA_TYPE='binary' AND CHARACTER_MAXIMUM_LENGTH=32 AND IS_NULLABLE='NO')
 WHEN 'source_line_number' THEN NOT(DATA_TYPE='bigint' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='NO')
 WHEN 'ingested_at' THEN NOT(DATA_TYPE='timestamp' AND DATETIME_PRECISION=3 AND IS_NULLABLE='NO')
 ELSE 0 END),0) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE()
 AND TABLE_NAME='ktp_team_score_observations');
SET @m23_observation_table := (SELECT COUNT(*)=1 FROM information_schema.TABLES
 WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ktp_team_score_observations'
 AND ENGINE='InnoDB' AND TABLE_COLLATION='utf8mb4_bin');
SET @m23_observation_primary := (SELECT COUNT(*)=1 AND MIN(NON_UNIQUE)=0 AND
 GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX)='id' AND SUM(SUB_PART IS NOT NULL)=0
 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE()
 AND TABLE_NAME='ktp_team_score_observations' AND INDEX_NAME='PRIMARY');
SET @m23_observation_bad_named := (SELECT COUNT(*) FROM (
 SELECT INDEX_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE()
 AND TABLE_NAME='ktp_team_score_observations' AND INDEX_NAME IN
 ('uq_team_score_order','idx_team_score_match_order','idx_team_score_retention')
 GROUP BY INDEX_NAME HAVING NOT (
 (INDEX_NAME='uq_team_score_order' AND MIN(NON_UNIQUE)=0 AND COUNT(*)=4 AND GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX)='match_id,half,tick_seconds,event_sequence' AND SUM(SUB_PART IS NOT NULL)=0) OR
 (INDEX_NAME='idx_team_score_match_order' AND MIN(NON_UNIQUE)=1 AND COUNT(*)=4 AND GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX)='match_id,half,tick_seconds,event_sequence' AND SUM(SUB_PART IS NOT NULL)=0) OR
 (INDEX_NAME='idx_team_score_retention' AND MIN(NON_UNIQUE)=1 AND COUNT(*)=2 AND GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX)='retention_class,match_id' AND SUM(SUB_PART IS NOT NULL)=0))) bad_i);
SET @m23_observation_extra_unique := (SELECT COUNT(*) FROM (
 SELECT INDEX_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE()
 AND TABLE_NAME='ktp_team_score_observations' AND NON_UNIQUE=0
 AND INDEX_NAME NOT IN ('PRIMARY','uq_team_score_order') GROUP BY INDEX_NAME) extra_i);
SET @m23_ok := (@m23_observation_columns=24 AND @m23_observation_total_columns=24 AND @m23_observation_bad=0 AND
 @m23_observation_table=1 AND @m23_observation_primary=1 AND
 @m23_observation_bad_named=0 AND @m23_observation_extra_unique=0);
SET @m23_ddl := IF(@m23_ok,'DO 0','SELECT * FROM ERROR_023_team_score_observation_partial_or_incompatible');
PREPARE m23_stmt FROM @m23_ddl; EXECUTE m23_stmt; DEALLOCATE PREPARE m23_stmt;

SET @m23_conflict_columns := (SELECT COUNT(*) FROM information_schema.COLUMNS
 WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ktp_team_score_ingest_conflicts'
 AND COLUMN_NAME IN ('id','match_id','half','tick_seconds','event_sequence',
 'manifest_content_sha256','incumbent_raw_sha256','rejected_raw_sha256',
 'incumbent_raw_event_json','rejected_raw_event_json','source_file_sha256',
 'source_path_sha256','source_line_number','conflict_kind','detected_at'));
SET @m23_conflict_total_columns := (SELECT COUNT(*) FROM information_schema.COLUMNS
 WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ktp_team_score_ingest_conflicts');
SET @m23_conflict_bad := (SELECT COALESCE(SUM(CASE COLUMN_NAME
 WHEN 'id' THEN NOT(DATA_TYPE='bigint' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND LOCATE('auto_increment',EXTRA)>0 AND IS_NULLABLE='NO')
 WHEN 'match_id' THEN NOT(DATA_TYPE='varchar' AND CHARACTER_MAXIMUM_LENGTH=64 AND COLLATION_NAME='utf8mb4_bin' AND IS_NULLABLE='NO')
 WHEN 'half' THEN NOT(DATA_TYPE='smallint' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='NO')
 WHEN 'tick_seconds' THEN NOT(DATA_TYPE='decimal' AND NUMERIC_PRECISION=20 AND NUMERIC_SCALE=9 AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='NO')
 WHEN 'event_sequence' THEN NOT(DATA_TYPE='bigint' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='NO')
 WHEN 'manifest_content_sha256' THEN NOT(DATA_TYPE='binary' AND CHARACTER_MAXIMUM_LENGTH=32 AND IS_NULLABLE='NO')
 WHEN 'incumbent_raw_sha256' THEN NOT(DATA_TYPE='binary' AND CHARACTER_MAXIMUM_LENGTH=32 AND IS_NULLABLE='NO')
 WHEN 'rejected_raw_sha256' THEN NOT(DATA_TYPE='binary' AND CHARACTER_MAXIMUM_LENGTH=32 AND IS_NULLABLE='NO')
 WHEN 'incumbent_raw_event_json' THEN NOT(DATA_TYPE='longtext' AND COLLATION_NAME='utf8mb4_bin' AND IS_NULLABLE='NO')
 WHEN 'rejected_raw_event_json' THEN NOT(DATA_TYPE='longtext' AND COLLATION_NAME='utf8mb4_bin' AND IS_NULLABLE='NO')
 WHEN 'source_file_sha256' THEN NOT(DATA_TYPE='binary' AND CHARACTER_MAXIMUM_LENGTH=32 AND IS_NULLABLE='NO')
 WHEN 'source_path_sha256' THEN NOT(DATA_TYPE='binary' AND CHARACTER_MAXIMUM_LENGTH=32 AND IS_NULLABLE='NO')
 WHEN 'source_line_number' THEN NOT(DATA_TYPE='bigint' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='NO')
 WHEN 'conflict_kind' THEN NOT(COLUMN_TYPE='enum(''batch'',''existing'')' AND IS_NULLABLE='NO')
 WHEN 'detected_at' THEN NOT(DATA_TYPE='timestamp' AND DATETIME_PRECISION=3 AND IS_NULLABLE='NO')
 ELSE 0 END),0) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE()
 AND TABLE_NAME='ktp_team_score_ingest_conflicts');
SET @m23_conflict_table := (SELECT COUNT(*)=1 FROM information_schema.TABLES
 WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ktp_team_score_ingest_conflicts'
 AND ENGINE='InnoDB' AND TABLE_COLLATION='utf8mb4_bin');
SET @m23_conflict_primary := (SELECT COUNT(*)=1 AND MIN(NON_UNIQUE)=0 AND
 GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX)='id' AND SUM(SUB_PART IS NOT NULL)=0
 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE()
 AND TABLE_NAME='ktp_team_score_ingest_conflicts' AND INDEX_NAME='PRIMARY');
SET @m23_conflict_bad_named := (SELECT COUNT(*) FROM (
 SELECT INDEX_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE()
 AND TABLE_NAME='ktp_team_score_ingest_conflicts' AND INDEX_NAME IN
 ('uq_team_score_conflict','idx_team_score_conflict_match') GROUP BY INDEX_NAME HAVING NOT (
 (INDEX_NAME='uq_team_score_conflict' AND MIN(NON_UNIQUE)=0 AND COUNT(*)=6 AND GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX)='match_id,half,tick_seconds,event_sequence,incumbent_raw_sha256,rejected_raw_sha256' AND SUM(SUB_PART IS NOT NULL)=0) OR
 (INDEX_NAME='idx_team_score_conflict_match' AND MIN(NON_UNIQUE)=1 AND COUNT(*)=4 AND GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX)='match_id,half,tick_seconds,event_sequence' AND SUM(SUB_PART IS NOT NULL)=0))) bad_i);
SET @m23_conflict_extra_unique := (SELECT COUNT(*) FROM (
 SELECT INDEX_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE()
 AND TABLE_NAME='ktp_team_score_ingest_conflicts' AND NON_UNIQUE=0
 AND INDEX_NAME NOT IN ('PRIMARY','uq_team_score_conflict') GROUP BY INDEX_NAME) extra_i);
SET @m23_ok := (@m23_conflict_columns=15 AND @m23_conflict_total_columns=15 AND @m23_conflict_bad=0 AND
 @m23_conflict_table=1 AND @m23_conflict_primary=1 AND
 @m23_conflict_bad_named=0 AND @m23_conflict_extra_unique=0);
SET @m23_ddl := IF(@m23_ok,'DO 0','SELECT * FROM ERROR_023_team_score_conflict_partial_or_incompatible');
PREPARE m23_stmt FROM @m23_ddl; EXECUTE m23_stmt; DEALLOCATE PREPARE m23_stmt;

SET @m23_audit_columns := (SELECT COUNT(*) FROM information_schema.COLUMNS
 WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ktp_team_score_ingest_audits'
 AND COLUMN_NAME IN ('id','match_id','audit_kind','accepted_match_id',
 'accepted_manifest_sha256','attempted_manifest_sha256',
 'attempted_events_file_sha256','attempted_metadata_file_sha256',
 'attempted_events_path_sha256','attempted_metadata_path_sha256','map_name',
 'source_server','match_type','terminal_half','event_count','official_row_count',
 'detected_at'));
SET @m23_audit_total_columns := (SELECT COUNT(*) FROM information_schema.COLUMNS
 WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ktp_team_score_ingest_audits');
SET @m23_audit_bad := (SELECT COALESCE(SUM(CASE COLUMN_NAME
 WHEN 'id' THEN NOT(DATA_TYPE='bigint' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND LOCATE('auto_increment',EXTRA)>0 AND IS_NULLABLE='NO')
 WHEN 'match_id' THEN NOT(DATA_TYPE='varchar' AND CHARACTER_MAXIMUM_LENGTH=64 AND COLLATION_NAME='utf8mb4_bin' AND IS_NULLABLE='NO')
 WHEN 'audit_kind' THEN NOT(COLUMN_TYPE='enum(''manifest-mismatch'',''path-reuse'',''context-mismatch'')' AND IS_NULLABLE='NO')
 WHEN 'accepted_match_id' THEN NOT(DATA_TYPE='varchar' AND CHARACTER_MAXIMUM_LENGTH=64 AND COLLATION_NAME='utf8mb4_bin' AND IS_NULLABLE='YES')
 WHEN 'accepted_manifest_sha256' THEN NOT(DATA_TYPE='binary' AND CHARACTER_MAXIMUM_LENGTH=32 AND IS_NULLABLE='YES')
 WHEN 'attempted_manifest_sha256' THEN NOT(DATA_TYPE='binary' AND CHARACTER_MAXIMUM_LENGTH=32 AND IS_NULLABLE='NO')
 WHEN 'attempted_events_file_sha256' THEN NOT(DATA_TYPE='binary' AND CHARACTER_MAXIMUM_LENGTH=32 AND IS_NULLABLE='NO')
 WHEN 'attempted_metadata_file_sha256' THEN NOT(DATA_TYPE='binary' AND CHARACTER_MAXIMUM_LENGTH=32 AND IS_NULLABLE='NO')
 WHEN 'attempted_events_path_sha256' THEN NOT(DATA_TYPE='binary' AND CHARACTER_MAXIMUM_LENGTH=32 AND IS_NULLABLE='NO')
 WHEN 'attempted_metadata_path_sha256' THEN NOT(DATA_TYPE='binary' AND CHARACTER_MAXIMUM_LENGTH=32 AND IS_NULLABLE='NO')
 WHEN 'map_name' THEN NOT(DATA_TYPE='varchar' AND CHARACTER_MAXIMUM_LENGTH=32 AND COLLATION_NAME='utf8mb4_bin' AND IS_NULLABLE='NO')
 WHEN 'source_server' THEN NOT(DATA_TYPE='varchar' AND CHARACTER_MAXIMUM_LENGTH=128 AND COLLATION_NAME='utf8mb4_bin' AND IS_NULLABLE='NO')
 WHEN 'match_type' THEN NOT(DATA_TYPE='tinyint' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='NO')
 WHEN 'terminal_half' THEN NOT(DATA_TYPE='smallint' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='NO')
 WHEN 'event_count' THEN NOT(DATA_TYPE='bigint' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='NO')
 WHEN 'official_row_count' THEN NOT(DATA_TYPE='int' AND LOCATE('unsigned',COLUMN_TYPE)>0 AND IS_NULLABLE='NO')
 WHEN 'detected_at' THEN NOT(DATA_TYPE='timestamp' AND DATETIME_PRECISION=3 AND IS_NULLABLE='NO' AND LOWER(COLUMN_DEFAULT)='current_timestamp(3)')
 ELSE 0 END),0) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE()
 AND TABLE_NAME='ktp_team_score_ingest_audits');
SET @m23_audit_table := (SELECT COUNT(*)=1 FROM information_schema.TABLES
 WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ktp_team_score_ingest_audits'
 AND ENGINE='InnoDB' AND TABLE_COLLATION='utf8mb4_bin');
SET @m23_audit_primary := (SELECT COUNT(*)=1 AND MIN(NON_UNIQUE)=0 AND
 GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX)='id' AND SUM(SUB_PART IS NOT NULL)=0
 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE()
 AND TABLE_NAME='ktp_team_score_ingest_audits' AND INDEX_NAME='PRIMARY');
SET @m23_audit_bad_named := (SELECT COUNT(*) FROM (
 SELECT INDEX_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE()
 AND TABLE_NAME='ktp_team_score_ingest_audits' AND INDEX_NAME IN
 ('uq_team_score_ingest_audit','idx_team_score_ingest_audit_match')
 GROUP BY INDEX_NAME HAVING NOT (
 (INDEX_NAME='uq_team_score_ingest_audit' AND MIN(NON_UNIQUE)=0 AND COUNT(*)=5 AND GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX)='match_id,audit_kind,attempted_manifest_sha256,attempted_events_path_sha256,attempted_metadata_path_sha256' AND SUM(SUB_PART IS NOT NULL)=0) OR
 (INDEX_NAME='idx_team_score_ingest_audit_match' AND MIN(NON_UNIQUE)=1 AND COUNT(*)=2 AND GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX)='match_id,detected_at' AND SUM(SUB_PART IS NOT NULL)=0))) bad_i);
SET @m23_audit_extra_unique := (SELECT COUNT(*) FROM (
 SELECT INDEX_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE()
 AND TABLE_NAME='ktp_team_score_ingest_audits' AND NON_UNIQUE=0
 AND INDEX_NAME NOT IN ('PRIMARY','uq_team_score_ingest_audit') GROUP BY INDEX_NAME) extra_i);
SET @m23_ok := (@m23_audit_columns=17 AND @m23_audit_total_columns=17 AND
 @m23_audit_bad=0 AND @m23_audit_table=1 AND @m23_audit_primary=1 AND
 @m23_audit_bad_named=0 AND @m23_audit_extra_unique=0);
SET @m23_ddl := IF(@m23_ok,'DO 0','SELECT * FROM ERROR_023_team_score_audit_partial_or_incompatible');
PREPARE m23_stmt FROM @m23_ddl; EXECUTE m23_stmt; DEALLOCATE PREPARE m23_stmt;

-- Defaults, referential actions, and check bodies are part of the schema
-- contract, not incidental metadata. Fail closed on any drift.
SET @m23_timestamp_defaults := (SELECT COUNT(*) FROM information_schema.COLUMNS
 WHERE TABLE_SCHEMA=DATABASE() AND (
  (TABLE_NAME='ktp_team_score_ingest_manifests' AND COLUMN_NAME='ingested_at') OR
  (TABLE_NAME='ktp_team_score_observations' AND COLUMN_NAME='ingested_at') OR
  (TABLE_NAME='ktp_team_score_ingest_conflicts' AND COLUMN_NAME='detected_at') OR
  (TABLE_NAME='ktp_team_score_ingest_audits' AND COLUMN_NAME='detected_at'))
 AND DATA_TYPE='timestamp' AND DATETIME_PRECISION=3 AND IS_NULLABLE='NO'
 AND LOWER(COLUMN_DEFAULT)='current_timestamp(3)');
SET @m23_fk_ok := (
 (SELECT COUNT(*)=1 FROM information_schema.REFERENTIAL_CONSTRAINTS r
  JOIN information_schema.KEY_COLUMN_USAGE k
    ON k.CONSTRAINT_SCHEMA=r.CONSTRAINT_SCHEMA AND k.CONSTRAINT_NAME=r.CONSTRAINT_NAME
   AND k.TABLE_NAME=r.TABLE_NAME
  WHERE r.CONSTRAINT_SCHEMA=DATABASE() AND r.TABLE_NAME='ktp_team_score_observations'
    AND r.CONSTRAINT_NAME='fk_team_score_observation_manifest'
    AND r.REFERENCED_TABLE_NAME='ktp_team_score_ingest_manifests'
    AND r.UPDATE_RULE='RESTRICT' AND r.DELETE_RULE='RESTRICT'
    AND k.COLUMN_NAME='match_id' AND k.REFERENCED_COLUMN_NAME='match_id')
 AND
 (SELECT COUNT(*)=1 FROM information_schema.REFERENTIAL_CONSTRAINTS r
  JOIN information_schema.KEY_COLUMN_USAGE k
    ON k.CONSTRAINT_SCHEMA=r.CONSTRAINT_SCHEMA AND k.CONSTRAINT_NAME=r.CONSTRAINT_NAME
   AND k.TABLE_NAME=r.TABLE_NAME
  WHERE r.CONSTRAINT_SCHEMA=DATABASE() AND r.TABLE_NAME='ktp_team_score_ingest_conflicts'
    AND r.CONSTRAINT_NAME='fk_team_score_conflict_manifest'
    AND r.REFERENCED_TABLE_NAME='ktp_team_score_ingest_manifests'
    AND r.UPDATE_RULE='RESTRICT' AND r.DELETE_RULE='RESTRICT'
    AND k.COLUMN_NAME='match_id' AND k.REFERENCED_COLUMN_NAME='match_id')
 AND (SELECT COUNT(*)=2 FROM information_schema.TABLE_CONSTRAINTS
      WHERE CONSTRAINT_SCHEMA=DATABASE() AND CONSTRAINT_TYPE='FOREIGN KEY'
      AND TABLE_NAME IN ('ktp_team_score_observations','ktp_team_score_ingest_conflicts',
                         'ktp_team_score_ingest_manifests','ktp_team_score_ingest_audits'))
);
SET @m23_check_count := (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
 WHERE CONSTRAINT_SCHEMA=DATABASE() AND CONSTRAINT_TYPE='CHECK'
 AND TABLE_NAME IN ('ktp_team_score_ingest_manifests','ktp_team_score_observations',
                    'ktp_team_score_ingest_conflicts','ktp_team_score_ingest_audits'));
SET @m23_bad_checks := (SELECT COUNT(*) FROM (
 SELECT t.TABLE_NAME,t.CONSTRAINT_NAME,
  LOWER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(c.CHECK_CLAUSE,
    '`',''),' ',''),'(',''),')',''),CHAR(9),''),CHAR(10),''),CHAR(13),'')) AS clause
 FROM information_schema.TABLE_CONSTRAINTS t
 JOIN information_schema.CHECK_CONSTRAINTS c
   ON c.CONSTRAINT_SCHEMA=t.CONSTRAINT_SCHEMA AND c.CONSTRAINT_NAME=t.CONSTRAINT_NAME
 WHERE t.CONSTRAINT_SCHEMA=DATABASE() AND t.CONSTRAINT_TYPE='CHECK'
 AND t.TABLE_NAME IN ('ktp_team_score_ingest_manifests','ktp_team_score_observations',
                      'ktp_team_score_ingest_conflicts','ktp_team_score_ingest_audits')
 ) checks WHERE NOT (
  (CONSTRAINT_NAME='chk_team_score_terminal_half' AND clause='terminal_halfin1,2orterminal_half>=101') OR
  (CONSTRAINT_NAME='chk_team_score_lifecycle_complete' AND clause='lifecycle_complete=1') OR
  (CONSTRAINT_NAME='chk_team_score_settlement' AND clause='settlement_seconds>=30') OR
  (CONSTRAINT_NAME='chk_team_score_side_ids' AND clause='allies_team_idin1,2andaxis_team_idin1,2andallies_team_id<>axis_team_id') OR
  (CONSTRAINT_NAME='chk_team_score_half' AND clause='halfin1,2orhalf>=101') OR
  (CONSTRAINT_NAME='chk_team_score_source_version' AND clause='source_version=1') OR
  (CONSTRAINT_NAME='chk_team_score_conflict_hashes' AND clause='incumbent_raw_sha256<>rejected_raw_sha256') OR
  (CONSTRAINT_NAME='chk_team_score_audit_terminal_half' AND clause='terminal_halfin1,2orterminal_half>=101')
 ));
SET @m23_ok := (@m23_timestamp_defaults=4 AND @m23_fk_ok=1
 AND @m23_check_count=8 AND @m23_bad_checks=0);
SET @m23_ddl := IF(@m23_ok,'DO 0','SELECT * FROM ERROR_023_team_score_constraint_or_default_incompatible');
PREPARE m23_stmt FROM @m23_ddl; EXECUTE m23_stmt; DEALLOCATE PREPARE m23_stmt;

-- Repair only wholly absent, already-preflighted named indexes.
SET @m23_exists := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ktp_team_score_ingest_manifests' AND INDEX_NAME='uq_team_score_events_path');
SET @m23_ddl := IF(@m23_exists,'DO 0','ALTER TABLE ktp_team_score_ingest_manifests ADD UNIQUE KEY uq_team_score_events_path (events_path_sha256)');
PREPARE m23_stmt FROM @m23_ddl; EXECUTE m23_stmt; DEALLOCATE PREPARE m23_stmt;
SET @m23_exists := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ktp_team_score_ingest_manifests' AND INDEX_NAME='uq_team_score_metadata_path');
SET @m23_ddl := IF(@m23_exists,'DO 0','ALTER TABLE ktp_team_score_ingest_manifests ADD UNIQUE KEY uq_team_score_metadata_path (metadata_path_sha256)');
PREPARE m23_stmt FROM @m23_ddl; EXECUTE m23_stmt; DEALLOCATE PREPARE m23_stmt;
SET @m23_exists := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ktp_team_score_ingest_manifests' AND INDEX_NAME='idx_team_score_manifest_retention');
SET @m23_ddl := IF(@m23_exists,'DO 0','ALTER TABLE ktp_team_score_ingest_manifests ADD KEY idx_team_score_manifest_retention (retention_class,match_id)');
PREPARE m23_stmt FROM @m23_ddl; EXECUTE m23_stmt; DEALLOCATE PREPARE m23_stmt;
SET @m23_exists := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ktp_team_score_observations' AND INDEX_NAME='uq_team_score_order');
SET @m23_ddl := IF(@m23_exists,'DO 0','ALTER TABLE ktp_team_score_observations ADD UNIQUE KEY uq_team_score_order (match_id,half,tick_seconds,event_sequence)');
PREPARE m23_stmt FROM @m23_ddl; EXECUTE m23_stmt; DEALLOCATE PREPARE m23_stmt;
SET @m23_exists := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ktp_team_score_observations' AND INDEX_NAME='idx_team_score_match_order');
SET @m23_ddl := IF(@m23_exists,'DO 0','ALTER TABLE ktp_team_score_observations ADD KEY idx_team_score_match_order (match_id,half,tick_seconds,event_sequence)');
PREPARE m23_stmt FROM @m23_ddl; EXECUTE m23_stmt; DEALLOCATE PREPARE m23_stmt;
SET @m23_exists := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ktp_team_score_observations' AND INDEX_NAME='idx_team_score_retention');
SET @m23_ddl := IF(@m23_exists,'DO 0','ALTER TABLE ktp_team_score_observations ADD KEY idx_team_score_retention (retention_class,match_id)');
PREPARE m23_stmt FROM @m23_ddl; EXECUTE m23_stmt; DEALLOCATE PREPARE m23_stmt;
SET @m23_exists := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ktp_team_score_ingest_conflicts' AND INDEX_NAME='uq_team_score_conflict');
SET @m23_ddl := IF(@m23_exists,'DO 0','ALTER TABLE ktp_team_score_ingest_conflicts ADD UNIQUE KEY uq_team_score_conflict (match_id,half,tick_seconds,event_sequence,incumbent_raw_sha256,rejected_raw_sha256)');
PREPARE m23_stmt FROM @m23_ddl; EXECUTE m23_stmt; DEALLOCATE PREPARE m23_stmt;
SET @m23_exists := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ktp_team_score_ingest_conflicts' AND INDEX_NAME='idx_team_score_conflict_match');
SET @m23_ddl := IF(@m23_exists,'DO 0','ALTER TABLE ktp_team_score_ingest_conflicts ADD KEY idx_team_score_conflict_match (match_id,half,tick_seconds,event_sequence)');
PREPARE m23_stmt FROM @m23_ddl; EXECUTE m23_stmt; DEALLOCATE PREPARE m23_stmt;
SET @m23_exists := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ktp_team_score_ingest_audits' AND INDEX_NAME='uq_team_score_ingest_audit');
SET @m23_ddl := IF(@m23_exists,'DO 0','ALTER TABLE ktp_team_score_ingest_audits ADD UNIQUE KEY uq_team_score_ingest_audit (match_id,audit_kind,attempted_manifest_sha256,attempted_events_path_sha256,attempted_metadata_path_sha256)');
PREPARE m23_stmt FROM @m23_ddl; EXECUTE m23_stmt; DEALLOCATE PREPARE m23_stmt;
SET @m23_exists := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ktp_team_score_ingest_audits' AND INDEX_NAME='idx_team_score_ingest_audit_match');
SET @m23_ddl := IF(@m23_exists,'DO 0','ALTER TABLE ktp_team_score_ingest_audits ADD KEY idx_team_score_ingest_audit_match (match_id,detected_at)');
PREPARE m23_stmt FROM @m23_ddl; EXECUTE m23_stmt; DEALLOCATE PREPARE m23_stmt;
