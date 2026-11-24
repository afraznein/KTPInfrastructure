### `scripts`, `ci`: the outside-list check honours dated holds from `config/ci-install-held.tsv` (2026-11-14)

Ruled 2026-11-14. `scripts/ktp-ci-install --check --scope outside` now reads
`config/ci-install-held.tsv` from the verified baseline. A STALE-OUTSIDE-LIST file with
an unexpired hold prints `HELD ... until <date> (<reason>)` instead of failing the
`outside-list` job, and fails again on its not-after date with nothing to remove. A hold
may run at most 30 days from the day its row was added (`HELD_ON`); a longer or
post-dated one is refused, and a malformed row fails the job loudly. A hold on a file
that is no longer stale prints a note so dead rows get deleted. First hold:
`/usr/local/bin/ktp-demo-retention.sh` until 2026-11-30.

Reporting only: `--install` never reads the file and the allowlisted check ignores it,
so nothing about what CI installs changes. Runbook: docs/runbooks/CI_INSTALL_ALLOWLIST.md.
