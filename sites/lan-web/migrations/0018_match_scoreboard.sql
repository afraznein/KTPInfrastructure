-- Per-match scoreboards, in ktp_lan where lan-web can read them.
--
-- The stats themselves live in hlstatsx_lan on the data server and lan-web
-- connects as ktp_lan with no privilege there, so the endpoint cannot query
-- them. Same split the award tables already live with: the build reads the
-- stats DB over SSH and writes the shaped rows here.
--
-- Two tables because "no such match" and "a match with no rows" are different
-- answers and the page has to tell them apart. lan_matches is the curated
-- tournament set (match-teams.json, 56); a key absent from it is a 404.

-- Loaded from match-teams.json. `closed` is 0 for a match whose logging died
-- before it could close -- real play with no result, which still gets a page.
CREATE TABLE IF NOT EXISTS lan_matches (
  match_key   VARCHAR(64)  NOT NULL,
  edition     VARCHAR(32)  NOT NULL,
  day         VARCHAR(8)   NULL,          -- 'MM-DD', as the match index writes it
  map_name    VARCHAR(64)  NULL,
  team_a      VARCHAR(96)  NOT NULL,
  team_b      VARCHAR(96)  NOT NULL,
  closed      TINYINT(1)   NOT NULL DEFAULT 1,
  loaded_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (match_key),
  KEY idx_edition (edition, day, match_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Rewritten wholesale by each load. Nothing operator-authored lives here.
--
-- ⚠️ HALF 1 AND 2 ONLY. Half 0 is ktp_match_stats' own match total, and storing
-- it alongside the halves doubles every figure the endpoint sums. The CHECK is
-- there because a comment saying so is what the trap has already defeated
-- twice; the endpoint's WHERE clause repeats it so relaxing one is not enough
-- to reintroduce the bug.
--
-- team is the club name the build resolved, not Allies/Axis and not 1/2: a
-- player can appear on either side across the weekend and the scoreboard is
-- read one match at a time.
CREATE TABLE IF NOT EXISTS lan_match_scoreboard (
  match_key    VARCHAR(64)  NOT NULL,
  half         TINYINT UNSIGNED NOT NULL,
  steam_id     VARCHAR(32)  NOT NULL,      -- canonical 'Y:Z', no STEAM_ prefix
  player_name  VARCHAR(96)  NOT NULL,
  team         VARCHAR(96)  NOT NULL,
  kills        INT NOT NULL DEFAULT 0,     -- match record
  deaths       INT NOT NULL DEFAULT 0,     -- match record
  headshots    INT NOT NULL DEFAULT 0,     -- match record
  damage       INT NOT NULL DEFAULT 0,     -- match record
  flags        INT NOT NULL DEFAULT 0,     -- HLStatsX control points + areas
  assists      INT NOT NULL DEFAULT 0,     -- HUD; the match record has no assists
  best_streak  INT NOT NULL DEFAULT 0,     -- frag log, rebuilt from the kills
  PRIMARY KEY (match_key, half, steam_id),
  CONSTRAINT ck_halves_only CHECK (half IN (1, 2))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
