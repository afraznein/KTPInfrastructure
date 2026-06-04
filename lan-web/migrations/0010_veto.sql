-- Map pick/ban veto: an append-only log of each ban/pick/decider action for a
-- bracket match. Current state is replayed from the log; the resulting maps are
-- written back to lan_bracket.map when the veto completes.

CREATE TABLE IF NOT EXISTS lan_veto (
  id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  mkey        VARCHAR(8)  NOT NULL,                 -- lan_bracket.mkey
  step_no     INT         NOT NULL,                 -- 0-based position in the sequence
  actor       ENUM('TS','LS') NOT NULL,            -- top seed / lower seed
  action      ENUM('ban','pick','decider') NOT NULL,
  map         VARCHAR(48) NULL,                     -- the map banned/picked (decider auto)
  side        VARCHAR(16) NULL,                     -- Allies/Axis for picks + decider
  by_discord  BIGINT UNSIGNED NULL,                 -- who submitted it
  created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_mkey_step (mkey, step_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
