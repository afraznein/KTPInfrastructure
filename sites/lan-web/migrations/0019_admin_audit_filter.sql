-- Make the staff action log filterable.
--
-- lan_admin_audit had idx_at and idx_actor only, so the two questions actually
-- asked of it -- "who was granted staff" and "what happened to this award" --
-- were full scans, and the viewer had no filter at all. One weekend of award
-- ticks buries every staff grant: the log records the rare decisions but shows
-- the routine ones.
--
-- idx_action_id, not idx_action: the viewer reads `WHERE action=? ORDER BY id
-- DESC LIMIT ? OFFSET ?`, and an index on `action` alone leaves the sort to a
-- filesort over the whole matching set.
--
-- target is a prefix match ('player:12', 'philly-2026:weekend-kills-high'), so
-- the plain column index is what a LIKE 'x%' can use. VARCHAR(160) utf8mb4 is
-- 640 bytes, inside InnoDB's 3072-byte key limit, so no prefix length needed.

ALTER TABLE lan_admin_audit
  ADD KEY idx_action_id (action, id),
  ADD KEY idx_target (target);
