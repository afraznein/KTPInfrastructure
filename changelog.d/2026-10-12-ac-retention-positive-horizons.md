### `scripts`: `ktp-ac-retention.sh` refuses a horizon that would delete everything (2026-10-12)

`0` meant opposite things to the two families of sweep in this script and only one
family was guarded. `UPLOAD_RETENTION_DAYS` and `NET_IDENTITY_RETENTION_DAYS` are each
tested at their own sweep, so `0` is a documented hold. `WEAPON_RETENTION_DAYS` and
`TOKEN_RETENTION_DAYS` went straight into `INTERVAL ${n} DAY`, where
`NOW() - INTERVAL 0 DAY` is `NOW()` — so a zero deleted **every row up to now**,
succeeded, and logged a count that read like any ordinary night. A negative was worse:
`INTERVAL -5 DAY` reaches five days into the future and takes rows that have not aged.

- The hazard was the **adjacency**, not any ruled value. The ruled
  `WEAPON_RETENTION_DAYS=36500` sits in `scripts/cron.d/ktp-ac-retention` directly
  beneath a comment block saying `0` is inert — true of uploads, false of weapons. A
  comment cannot refuse, which is why this is a guard rather than a clearer warning.
- Those two are now required to be positive, and both pre-flights run **before the first
  sweep**. A guard placed where the value is used would fire after sweep 2 had already
  deleted, which is not a refusal.
- The other two keep accepting `0`. ⛔ The asymmetry is deliberate:
  `UPLOAD_RETENTION_DAYS` defaults to `0`, so tightening it would turn every host's
  correct configuration into a nightly failure.
- All four also get a shape check, so a typo names its own variable instead of reaching
  `[ "$x" -le 0 ]` and dying as a bare bash `integer expression expected`.
- Exit code 2 and the message on stderr, so cron mails a refusal rather than a silent
  night.
- `tests/unit/test_ac_retention_positive_horizons.py` runs the shipped script through the
  sibling module's harness: 0 and two negatives on each unguarded horizon, a non-integer
  on all four, a leg asserting a refusal reaches the database with **no statement at
  all**, and the hold preserved on the guarded pair. Four mutations — each guard removed,
  `-le 0` inverted to `-lt 0`, and the guarded pair tightened — with the anchor asserted
  present first, because a mutation that does not land runs the unmutated script and
  passes for free.
- Behaviour is unchanged at every value anything currently sets: the shipped defaults
  (365 and 22) and the ruled 36500 all pass.
- Not run here: the installed copy on the data server. The repo change is not a deploy,
  and the one-line cron install this guard protects is still owed and still the
  operator's act.
