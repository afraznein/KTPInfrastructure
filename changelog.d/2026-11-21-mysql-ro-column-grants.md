### `scripts`: `ktp_mysql_ro.py` accepts per-table and per-column SELECT grants (2026-11-21)

The read-only proof split each `SHOW GRANTS` privilege list on commas, so a column grant
such as ``GRANT SELECT (`a`, `b`) ON `hlstatsx`.`t` `` read as the privileges
``SELECT (`a`` and `` `b`)`` and was refused. The staged grants change that narrows
`ktp_ro` from `SELECT ON hlstatsx.*` to per-table and per-column grants would have stopped
every read through the helper.

- The privilege list is now split outside backticks and parentheses, and a column list is
  checked as a list of quoted names, then dropped before the privilege is compared.
- A column list is accepted on `SELECT` only. `UPDATE (`c`)`, `INSERT (`c`)` and
  `REFERENCES (`c`)` are refused, as are any write privilege, `ALL PRIVILEGES`,
  `WITH GRANT OPTION`, a role grant, a routine grant and any line it cannot parse.
- The schema-wide grant still passes, so this lands before the grants change, not with it.
- Tests in `tests/unit/test_ktp_mysql_ro.py`, mutation-checked against the old comma split.
