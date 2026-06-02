-- WSDoD LAN 2026 — initial schema (Phase 0 foundation).
-- Applied by migrate.py; tracked in lan_schema_migrations.
-- lan_schedule + lan_bracket are foundational stubs for Phases 3-4; the
-- columns may grow as the result-reporting and bracket logic land.

CREATE TABLE lan_teams (
  id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  name        VARCHAR(64) NOT NULL,
  tag         VARCHAR(16) NULL,
  seed        INT NULL,                       -- group-stage seed; set after the captain poll
  created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_lan_teams_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE lan_players (
  id            INT UNSIGNED NOT NULL AUTO_INCREMENT,
  team_id       INT UNSIGNED NOT NULL,
  discord_id    BIGINT UNSIGNED NULL,         -- Discord snowflake; the OAuth identity linchpin
  discord_name  VARCHAR(64) NULL,
  steam_id      VARCHAR(32) NULL,
  display_name  VARCHAR(64) NOT NULL,
  is_captain    TINYINT(1) NOT NULL DEFAULT 0,
  created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_lan_players_discord (discord_id),  -- NULLs allowed for unlinked players
  KEY idx_lan_players_team (team_id),
  CONSTRAINT fk_lan_players_team FOREIGN KEY (team_id) REFERENCES lan_teams(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE lan_seed_ballots (
  id              INT UNSIGNED NOT NULL AUTO_INCREMENT,
  voting_team_id  INT UNSIGNED NOT NULL,       -- team casting the ballot
  ranked_team_id  INT UNSIGNED NOT NULL,       -- team being ranked
  rank            INT NOT NULL,                -- 1 = strongest
  submitted_by    BIGINT UNSIGNED NULL,        -- captain discord_id
  submitted_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_ballot (voting_team_id, ranked_team_id),
  KEY idx_ballot_ranked (ranked_team_id),
  CONSTRAINT fk_ballot_voter  FOREIGN KEY (voting_team_id) REFERENCES lan_teams(id) ON DELETE CASCADE,
  CONSTRAINT fk_ballot_ranked FOREIGN KEY (ranked_team_id) REFERENCES lan_teams(id) ON DELETE CASCADE,
  CONSTRAINT chk_ballot_not_self CHECK (voting_team_id <> ranked_team_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE lan_schedule (
  id             INT UNSIGNED NOT NULL AUTO_INCREMENT,
  round          INT NOT NULL,                 -- group round 1-6 (BO1)
  station        INT NULL,                     -- server/station number
  team_a_id      INT UNSIGNED NOT NULL,
  team_b_id      INT UNSIGNED NOT NULL,
  score_a        INT NULL,
  score_b        INT NULL,
  winner_team_id INT UNSIGNED NULL,
  status         ENUM('pending','live','final') NOT NULL DEFAULT 'pending',
  reported_by    BIGINT UNSIGNED NULL,         -- discord_id of reporter
  reported_at    TIMESTAMP NULL,
  created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_sched_round (round),
  CONSTRAINT fk_sched_a FOREIGN KEY (team_a_id) REFERENCES lan_teams(id),
  CONSTRAINT fk_sched_b FOREIGN KEY (team_b_id) REFERENCES lan_teams(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE lan_bracket (
  id             INT UNSIGNED NOT NULL AUTO_INCREMENT,
  bracket        ENUM('upper','lower') NOT NULL,
  stage          VARCHAR(16) NOT NULL,         -- QF/SF/F, playin/lsemi/lfinal
  slot           INT NOT NULL,                 -- position within the stage
  source_a       VARCHAR(32) NULL,             -- e.g. 'seed:3', 'W:QF1', 'L:QF2'
  source_b       VARCHAR(32) NULL,
  team_a_id      INT UNSIGNED NULL,            -- resolved as the bracket fills
  team_b_id      INT UNSIGNED NULL,
  score_a        INT NULL,                     -- BO3 series wins
  score_b        INT NULL,
  winner_team_id INT UNSIGNED NULL,
  status         ENUM('pending','live','final') NOT NULL DEFAULT 'pending',
  PRIMARY KEY (id),
  KEY idx_bracket_stage (bracket, stage),
  CONSTRAINT fk_brk_a FOREIGN KEY (team_a_id) REFERENCES lan_teams(id),
  CONSTRAINT fk_brk_b FOREIGN KEY (team_b_id) REFERENCES lan_teams(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
