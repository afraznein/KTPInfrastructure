### Added
- `scripts/ktp_mysql_ro.py`: data-server MySQL reads as `ktp_ro`, a login granted only
  `SELECT` on `hlstatsx` and authenticated by `auth_socket`, so no password exists. Before
  sending a query it requires the server to answer, on the same connection, that the
  login is `ktp_ro@localhost`, that no grant goes beyond `USAGE`/`SELECT`/`SHOW VIEW`, and
  that a statement it cannot run comes back as ERROR 1193; any answer missing is exit 2
  and nothing is queried. Measured on MySQL 8.0.46 in a throwaway container:
  `SET SESSION TRANSACTION READ ONLY` binds root, but `START TRANSACTION READ WRITE`,
  `SET SESSION transaction_read_only=0` and `SET SESSION TRANSACTION READ WRITE` each
  wrote afterwards (also under `--init-command`) and `SET GLOBAL` was never blocked, while
  a SELECT-only login refused every write with ERROR 1142. The login itself is created by
  an operator-applied migration; until then the helper refuses. Runbook:
  `docs/runbooks/MYSQL_READ_ONLY_READS.md`.

### Fixed
- `ktp-corpus-integrity-guard.sh`: its header said the read-only directive "binds the
  credential it is given and no other". It binds root too; what it cannot do is stop the
  session revoking it, or protect a path that never sends it. Comment corrected; no
  behaviour change.
