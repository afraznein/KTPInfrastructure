### `scripts` + `tier2`: `sync-runner-stack.py` now syncs the configs the drift checker alerts on (2026-10-01)

`ktp-tier2-stack-drift.py` md5-compares every fleet config outside
`CONFIGS_RUNNER_LOCAL`, but `sync-runner-stack.py` only synced binaries and
strict plugins and left configs to be copied by hand. So when the fleet's
`ktp_maps.ini` changed on 2026-09-30, the heartbeat paged
`runner ce14242f… vs fleet da411a1d…` on every run, and a fresh `--apply` the
next morning reported the runner synced while that file stayed behind.

The sync tool now plans configs from the drift module's own enumeration and
allowlist, the same way it already took its binary list from that module:

- a config the runner holds whose md5 differs from the fleet's gets backed up
  and overwritten, like a drifted binary;
- a config the fleet has and the runner **lacks** is reported and left alone
  unless `--add-missing-configs` is passed. Adding a file nobody has looked at
  is the real judgement call, because it may carry a credential that belongs
  in the allowlist instead;
- nothing in `CONFIGS_RUNNER_LOCAL` is ever written, whatever flags are passed.
  `hud_observer.cfg` stays absent.
