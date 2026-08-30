# Runbook: data-server config traps

**What:** four ways a routine change on the data server produces a result that
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

## Backups in a docroot are not globbed — they are SERVED

The trap above is about a directory a service *reads*. A web root is worse: nginx
does not glob it, it serves whatever is requested by name. So `index.html.bak-<date>`
beside a live page is fetchable by anyone who guesses the filename, and the usual
deploy habit — copy the file, then edit it — creates exactly that.

Nothing warns you. The backup is not in any config, `nginx -t` has no opinion, and
the live page keeps returning 200.

```bash
# what is actually reachable
find /var/www -maxdepth 2 -name '*.bak*' ! -name '*fallback*'
curl -s -o /dev/null -w '%{http_code}\n' https://<host>/index.html.bak-<date>
```

Two fixes, and the second is the one that lasts:

1. Move the files out of the docroot. Delete nothing — a superseded page is still
   a record; it just does not belong on a public path.
2. Refuse the extensions at the server, so the next deploy cannot reintroduce it:

```nginx
location ~* \.(bak|bak-.*|orig|old|save|swp|swo|tmp)$ { return 404; }
```

Two cautions from applying it:

- **Do not copy a variant that also denies `.md`** unless that vhost really has no
  markdown to serve. One of ours serves `README.md` as `text/plain`, and the
  stricter rule would have 404'd it.
- **Verify with a file that exists.** After moving the backups out, a 404 proves
  the file is gone, not that the rule fired. Plant one file and one `.bak` copy of
  it, expect 200 and 404, then remove both.

A regex `location` outranks prefix locations, so check it cannot shadow an ACME
challenge block — give that block `^~` if it is a prefix match.

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
