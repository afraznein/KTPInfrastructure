### cron inventory: ktp-offsite re-captured after its header was corrected on the box (2026-11-14)

- `ops/cron-inventory/data/cron.d/ktp-offsite` now matches the live `/etc/cron.d/ktp-offsite` byte for byte
  (md5 `99879bbfc78d5dadc0c9f0ac75458777`). The header no longer says a missing conf "fails loudly": a
  missing `/etc/ktp/offsite.conf` fails the `.` itself, `&&` skips the script and nothing reaches the log,
  so these legs are judged by the log's mtime. Comment only; the three schedule lines are unchanged.
- `docs/BACKUP_SCOPE.md` drops the note that the header was still wrong.
