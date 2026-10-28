### Fixed
- `hlstatsx-ingest-monitor.py` reads `unresolved_actions` as a delta against saved state,
  the way it already read `sql_failed`. The count is process-lifetime, so reporting on
  "above zero" meant one player's bind to a command `dod.so` does not implement red the
  hourly unit for the life of the daemon -- it fired about 24 times against a set that had
  not changed in over a day. A count below the last one is a daemon restart, and the codes
  in the new generation count as new rather than as a fall.
- The finding now names the offending code when the daemon's first-sighting line is in the
  window, and says it cannot when it is not. It no longer prescribes "Seed the table":
  `voice_bazooka`, the live example, is absent from `dod.so` (`voice_bazookaspotted` is the
  real token), so seeding it would invent a row for a command the game has no notion of.

### Changed
- `docs/LIVE_SCRIPT_INVENTORY.md` marks the `hlstatsx-ingest-monitor.py` row SUPERSEDED. The
  deployed copy was byte-identical to the pinned commit, so the row described the host
  correctly until this change moved the repo source past it. Read the token as an install
  being owed rather than as the row being wrong; re-pinning needs a read on the host.
