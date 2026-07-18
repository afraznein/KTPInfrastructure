-- Map per match (group BO1 + Sunday series), demo->match linkage,
-- result audit log, caster streams, awards voting, photo gallery.

ALTER TABLE lan_schedule ADD COLUMN map VARCHAR(48) NULL AFTER station;
ALTER TABLE lan_bracket  ADD COLUMN map VARCHAR(96) NULL AFTER station;

ALTER TABLE lan_demos ADD COLUMN schedule_id  INT UNSIGNED NULL AFTER team_id;
ALTER TABLE lan_demos ADD COLUMN bracket_mkey VARCHAR(8)   NULL AFTER schedule_id;

-- Every result report/edit/undo on a Saturday match or Sunday series.
CREATE TABLE IF NOT EXISTS lan_result_audit (
  id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  scope       ENUM('schedule','bracket') NOT NULL,
  ref         VARCHAR(16) NOT NULL,            -- lan_schedule.id or lan_bracket.mkey
  action      VARCHAR(16) NOT NULL DEFAULT 'report',
  prev_a      INT NULL,
  prev_b      INT NULL,
  prev_winner INT UNSIGNED NULL,
  prev_status VARCHAR(12) NULL,
  new_a       INT NULL,
  new_b       INT NULL,
  new_winner  INT UNSIGNED NULL,
  new_status  VARCHAR(12) NULL,
  actor       BIGINT UNSIGNED NULL,            -- reporter discord id
  created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_scope_ref (scope, ref)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Caster / stream links shown on the Now Playing board.
CREATE TABLE IF NOT EXISTS lan_streams (
  id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  label       VARCHAR(80)  NOT NULL,           -- "Main stage" / channel name
  url         VARCHAR(255) NOT NULL,
  caster      VARCHAR(80)  NULL,               -- who's on the mic
  live        TINYINT(1)   NOT NULL DEFAULT 0,
  sort_order  INT          NOT NULL DEFAULT 0,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Post-event awards. kind decides whether targets are players or teams.
CREATE TABLE IF NOT EXISTS lan_awards (
  id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  slug        VARCHAR(48)  NOT NULL,
  title       VARCHAR(96)  NOT NULL,
  kind        ENUM('player','team') NOT NULL DEFAULT 'player',
  is_open     TINYINT(1)   NOT NULL DEFAULT 0,
  sort_order  INT          NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY uq_award_slug (slug)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- One ballot per voter per award.
CREATE TABLE IF NOT EXISTS lan_award_votes (
  award_id    INT UNSIGNED NOT NULL,
  voter       BIGINT UNSIGNED NOT NULL,
  target_id   INT UNSIGNED NOT NULL,           -- player id or team id per award.kind
  created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (award_id, voter)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Event photo gallery.
CREATE TABLE IF NOT EXISTS lan_photos (
  id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  stored_name VARCHAR(64)  NOT NULL,           -- <id>.<ext> on disk
  caption     VARCHAR(200) NULL,
  uploaded_by BIGINT UNSIGNED NULL,
  uploaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
