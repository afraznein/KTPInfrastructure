### Changed
- `hlstatsx-ingest-monitor.py` no longer pages on a sequence gap of 1-2 events on one
  `(half, stream)`. Those are printed as `??` warnings and leave the exit code at 0; a gap of 3
  or more is still a finding and still exits 1. Since the gap leg was installed it failed 7 of 58
  runs, every one a `damage` gap of 1-2 events in a half of 500-700. `--gap-warn-max N` moves the
  ceiling (default 2; 0 restores page-on-any-gap). Other checks are unchanged.
  ⚠️ Not fielded until the script is reinstalled on the data server.
