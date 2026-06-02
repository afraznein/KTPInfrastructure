-- "Now Playing" station/server board. `connect` is shown to logged-in operators,
-- `password` is admin-only, `now_playing` is free text staff update live.
CREATE TABLE IF NOT EXISTS lan_stations (
  id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  label       VARCHAR(80)  NOT NULL,        -- "Server 1" / "Station A — back row"
  connect     VARCHAR(160) NULL,            -- "74.91.x.x:27015" (gated to logged-in)
  password    VARCHAR(80)  NULL,            -- server password (admin-only)
  now_playing VARCHAR(160) NULL,            -- "R3 — dicE vs NoSoul" / "QF1 · game 2"
  status      VARCHAR(12)  NOT NULL DEFAULT 'idle',   -- idle | live | done
  sort_order  INT NOT NULL DEFAULT 0,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
