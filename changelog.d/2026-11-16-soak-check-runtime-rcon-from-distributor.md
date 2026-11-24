### Changed
- `ktp-soak-verify --suite post-restart` now runs `ktp-verify-deploy --check-runtime`, so the
  nightly soak compares each instance's LOADED plugin builds (`amx_ktp_versions` over rcon), not
  only the files on disk. The rcon password comes from `$KTP_RCON_PASSWORD` if set, else is read
  at run time from the distributor's copy, `/home/dod/distribute/dodserver.cfg` (`$KTP_RCON_CFG`
  overrides the path), and is placed in the verify child's environment only. No new copy of the
  secret is written anywhere.
- It refuses that source unless the file holds exactly one non-empty `rcon_password` line
  (quoted or bare, LF or CRLF; `//` comments and look-alike cvars are not counted). On a refusal
  the disk checks still run, the suite posts RED (`Runtime check credential`) and exits 5. The
  value is never printed, and a child that echoes it has it replaced with `<redacted>`.
- New `Runtime check (amx_ktp_versions)` row: `runtime checked N/M instances`. The gate skips the
  whole runtime leg when the reference's own rcon fails and calls a per-instance rcon failure
  yellow, which `--quiet-yellow` silences, so a wrong password would otherwise read GREEN. The row
  is RED when the reference rcon failed or no instance answered, YELLOW when some did not.
  Runtime drift and not-loaded plugins now appear in the RED detail. Gate timeout 300 s -> 600 s.
  ⚠️ Not fielded until `/usr/local/bin/ktp-soak-verify` is reinstalled on the data server.
