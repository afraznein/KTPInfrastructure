-- Check-in timestamps (players self-check-in; captains confirm the team).
ALTER TABLE lan_players ADD COLUMN checked_in_at TIMESTAMP NULL;
ALTER TABLE lan_teams   ADD COLUMN checked_in_at TIMESTAMP NULL;

-- Uploaded demos/VODs. The file is zipped server-side; we keep only the .zip.
CREATE TABLE IF NOT EXISTS lan_demos (
  id                INT UNSIGNED NOT NULL AUTO_INCREMENT,
  alias             VARCHAR(64) NOT NULL,          -- uploader's in-game alias (required)
  team_id           INT UNSIGNED NULL,             -- from the uploader's roster link, if any
  original_filename VARCHAR(255) NOT NULL,
  stored_name       VARCHAR(64) NULL,              -- <id>.zip on disk
  size_bytes        BIGINT UNSIGNED NULL,          -- size of the stored zip
  note              VARCHAR(255) NULL,             -- optional: match/map context
  uploaded_by       BIGINT UNSIGNED NULL,          -- discord id
  uploaded_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_demos_team (team_id),
  CONSTRAINT fk_demos_team FOREIGN KEY (team_id) REFERENCES lan_teams(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
