### Fixed
- `sql/analytics/player_match_fact.sql` no longer sums a `ktp_damage_events` row whose
  `producer_match_id` names a different match into this match's damage columns. The join
  filtered on `match_id` alone, so such a row reached `damage_dealt`, `damage_taken`,
  `team_damage`, `self_damage` and the grenade columns of the wrong box score. A non-NULL
  `producer_match_id` is now authoritative here, as it already is for retention and for
  `damage_timeline_fact.sql` (`afraznein/KTPInfrastructure#780`).
- No published value moves. Measured read-only on the data server's ledger: 0 of
  1,194,978 rows carry a `producer_match_id` that differs from a non-NULL `match_id`,
  against 1,086,911 where the two are equal. The daemon cannot write one today: since
  `KTPHLStatsX` `ea42b79` a validated producer tuple sets `match_id` itself, and an
  unvalidated one stores `producer_match_id` NULL. So this closes a latent hole that only
  historical or injected rows could reach.

### Changed
- The prose behind `damage_reconciliation`'s cross-tag `WARN` said such a row "was never in
  the daemon's accumulators". It was: `ktp_match_stats.damage` is itself a `SUM` over the
  same ledger by `match_id`, so the row sat on both sides and the identity would have held.
  With the fix the two totals genuinely differ by design (ingest counts the row, the box
  score does not), which is still why the check warns rather than fails. The query comment,
  the check comment and the DTO contract row now say that.

### Not done here
- 1,462 historical rows (August and September, four producer matches) carry a
  `producer_match_id` with a NULL `match_id` -- the receipt-time gate that `ea42b79`
  removed. Neither the ingest total nor the box score reaches them. Recovering them into
  box scores would move published values (a schema bump) and would need the cached totals
  recomputed too, or `damage_reconciliation` would fail on exactly those matches.
