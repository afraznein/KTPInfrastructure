### `docs`: the tier-2 cutover runbook matches the box, and § B has a guarded script (2026-11-11)

`docs/runbooks/TIER2_RUNNER_NONROOT_CUTOVER.md` was written before anything in it had run.
Checked against the data server, it was wrong in six places:

- § A unpacked the runner with a plain `tar xzf` as root, which keeps the archive's uid
  1001. On this box that is `hltvserver`, the HLTV API's user, so the `ktp-ops` tree came
  out owned by it, binaries included, and the tier-2 tree had the same history. Both were
  chowned to root. § A now unpacks with `--no-same-owner` and checks that nothing in the
  tree is owned by anyone but root.
- Verify row a matched the listener on `ps -eo user`, which truncates names past 8
  characters (`ktp-tier2` prints as `ktp-tie+`). It matches on uid now, and so does step 3.
- The window said "weekday daytime" and missed the heartbeat cron, which fires at 00, 06,
  12 and 18 ET. A run while the runner is down alerts twice. The window now keeps 40
  minutes before a slot and 5 after.
- The Monday fleet-audit exclusion went stale when the ops jobs moved to `ktp-ops`.
- The go check used `gh`, which the box does not have. It is local now: no `Runner.Worker`
  process and no worker log younger than two minutes. The log check caught a
  self-skipping PR job that the process check had already missed.
- `serverfiles/` is `ftpuser:ftpuser 775`, not root, so "ownership can stay" on rollback
  cannot restore it. The rollback now gives the restore loop over `owners.txt`.

The runner table also lists the third runner, `ktp-ci-neindataatl`, and proof h pushes an
empty commit to the refuse-root branch instead of opening a new PR.

New `scripts/tier2-runner-cutover.sh` runs § B as one script over `ssh ... "bash -s"`:
preflight by default, `--go` to cut over, an assertion after every step, and a rollback
block printed on any failure once the runner is stopped. It never runs the heartbeat.
`bash -n` and `shellcheck` are clean.
