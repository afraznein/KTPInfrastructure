-- Staff nominations: the first tier of the two-tier award decision. Staff vote
-- here, master admins read the tally and hold the checkbox in
-- lan_award_selections.
--
-- ⛔ NOT lan_award_votes. That is the players' live ballot on lan_awards and
-- nothing in this feature reads or writes it.
--
-- A separate file rather than an edit to 0015/0016, because the runner tracks
-- by filename -- anyone who already applied those would never see the change.
--
-- Presence of a row IS the vote, so un-voting is a DELETE and there is no
-- stale `false` to reconcile. match_key defaults to '' rather than NULL so
-- weekend rows can sit in the primary key.
CREATE TABLE IF NOT EXISTS lan_award_staff_votes (
  edition     VARCHAR(32)  NOT NULL,
  award_slug  VARCHAR(48)  NOT NULL,
  match_key   VARCHAR(64)  NOT NULL DEFAULT '',
  voter       BIGINT UNSIGNED NOT NULL,
  voted_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (edition, award_slug, match_key, voter),
  -- The tally reads one scope at a time and groups by award; the primary key
  -- orders award_slug before match_key, so it cannot serve that.
  KEY idx_tally (edition, match_key, award_slug)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
