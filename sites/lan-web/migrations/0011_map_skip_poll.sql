-- Captain map-skip poll: Saturday runs only 6 matches, so one map is dropped
-- and used as the play-in map. Each team captain casts a single ballot naming
-- the map their squad wants skipped; the most-voted map wins. One ballot per
-- team (resubmitting overwrites).

CREATE TABLE IF NOT EXISTS lan_map_skip_ballots (
  id              INT UNSIGNED NOT NULL AUTO_INCREMENT,
  voting_team_id  INT UNSIGNED NOT NULL,        -- team casting the ballot
  skip_map        VARCHAR(48) NOT NULL,         -- the map they want skipped
  submitted_by    BIGINT UNSIGNED NULL,         -- captain discord_id
  submitted_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_map_skip_voter (voting_team_id),
  CONSTRAINT fk_map_skip_voter FOREIGN KEY (voting_team_id) REFERENCES lan_teams(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO lan_settings (k, v) VALUES ('map_skip_poll_open', '0')
  ON DUPLICATE KEY UPDATE v=v;
