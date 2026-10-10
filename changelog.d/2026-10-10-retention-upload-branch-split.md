### `scripts`: `ktp-ac-retention.sh` stops calling the evidence store missing when retention is off (2026-10-10)

The upload sweep was guarded by one condition — `-d $UPLOADS_DIR` **and**
`UPLOAD_RETENTION_DAYS -gt 0` — whose single else branch printed
`WARN <dir> missing; skipping upload sweep` for both failures. An unset
`UPLOAD_RETENTION_DAYS` defaults to 0, so the ordinary opt-in default reported the
evidence store as absent while its day-dirs sat in place.

- Three outcomes instead of two: a missing directory still warns on stderr, a
  configured-off sweep says `upload sweep is off (UPLOAD_RETENTION_DAYS=N);
  retaining all bundles` on stdout, and the sweep itself is unchanged.
- The directory is tested **first and separately**. Checking retention first would
  have made the missing-store warning unreachable on every host that leaves the
  variable unset, which is all of them by design.
- The off message goes to stdout and carries the value that caused it, matching
  sweeps 4 and 5 rather than mailing cron a WARN for a correct configuration.
- Behaviour is unchanged: 0 or unset still retains everything, and the cron's
  36500 still sweeps. Only the reporting moved.
- `tests/unit/test_ac_retention_upload_branch.py` runs the shipped script through
  the sibling module's harness, with mutations that restore the combined guard,
  swap the branch order, silence the off message and drop the zero guard.
- A probe note in that module's docstring: the warning is interpolated, so
  grepping the rendered phrase returns zero on a script that plainly emits it.
  Grep the format string.
- Not run here: the installed copy on the data server. The repo change is not a
  deploy, and the live-script inventory row is unchanged.
