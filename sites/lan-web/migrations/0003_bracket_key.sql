-- Stable match key for bracket slots (QF1, SF2, PA, LSF1, LF, ...) so W:/L:
-- source references resolve deterministically.
ALTER TABLE lan_bracket ADD COLUMN mkey VARCHAR(8) NULL AFTER bracket;
ALTER TABLE lan_bracket ADD UNIQUE KEY uq_bracket_mkey (mkey);
