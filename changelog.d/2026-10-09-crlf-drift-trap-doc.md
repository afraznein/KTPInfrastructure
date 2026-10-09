### docs: a CRLF copy is not a drifted file (2026-10-09)

- `docs/LIVE_SCRIPT_INVENTORY.md` § Method now says to strip CR before calling a live file behind.
  `/opt/lan-web`'s apparent drift was 31 files with CRLF-only differences, left by an old
  Windows-side deploy. Compare with `tr -d '\r' < file | md5sum`, or with
  `git hash-object --path=<repo path>` inside a checkout. Plain `git hash-object` answers
  differently on Windows (`core.autocrlf=true`) and on Linux.
- `sites/lan-web/README.md` § Deploy points at it.
