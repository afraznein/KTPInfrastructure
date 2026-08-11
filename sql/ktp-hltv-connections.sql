-- HLTV connection attempts. See scripts/README-hltv-connection-logging.md.
--
-- One row per (source IP, proxy port) per hour, from the ufw LOG rule. These are
-- CONNECTION ATTEMPTS, not confirmed viewers -- the name says so on purpose. The
-- firewall deliberately does not try to decide which are people; that judgement
-- lives in ktp-hltv-correlate.py where it can be audited and changed without a
-- kernel rule nobody can test. Two earlier designs tried to discriminate in the
-- rule and both were structurally wrong in production.
--
-- COLLATION IS LOAD-BEARING: utf8mb4_unicode_ci matches hlstats_Events_Connects,
-- which is what src_ip is joined against. Create this utf8mb4_0900_ai_ci (the
-- server default, and what the ktp_ac_* tables use) and every correlation query
-- fails with ERROR 1267 Illegal mix of collations instead.
-- CREATE TABLE IF NOT EXISTS is a NO-OP on an existing table, so it cannot
-- enforce that -- verify with SHOW CREATE TABLE after running this.
CREATE TABLE IF NOT EXISTS ktp_hltv_connections (
  id        INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  hit_time  DATETIME          NOT NULL COMMENT 'server-local ET, matching hlstats_Events_Connects.eventTime; ctstate NEW, so this is connection time',
  src_ip    VARCHAR(45)       NOT NULL COMMENT 'source IP; NOT an identity - see players_behind_ip and ports_swept',
  dst_port  SMALLINT UNSIGNED NOT NULL COMMENT 'which HLTV proxy (27020-27044, the range the rule covers)',
  PRIMARY KEY (id),
  -- Makes ingest idempotent: the parser re-reads the log and relies on INSERT
  -- IGNORE rather than tracking a file offset.
  UNIQUE KEY uq_hit (hit_time, src_ip, dst_port),
  KEY idx_ip (src_ip),
  KEY idx_time (hit_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='HLTV connection attempts from the ufw LOG rule. One row per (src,proxy) per hour. NOT confirmed viewers.';

-- The ingest cron runs as root and reaches MySQL over the unix socket, so no
-- GRANT is required for it. Anything ELSE that reads this table (a web view, a
-- reporting user) needs its own per-table GRANT -- and UPDATE too if it upserts,
-- or its writes fail silently.
