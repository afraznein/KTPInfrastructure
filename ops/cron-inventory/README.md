# Estate cron inventory

A captured snapshot of the scheduled jobs across the KTP estate — 7 hosts.

```
ops/cron-inventory/<host>/crontab-<user>.cron    user crontabs
ops/cron-inventory/<host>/cron.d/<name>          /etc/cron.d entries
```

This exists because scheduled work kept living only on the boxes: a job would be written, do its
work for months, and be invisible to anyone reading this repo. When something was lost or changed,
there was nothing to diff against.

## Capture dates are PER HOST

There is no single "as of" date for this directory, and pretending otherwise is worse than being
cleanly stale. One host cannot be captured at all, so every refresh from here on is mixed-date by
construction:

| Host | Captured | Note |
|---|---|---|
| `data` | 2026-08-25 | |
| `atlanta` | 2026-08-25 | |
| `dallas` | 2026-08-25 | |
| `denver` | 2026-08-25 | |
| `newyork` | 2026-08-25 | |
| `chicago` | 2026-08-25 | |
| `lanbox` | **2026-08-06** | **Host will not boot** (operator ruling 2026-08-24). Frozen at its last capture. |

⚠️ **`lanbox/` is not stale by neglect and must not be deleted.** The files there are the last
record of what that box ran. An unreachable host and a host with no cron jobs look identical to any
sweep that does not check reachability first — capture with a positive control (`ls -d /etc/cron.d`)
and record UNREACHABLE distinctly from empty.

📌 `data/crontab-root.cron` is **zero bytes on purpose**. root's crontab on the data server exists but
holds no jobs: it was reinstalled empty on 2026-08-11 22:33 and everything it used to run either moved
to `/etc/cron.d` or stopped. An empty capture is the finding; a missing file would hide it.

## This is a SNAPSHOT, not the source of truth

Nothing reads these files. The live crontabs are still authoritative, so a job changed on a box does
not change here. **Re-capture after any cron change** and commit the diff — that diff is the whole
point.

Capture the four root crontabs on the game hosts as `root`, not via `sudo`: `dodserver` has no sudo
grant, so `sudo -n crontab -l -u root` returns "a password is required", which reads exactly like
"there is no root crontab". Atlanta, Dallas, Denver and New York genuinely have none; Chicago does.

## Secret scan

⚠️ **Re-run the scan before committing a refresh.** This repo is PUBLIC, and it is how the fleet SSH
password leaked in 2026-05. A scan that reports zero is only meaningful if it can report non-zero:
control-test it against a known-bad string first.

Last refresh: **0 findings across every captured file**, scanned value-by-value against the live,
retired and hostinfo sets in `$KTP_SECRET_INVENTORY`. The control was a live value planted in a file
inside the same scope, and it was found — so the zero is a measurement, not an absence of evidence.

Cron here invokes scripts, and those scripts source their secrets from `/etc/ktp/*.conf`. That is the
reason this directory is publishable at all, and it is the property to preserve: a job line that
inlines a credential must be fixed on the box, not redacted here.

## Scripts referenced by these jobs

All are in `scripts/` or `monitoring/`.
