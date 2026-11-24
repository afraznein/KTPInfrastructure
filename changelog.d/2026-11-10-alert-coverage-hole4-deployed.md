### `docs`: `ALERT_COVERAGE.md` hole 4 closed — the stale-state detector it waited on was already deployed (2026-11-10)

Read-only on the data server.

- **`KTPAdminBot`#21's stale-state field is live.** `/opt/ktp-admin-bot/ops_alert_state.py` is md5
  `e21c26fc9307dad44ba2a601c1611631`, byte-identical to `KTPAdminBot` `origin/main`, installed
  2026-10-14, reads `/var/lib/ktp-data-server-health.json` with a two-hour stale threshold, and
  `ktp-admin-bot` is active. The runbook said *"merged, not deployed"* in two places — the hole and
  the service table — for nearly four weeks after the install.
- **Hole 4 is struck.** Its two halves — the hourly check's silence and the weekly audit's — are
  each covered by a live external detector. What both share, the data server itself being down, is
  host liveness and is recorded as out of scope rather than as a residue.
