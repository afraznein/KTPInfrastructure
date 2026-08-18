-- Not every demo belongs to a tournament match. Draft night, scrims and
-- twelve-mans were played by the same people on the same servers and the old
-- form had nowhere to say so, which is why uploaders typed "DRAFT" into the
-- free-text note. This gives that a field.
--
-- 'match' is the default so every existing row keeps meaning what it meant:
-- a demo attached to a schedule or bracket match, or to nothing at all.
ALTER TABLE lan_demos
  ADD COLUMN category ENUM('match','draft','scrim','12man') NOT NULL DEFAULT 'match';

CREATE INDEX idx_demos_category ON lan_demos (category, uploaded_at);
