-- Format C: a Grand Final (upper champ vs lower champ, BO5, no reset) reuniting
-- the two brackets, placement matches that decide each tied tier (3/4, 5/6,
-- 7/8, 9/10) off to the side, and a per-match station/server assignment.
ALTER TABLE lan_bracket MODIFY bracket ENUM('upper','lower','grand','placement') NOT NULL;
ALTER TABLE lan_bracket ADD COLUMN station INT NULL AFTER slot;
