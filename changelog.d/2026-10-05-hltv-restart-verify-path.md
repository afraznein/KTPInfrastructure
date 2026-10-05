### `docs`: HLTV restart verification names the real unit and the digest spool (2026-10-05)

The runbook told operators to verify `hltv-restart-all.sh` in `/var/log/hltv-restart.log`, which does not exist: `hltv-restart.service` has no `StandardOutput` redirect. It now points at the state file, `journalctl -u hltv-restart.service`, and the `ops-daily` spool line, and says plainly that clean runs no longer post and that nothing drains the spool yet.
