### `docs`: ALERT_ROUTING no longer describes the alert spool as a delivered digest (2026-10-05)

A clean `hltv-restart-all.sh` run (deployed 2026-10-05) appends one line to
`/var/lib/ktp-alerts/ops-daily.jsonl` and posts nothing. Nothing reads that file to Discord:
`drain_digest_lines()` has no caller. The runbook called the line a digest in several places,
including the `KTP_CHANNEL_OPS_DAILY` comment. It now says the spool is a local record only,
and quotes the script's clean-run branch.
