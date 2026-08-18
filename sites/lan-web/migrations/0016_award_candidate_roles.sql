-- The "best six by position" panel is one award whose six rows are role slots,
-- not tied co-winners, so each row needs to say which slot it fills. Nullable:
-- every ordinary award leaves both NULL, and a row carrying a role is what
-- marks its award as the role panel.
--
-- A separate file rather than an edit to 0015, because the runner tracks by
-- filename -- anyone who already applied 0015 locally would never see a change
-- made inside it.
--
-- rank_pos carries the panel's DISPLAY order for these rows (Rifle #1, Heavy #1,
-- 3rd, Rifle #2, Heavy #2, Sniper), which is not the same as ordering by
-- (role, slot). slot is 1-based within a role, so the two Rifles are 1 and 2.
ALTER TABLE lan_award_candidates
  ADD COLUMN role VARCHAR(16)      NULL AFTER who_alias,
  ADD COLUMN slot TINYINT UNSIGNED NULL AFTER role;
