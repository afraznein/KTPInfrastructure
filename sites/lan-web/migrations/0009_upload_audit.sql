-- Upload traceability: capture the uploader's IP (and Discord name for photos,
-- whose uploaders may not be on a roster) so any bad upload can be traced.

ALTER TABLE lan_photos ADD COLUMN uploaded_ip   VARCHAR(45) NULL AFTER uploaded_by;
ALTER TABLE lan_photos ADD COLUMN uploaded_name VARCHAR(64) NULL AFTER uploaded_ip;
ALTER TABLE lan_demos  ADD COLUMN uploaded_ip   VARCHAR(45) NULL AFTER uploaded_by;
