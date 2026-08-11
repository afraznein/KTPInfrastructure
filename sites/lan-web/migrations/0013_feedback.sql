-- Site feedback. Attribution is the point — there is no anonymous path, so
-- every row carries the Discord account that sent it. Kept here as well as
-- posted to Discord: the channel is where staff read it, this is what survives
-- a relay outage and what the per-hour limit is counted from.
CREATE TABLE IF NOT EXISTS lan_feedback (
  id           INT UNSIGNED NOT NULL AUTO_INCREMENT,
  category     ENUM('event','site','next','other') NOT NULL DEFAULT 'other',
  body         VARCHAR(2000) NOT NULL,
  sent_by      BIGINT UNSIGNED NOT NULL,      -- sender discord id
  sent_name    VARCHAR(64)  NULL,             -- their Discord name at the time
  sent_ip      VARCHAR(45)  NULL,
  notified     TINYINT(1)   NOT NULL DEFAULT 0,
  created_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_feedback_rate (sent_by, created_at),
  KEY idx_feedback_recent (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
