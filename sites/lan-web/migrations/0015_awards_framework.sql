-- Award candidates generated from the stats build, with operator intent kept in
-- separate tables so a regeneration can never clobber a rename or a selection.
--
-- Three lifetimes, three tables:
--   lan_award_types       outlive every event; a rename here is inherited forward
--   lan_award_candidates  disposable, truncated and rewritten by each stats build
--   lan_award_selections  per edition; what staff ticked to publish

-- Replaces rename_awards.py, which existed only because "a rename has nowhere
-- upstream to live". title/sting NULL means "use the generated default".
CREATE TABLE IF NOT EXISTS lan_award_types (
  slug           VARCHAR(48)  NOT NULL,
  -- 'day' is KTPR's scope: it renormalises per day, so an MVP award exists once
  -- per day of the event and never as a weekend total.
  scope          ENUM('weekend','match','day') NOT NULL,
  kind           ENUM('player','team') NOT NULL DEFAULT 'player',
  stat_key       VARCHAR(48)  NOT NULL,      -- which generated stat decides it
  direction      ENUM('high','low') NOT NULL,
  default_title  VARCHAR(96)  NOT NULL,      -- regenerated; operator never edits
  default_sting  VARCHAR(255) NOT NULL,
  title          VARCHAR(96)  NULL,          -- operator override, wins when set
  sting          VARCHAR(255) NULL,
  -- Two floors, because the real awards need both shapes: "played at least half
  -- the games" is a share of the event, "30-kill minimum" is an absolute on a
  -- companion stat.
  min_share      DECIMAL(4,3) NULL,          -- fraction of event halves played
  min_stat_key   VARCHAR(48)  NULL,
  min_stat       INT          NULL,
  retired        TINYINT(1)   NOT NULL DEFAULT 0,
  sort_order     INT          NOT NULL DEFAULT 0,
  updated_by     BIGINT UNSIGNED NULL,
  updated_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (slug)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Rewritten wholesale by the stats build. Nothing operator-authored lives here,
-- which is what makes a full rebuild safe.
CREATE TABLE IF NOT EXISTS lan_award_candidates (
  id            INT UNSIGNED NOT NULL AUTO_INCREMENT,
  edition       VARCHAR(32)  NOT NULL,       -- 'philly-2026'
  award_slug    VARCHAR(48)  NOT NULL,
  match_key     VARCHAR(64)  NOT NULL DEFAULT '',  -- '' for weekend scope
  rank_pos      INT          NOT NULL,       -- competition rank: 1,2,2,4
  who           VARCHAR(96)  NOT NULL,
  who_alias     VARCHAR(96)  NULL,           -- name worn at the time, if different
  value_num     DECIMAL(14,4) NULL,          -- sorts and ties compare on this
  value_text    VARCHAR(48)  NOT NULL,       -- display form (m:ss, 2.35, 1,204)
  where_text    VARCHAR(160) NULL,           -- 'harrington · Sat · v b Team'
  generated_at  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_award (edition, award_slug, match_key, rank_pos)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- match_key defaults to '' rather than NULL so weekend rows can sit in the
-- primary key; MySQL will not take a nullable column there.
CREATE TABLE IF NOT EXISTS lan_award_selections (
  edition       VARCHAR(32)  NOT NULL,
  award_slug    VARCHAR(48)  NOT NULL,
  match_key     VARCHAR(64)  NOT NULL DEFAULT '',
  selected      TINYINT(1)   NOT NULL DEFAULT 0,
  selected_by   BIGINT UNSIGNED NULL,
  selected_at   TIMESTAMP    NULL DEFAULT NULL,
  PRIMARY KEY (edition, award_slug, match_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- action is VARCHAR, not ENUM, on purpose: an ENUM needs a migration for every
-- new value and STRICT mode turns an unregistered one into a swallowed write, so
-- the audit log silently loses the row it exists to keep.
CREATE TABLE IF NOT EXISTS lan_admin_audit (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  actor       BIGINT UNSIGNED NOT NULL,
  actor_name  VARCHAR(96)  NULL,
  action      VARCHAR(48)  NOT NULL,
  target      VARCHAR(160) NULL,
  old_value   TEXT         NULL,
  new_value   TEXT         NULL,
  at          TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_at (at),
  KEY idx_actor (actor)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
