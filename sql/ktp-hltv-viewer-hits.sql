-- HLTV viewer-session hits. See scripts/README-hltv-viewer-logging.md.
--
-- One row per (source IP, proxy port) per hour, for UDP flows qualified by
-- bytes and a minimum packet length -- i.e. genuine viewing sessions, not the
-- automated pollers that sweep all 24 proxy ports continuously.
--
-- COLLATION IS LOAD-BEARING: utf8mb4_unicode_ci matches hlstats_Events_Connects,
-- which is what src_ip is joined against. Create this utf8mb4_0900_ai_ci (the
-- server default, and what the ktp_ac_* tables use) and every correlation query
-- fails with ERROR 1267 Illegal mix of collations instead.
CREATE TABLE IF NOT EXISTS ktp_hltv_viewer_hits (
  id        INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  hit_time  DATETIME          NOT NULL COMMENT 'server-local ET, matching hlstats_Events_Connects.eventTime',
  src_ip    VARCHAR(45)       NOT NULL COMMENT 'viewer source IP; NOT an identity - see players_behind_ip in the correlate tool',
  dst_port  SMALLINT UNSIGNED NOT NULL COMMENT 'which HLTV proxy (27020-27043)',
  PRIMARY KEY (id),
  -- Makes ingest idempotent: the parser re-reads the whole log every run and
  -- relies on INSERT IGNORE rather than tracking a file offset.
  UNIQUE KEY uq_hit (hit_time, src_ip, dst_port),
  KEY idx_ip (src_ip),
  KEY idx_time (hit_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='HLTV viewer sessions from the ufw connbytes LOG rule. One row per (src,proxy) per hour.';

-- The ingest cron runs as root and reaches MySQL over the unix socket, so no
-- GRANT is required for it. Anything ELSE that reads this table (a web view, a
-- reporting user) needs its own per-table GRANT -- and UPDATE too if it upserts,
-- or its writes fail silently.
