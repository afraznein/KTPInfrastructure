### docs: distributor fan-out timing and the aborted-upload incident row (2026-11-15)

- The distributor docs said a change reaches all 24 instances "within ~15 s". The service's own
  `Distribution complete` log lines (2026-11-05 to 11-14) show a 5 s debounce followed by
  18.4-21.1 s of SFTP fan-out for one small file, and 82.1 s for a seven-file map batch. The
  runbooks now say about 25 s and tell you to poll md5s until they converge.
- `ALERT_COVERAGE.md`'s 2026-09-08 incident row called six aborted uploads "lost". The client's
  retry queue already re-offered a dropped upload at next login, and whether those six arrived
  later was never checked, so the row now says that.
