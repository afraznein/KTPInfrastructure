### Fixed
- `docs/runbooks/ALERT_COVERAGE.md` said `ktp-weekly-outliers.service` is in the health sweep's
  `FAILED_UNIT_IGNORE`. It is not, and that is the variable whose name-only semantics let the
  `203/EXEC` of 2026-10-12 go unreported — the incident two sections higher in the same file. The
  entry is `FAILED_UNIT_IGNORE_EXIT` at `=1`, which accepts that one exit and no other. The row now
  says so, says the name-only list is empty and must stay empty for this unit, and states the part a
  reader keeps rediscovering: `systemctl --failed` naming this unit is the expected steady state six
  days out of seven, and an empty `--failed` after a Monday that found outliers is the surprise.
  Ruled 2026-11-02: documentation only — the unit and its guard stay exactly as built, because the
  guard already discriminates a real failure from a start failure.
