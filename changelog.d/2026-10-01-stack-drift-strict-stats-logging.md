### `tier2`: the stack-drift checker now compares `stats_logging.amxx` and `admin.amxx` (2026-10-01)

Both plugins load on every fleet instance and were in neither `PLUGINS_STRICT`
nor `PLUGINS_TESTMODE` in `ktp-tier2-stack-drift.py`, so nothing compared them
and the runner's `stats_logging.amxx` fell behind the fleet without an alarm.
They are now strict. A new test fails if any plugin in the online
`plugins.ini` is missing from both lists. Because `sync-runner-stack.py` takes
its list from the checker, `--apply` now syncs them as well.
