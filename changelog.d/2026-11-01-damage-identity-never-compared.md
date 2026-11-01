### Added
- Two `quality` checks in `scripts/match_analytics.py` for an identity nothing in the tree
  ever compared. `ktp_match_stats.damage` is every hit the attacker landed -- the ingest
  query groups `ktp_damage_events` by `attacker_id` with no victim join and no team
  predicate -- while `players[].damage_dealt` is opponent damage only. The comparable
  quantity is `damage_dealt + team_damage + self_damage`, and nothing asserted it:
  `aggregate_reconciliation` covers kills and deaths only, `damage_balance` compares dealt
  against taken and loses the same rows on both sides, and `legacy_damage_source` speaks
  only for matches without the per-hit ledger. A match's 6621 against 6460 was therefore a
  figure somebody wrote on a board rather than a check result (`afraznein/KTPInfrastructure#780`).

  - `damage_reconciliation` asserts the identity. It is **WARN, not PASS**, when
    `ktp_match_stats` half=0 carries no damage figure at all: the daemon writes `NULL`
    damage for a half it has no ledger rows for, so an absent figure is a different answer
    from a cached zero, and comparing against a `COALESCE`'d 0 would pass every match whose
    report damage is also 0. It is absent entirely on a legacy match and on a match with no
    per-hit rows, where the existing checks already speak.
  - `damage_partition_exhaustive` asserts the identity's own precondition. The three CASE
    arms in `sql/analytics/player_match_fact.sql` read both teams through `LEFT JOIN
    roster`, so a hit whose victim is absent from `ktp_match_players` leaves
    `victim.team <> r.team` and `victim.team = r.team` both `NULL`: neither arm fires, the
    damage reaches no column, and the ingest side counts it. `damage_taken` and
    `grenade_damage_taken` carry the mirror hole through the attacker, so both sides are
    measured -- a check watching one would report an exhaustive partition on the other's
    hole. Measured at zero on 20 recent matches when #780 was filed, which makes this a
    latent partition defect rather than a live one; the partition is non-exhaustive by
    construction and the failure is silent in both directions.

- `sql/analytics/quality_inventory.sql` supplies what those checks read: `cached_damage`,
  `cached_damage_rows` (`COUNT(damage)`, so NULL is distinguishable from 0),
  `cached_damage_off_roster`, and the unpartitioned damage and hit counts for each side.
  The unpartitioned predicates use `<=>` so a NULL `victim_id` counts as unpartitioned
  instead of being dropped by a three-valued comparison, and `NOT EXISTS` rather than
  `NOT IN` so a NULL roster `player_id` cannot turn the whole count into a silent zero.

### Changed
- `docs/ANALYTICS_REPORT_DTO_CONTRACT.md` records that `players[].damage_dealt` is not
  comparable to `ktp_match_stats.damage`, names the three columns that together are, and
  names the two checks that assert it. That was disposition 1 of #780 and closes the
  original question.

  **No fourth published column, deliberately.** Folding unresolved-side damage into
  `damage_dealt` would make the numbers agree and the meaning wrong, and a fourth column is
  a contract change -- a `contract_version` row and every consumer of the box score -- so
  the hole is reported as a check result instead. Adding the column stays open; the silence
  does not.

### Verification
- `tests/unit/test_damage_reconciliation.py`, 12 cases, green. Red-tested in five
  directions, each killed on its own test: the identity reading `damage_dealt` alone; the
  no-cached-figure WARN branch removed; the partition watching the dealt side only; a
  column dropped from `INTEGER_COLUMNS` (an unlisted column stays a string, and `"143"`
  never equals `143`); and the query renaming one alias. A dead anchor could not apply, and
  the baseline is green before and after.
- The alias assertion matches the **whole** alias. A substring test passed the renamed
  alias `unpartitioned_hits_taken_x` -- a column no check reads -- which is the one
  mutation that survived the first pass.
- The inventory query parses as one statement with every new alias present, against a
  deliberately broken statement as the control. Read-only; no database was contacted and
  no report was regenerated.

### Not done here
- Disposition 2 of #780 asked for damage inside `aggregate_reconciliation`. It is a
  separate check instead, because that one compares raw event facts against the cache for
  kills and deaths with no coverage gate, and damage needs three: per-hit coverage, a cache
  row, and a non-NULL cached figure. Folding three gates into a check that has none would
  have made its kills verdict conditional on damage coverage.
- The 6621/6460 pair itself is still not re-derived: the board line that carried it does not
  name the match. What ships here is the check that would have made the next one a FAIL.
