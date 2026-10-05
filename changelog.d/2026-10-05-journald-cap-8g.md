### `ops`, `docs`: data-server journald cap raised to 8G, drop-in now tracked (2026-10-05)

The drop-in capped the journal at 1G on the premise of about four days at 230 MB/day.
Measured now, the journal spans roughly a day and a half at about 750 MB/day (mostly the
hlstatsx daemon's player-update flushes), so `/var/log/syslog*` was the longer-lived copy.
`/` has ample free space, so the cap is raised to 8G (about ten days at that rate).

- `ops/data-server/journald.conf.d/10-ktp-size-cap.conf` (new): tracked copy of the drop-in,
  `SystemMaxUse=8G`, `SystemKeepFree=2G`, comment rewritten as a property to re-measure.
- `docs/runbooks/DATA_SERVER_CONFIG_TRAPS.md`: cap section updated to match.
- `tests/ops_config/test_journald_cap.py` (new): pins the values.
- Not applied by this change; the live file is installed by hand (steps in the PR).
