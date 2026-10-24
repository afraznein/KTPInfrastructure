### `docs`: two live-host probes that read clean while blind (2026-10-24)

Both nearly became findings in the last two days, and neither trap had a home in this repo.

- **Resolving a live script to its repo source by basename manufactures DRIFT.**
  `/usr/local/bin/ktp-review-integrity-guard` matched `scripts/cron.d/ktp-review-integrity-guard`
  — a cron file — instead of `scripts/ktp-review-integrity-guard.py`, so a correct host reported
  drift. The collision is structural: `scripts/` holds the executable, `scripts/cron.d/` the cron
  file and `scripts/systemd/` the unit, under the same stem. Read `source_path` off the deploy
  manifest row, or require exactly one derived candidate.
- **KTP plugin lines are in `dod/addons/ktpamx/logs/`, not `dod/logs/`, and a GoldSrc log name has
  no year.** A `dod/logs` grep for a producer marker returned zero on every game host hours after
  that producer had gone fleet-wide; the positive control — a known-live marker, also zero in the
  same files — is what caught it. Separately, `L1024*.log` matches every October 24 in a host's
  history, so a per-day figure off that glob is plausible and years wide. Select by mtime with
  `find … -newermt`.

New `docs/runbooks/LIVE_HOST_PROBE_TRAPS.md` holds both, cross-referenced from
`docs/LIVE_SCRIPT_INVENTORY.md` where the by-name lookup is written and pointing at the `/tmp`
core-glob sidecar trap as the same defect class.
