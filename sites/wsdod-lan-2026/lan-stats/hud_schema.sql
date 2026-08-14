-- LAN HUD observer data — full event capture, nothing discarded.
--
-- One raw table holding every event verbatim, plus typed tables for the events
-- worth querying directly. The raw table exists because "all of it" has to
-- survive a change of mind about what matters: the typed tables can be dropped
-- and rebuilt from `hud_events` without going back to the LAN box.
--
-- `user_id` in the HUD payload IS the SteamID (STEAM_0:1:x), so these join to
-- hlstatsx by SteamID with no name matching.
--
-- Applies to `hlstatsx_lan` — the restored LAN clone, never the league database.

CREATE TABLE IF NOT EXISTS hud_events (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  match_id    VARCHAR(64)  NOT NULL,
  half        TINYINT      NOT NULL DEFAULT 0,
  tick        DECIMAL(12,2) NULL,
  sent_at     BIGINT       NULL,          -- plugin_sent_at, epoch ms
  event       VARCHAR(40)  NOT NULL,
  payload     JSON         NOT NULL,      -- the line verbatim
  PRIMARY KEY (id),
  KEY ix_hud_events_match (match_id, half),
  KEY ix_hud_events_type (event),
  KEY ix_hud_events_tick (match_id, tick)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Per-player summary the plugin computes. Emitted repeatedly during a half, so
-- the LAST row per (match, half, player) is the final state -- summing these
-- would multiply every stat by the number of emissions.
CREATE TABLE IF NOT EXISTS hud_player_stats (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  match_id    VARCHAR(64) NOT NULL,
  half        TINYINT     NOT NULL,
  tick        DECIMAL(12,2) NULL,
  steam_id    VARCHAR(32) NOT NULL,
  name        VARCHAR(64) NOT NULL,
  team        VARCHAR(16) NULL,
  kills       INT NOT NULL DEFAULT 0,
  deaths      INT NOT NULL DEFAULT 0,
  assists     INT NOT NULL DEFAULT 0,
  damage      INT NOT NULL DEFAULT 0,
  hits        INT NOT NULL DEFAULT 0,
  hs_hits     INT NOT NULL DEFAULT 0,
  hs_kills    INT NOT NULL DEFAULT 0,
  gun_kills   INT NOT NULL DEFAULT 0,
  nade_kills  INT NOT NULL DEFAULT 0,
  caps        INT NOT NULL DEFAULT 0,
  cap_breaks  INT NOT NULL DEFAULT 0,
  obj_score   INT NOT NULL DEFAULT 0,
  best_streak INT NOT NULL DEFAULT 0,
  is_final    TINYINT(1) NOT NULL DEFAULT 0,   -- last emission for this half
  PRIMARY KEY (id),
  KEY ix_hps_match (match_id, half),
  KEY ix_hps_player (steam_id),
  KEY ix_hps_final (is_final, match_id, half)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Per-hit damage: attacker, victim, amount, hitbox. This is what HLStatsX
-- cannot provide -- its damage is aggregated per weapon per flush with no
-- victim and no timestamp.
CREATE TABLE IF NOT EXISTS hud_damage (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  match_id      VARCHAR(64) NOT NULL,
  half          TINYINT     NOT NULL,
  tick          DECIMAL(12,2) NULL,
  attacker_id   VARCHAR(32) NULL,
  victim_id     VARCHAR(32) NULL,
  damage        INT NOT NULL DEFAULT 0,
  hitplace      VARCHAR(24) NULL,
  weapon        VARCHAR(32) NULL,
  victim_health INT NULL,
  PRIMARY KEY (id),
  KEY ix_hd_match (match_id, half),
  KEY ix_hd_attacker (attacker_id),
  KEY ix_hd_victim (victim_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Kills with assist attribution -- assist_ids is a list, so it is exploded into
-- hud_kill_assists rather than stored as text nobody can join on.
CREATE TABLE IF NOT EXISTS hud_kills (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  match_id     VARCHAR(64) NOT NULL,
  half         TINYINT     NOT NULL,
  tick         DECIMAL(12,2) NULL,
  killer_id    VARCHAR(32) NULL,
  victim_id    VARCHAR(32) NULL,
  weapon       VARCHAR(32) NULL,
  headshot     TINYINT(1) NOT NULL DEFAULT 0,
  killer_prone TINYINT(1) NULL,
  victim_prone TINYINT(1) NULL,
  kill_class   VARCHAR(32) NULL,
  kill_type    VARCHAR(32) NULL,
  PRIMARY KEY (id),
  KEY ix_hk_match (match_id, half),
  KEY ix_hk_killer (killer_id),
  KEY ix_hk_victim (victim_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS hud_kill_assists (
  kill_id   BIGINT UNSIGNED NOT NULL,
  steam_id  VARCHAR(32) NOT NULL,
  KEY ix_hka_kill (kill_id),
  KEY ix_hka_player (steam_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Prone transitions. Duration is derived (next transition minus this one), not
-- stored, because a half can end while a player is still prone.
CREATE TABLE IF NOT EXISTS hud_prone (
  id        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  match_id  VARCHAR(64) NOT NULL,
  half      TINYINT     NOT NULL,
  tick      DECIMAL(12,2) NULL,
  steam_id  VARCHAR(32) NOT NULL,
  state     VARCHAR(16) NULL,
  PRIMARY KEY (id),
  KEY ix_hp_match (match_id, half),
  KEY ix_hp_player (steam_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS hud_flag_events (
  id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  match_id   VARCHAR(64) NOT NULL,
  half       TINYINT     NOT NULL,
  tick       DECIMAL(12,2) NULL,
  event      VARCHAR(32) NOT NULL,     -- captured | cap_started | cap_stopped | cap_break
  flag_id    VARCHAR(32) NULL,
  flag_name  VARCHAR(64) NULL,
  team       VARCHAR(16) NULL,
  steam_id   VARCHAR(32) NULL,         -- captor or breaker; one row per player
  PRIMARY KEY (id),
  KEY ix_hf_match (match_id, half),
  KEY ix_hf_player (steam_id),
  KEY ix_hf_event (event)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS hud_spawns (
  id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  match_id   VARCHAR(64) NOT NULL,
  half       TINYINT     NOT NULL,
  tick       DECIMAL(12,2) NULL,
  steam_id   VARCHAR(32) NOT NULL,
  name       VARCHAR(64) NULL,
  team       VARCHAR(16) NULL,
  class_id   VARCHAR(32) NULL,
  weapon_primary   VARCHAR(32) NULL,
  weapon_secondary VARCHAR(32) NULL,
  PRIMARY KEY (id),
  KEY ix_hs_match (match_id, half),
  KEY ix_hs_player (steam_id),
  KEY ix_hs_class (class_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- RETIRED 2026-08-14 -- NOT the production gate, and never was. Nothing has
-- ever read this table, both audit columns are still NULL, and lan-web cannot
-- reach it anyway: the app connects as ktp_lan and this lives in hlstatsx_lan.
-- The live gate is lan_settings.stats_published, in ktp_lan, via /admin/publish.
-- Kept only so an existing deployment does not lose a table. When per-match
-- gating lands, rebuild the per-scope idea in ktp_lan rather than granting
-- cross-database access to this one.
--
-- Its default was right and is worth carrying forward: a new dataset starts
-- unpublished, because a page that defaults to visible eventually leaks
-- something nobody meant to release.
CREATE TABLE IF NOT EXISTS lan_stats_publication (
  scope       VARCHAR(32) NOT NULL,     -- 'all' | a match_id | a date
  published   TINYINT(1)  NOT NULL DEFAULT 0,
  published_by VARCHAR(32) NULL,
  published_at DATETIME   NULL,
  note        VARCHAR(255) NULL,
  PRIMARY KEY (scope)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO lan_stats_publication (scope, published, note)
VALUES ('all', 0, 'Philly LAN 2026 — unpublished by default; flip deliberately.');
