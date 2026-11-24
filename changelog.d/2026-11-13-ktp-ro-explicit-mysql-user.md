### Fixed
- `scripts/ktp_mysql_ro.py`: both the proof and the query now pass `--user=ktp_ro` to
  `mysql`. Measured on the data server (MySQL 8.0.46): under `runuser -u ktp_ro` without
  it the client connected as `root` and `auth_socket` refused it with ERROR 1698, so the
  helper could never get past its proof; with it `CURRENT_USER()` is `ktp_ro@localhost`
  and the proof passes. Runbook example corrected to match, and a unit test now requires
  the `mysql --user=` to equal the `runuser -u` account.
