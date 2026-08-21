# Runbook: data-server config traps

**What:** three ways a routine change on the data server produces a result that
looks right and is not. Each one has cost real time; each has a cheap check.

**When:** before editing nginx vhosts, changing observability retention, or
reporting a disk number.

---

## Backups belong outside the glob

nginx includes `sites-enabled/*` — the whole directory, not `*.conf`. A backup
left beside the file it backs up is therefore **loaded**, and the duplicate
`server_name` it introduces is resolved by filename order, not by intent.

`nginx -t` calls the clash a warning and exits 0, so the config passes its own
test while serving whichever block sorted first. Verify what actually loaded:

```bash
nginx -T | grep '^# configuration file'      # what nginx really read
nginx -T | grep -i 'conflicting server name' # clashes it resolved silently
```

Keep backups anywhere except the directory the service globs. The same shape
applies wherever a service reads a directory rather than a named file — `sa2`
find-globs `/etc/sysstat/`, and `cron.d` entries are read the same way.

## Observability config that changes format, not just volume

`sysstat`'s `HISTORY` is a ceiling, not a preference. Above 28 the collector
switches to `LONG_NAME=y` and starts writing `saYYYYMMDD` instead of `saDD` —
which forks the **current day's** file mid-day, leaving the morning in one file
and the afternoon in another. Raising retention past 28 is a format change;
treat it as one.

`journalctl --disk-usage` reports the default namespace only. A service logging
into its own namespace is invisible to it, so the number can sit comfortably
under `SystemMaxUse` while the directory is much larger. Measure the directory:

```bash
du -sh /var/log/journal          # the real figure
journalctl --disk-usage          # default namespace only
```

## Measuring disk through a symlink

`/var/www/fastdl/demos` is a symlink. `du -sh` does not follow it and reports
effectively nothing, which reads as "the demo archive is empty" rather than
"this tool declined to look". `find` does not follow it either, so file counts
taken there are wrong the same way.

```bash
du -shL /var/www/fastdl/demos    # -L follows the link
```

Prefer the real path when you have it. Any disk figure taken without one of
these is worth re-deriving before it goes in a report.
