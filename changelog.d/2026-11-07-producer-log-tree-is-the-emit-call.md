### `docs`: which log tree a KTP marker lands in is decided by the emit call (2026-11-07)

`docs/runbooks/LIVE_HOST_PROBE_TRAPS.md` said plugin lines are in `dod/addons/ktpamx/logs/` and not
in `dod/logs/`. That is true of the producer it was written from and false as a rule, so it hands
the next reader the same false zero pointing the other way.

- **The emit call decides the tree, not whether the producer is a plugin.** `log_amx()` — and a
  `stock` wrapper over it — writes `dod/addons/ktpamx/logs/L<YYYYMMDD>.log`; `log_message()` writes
  the engine's `dod/logs/L<MMDD><NNN>.log`. Measured on `origin/main`: `KTPCvarChecker`'s
  `ktp_cvar.sma` is `log_amx` ×19 with no `log_message`, which is why the `NETOBS_SNAPSHOT` grep of
  `dod/logs` returned zero on all five hosts; `KTPAMXX`'s in-tree `stats_logging.sma` is
  `log_message` ×22 with no `log_amx`, because HLStatsX parses the engine log.
- **One plugin writes both trees, so the old rule would break working code.**
  `KTPMatchHandler.sma` carries `log_message` ×14 and `log_amx` ×27, and `KTP_MATCH_START` is a
  `log_message` one. `services/ktp-nettest/lib/busy.js` reads it out of `dod/logs` for the
  live-match block, so "correcting" that path to the amxx tree blinds the gate.
- The no-year glob half is unchanged and now says why it is safe in one tree and not the other: the
  amxx name carries `YYYY`, the engine name does not.
