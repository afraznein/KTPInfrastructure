-- Photo takedown requests. Anyone signed in with Discord can ask for a gallery
-- photo to come down; staff work the queue and mark each one handled. The app
-- refuses a repeat from the same requester on the same photo within 24h, so
-- every row here is a distinct ask rather than a retry.

-- Deliberately no FK to lan_photos: honouring a request deletes the photo, and
-- the record of who asked must outlive it.
CREATE TABLE IF NOT EXISTS lan_photo_removal_requests (
  id             INT UNSIGNED NOT NULL AUTO_INCREMENT,
  photo_id       INT UNSIGNED NOT NULL,
  requested_by   BIGINT UNSIGNED NOT NULL,     -- requester discord id
  requested_name VARCHAR(64)  NULL,            -- their Discord name at the time
  reason         VARCHAR(500) NULL,
  requested_ip   VARCHAR(45)  NULL,
  status         ENUM('pending','handled') NOT NULL DEFAULT 'pending',
  handled_by     BIGINT UNSIGNED NULL,         -- staff discord id
  handled_at     TIMESTAMP NULL,
  created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_photo_removal_rate (photo_id, requested_by, created_at),
  KEY idx_photo_removal_queue (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
