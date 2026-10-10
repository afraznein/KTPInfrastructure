# Runbook: data-server config traps

**What:** ways a routine change on the data server produces a result that looks
right and is not. Each one has cost real time; each has a cheap check. No count
here on purpose: this opened with "four" while the file carried more, which is
the same silent-staleness shape the runbook is about.

**When:** before editing nginx vhosts, adding a line to a `cron.d` file,
changing observability retention, or reporting a disk number.

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

## An env line APPENDED to a `cron.d` file never reaches the job

cron builds each job's environment from the assignments it has read **so far**,
in file order. So a variable added at the end of `/etc/cron.d/<name>` sits below
the job line and is never exported into it. The string is in the file, a
`grep -c` for it returns 1, and the job runs on its script's default.

This is the ordinary way a one-line retention or switch install becomes a silent
no-op: the obvious edit — append — is the wrong one. Put assignments **above**
the schedule line, which is where every file under `scripts/cron.d/` already has
them.

Verify by reconstructing the environment the job actually gets, not by grepping
the file:

```bash
awk '/^[0-9*]/{exit} /^[A-Za-z_][A-Za-z0-9_]*=/{print}' /etc/cron.d/<name>
```

That output **is** the job's environment. The failure to look for is the gap
between the two reads: `grep -c VAR` returns 1 while the `awk` output does not
list `VAR`. Carry a variable already known to be live as the positive control —
if it is missing from the `awk` output too, the probe is wrong, not the install.

⚠️ **Some of these installs have no verify-by-effect at all, so this structural
check is the only evidence.** `WEAPON_RETENTION_DAYS` is the worked example: at
both the 365-day default and the ruled 36500 the nightly sweep deletes 0 rows
until the oldest row ages out, so the log line is byte-identical either way.

⚠️ **And `ops/cron-inventory/data/cron.d/` is a snapshot of the box, not the
box.** After any hand install there, that copy is stale and a later reader
diffing against it reads the install as absent. Refresh it in the same change.

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

## A size cap is a retention promise that ages out from under you

`/etc/systemd/journald.conf.d/10-ktp-size-cap.conf` (tracked copy:
`ops/data-server/journald.conf.d/10-ktp-size-cap.conf`) sets `SystemMaxUse` and
`SystemKeepFree=2G`. It was `1G` on a comment budgeting "roughly 4 days at the
measured ~230MB/day"; measured, the journal spanned about a day and a half at
roughly 750MB/day, mostly the hlstatsx daemon's "Flushing player updates" lines.
The cap is now `8G`, sized for about ten days at that rate. **A cap in bytes buys
a retention window in days only at a rate nobody re-measures**, and nothing
anywhere reports that the window has shrunk, so the comment in the file is a
procedure rather than a number.

Until the 8G file is installed on the host, `/var/log/syslog*` (`ForwardToSyslog=yes`) was the
longer-lived copy of everything the journal carried. That inverts at 8G, but
syslog is still rotated by size, so the journal is the one to read first only
after you have checked its oldest entry.

Two consequences worth separating:

- `journalctl --list-boots` showed a single boot whose first entry was two days
  old against an uptime of thirteen days. That is rotation, not a reboot —
  read it as "the journal no longer reaches the start of this boot".
- `systemctl status` says `Notice: journal has been rotated since unit was
  started` and then prints nothing. The unit state survives; its output does not.

Derive the window rather than trusting the comment:

```bash
journalctl -o short-iso | head -1      # oldest surviving entry
uptime -s                              # compare: earlier means rotation
```

**For a unit whose stdout IS its report, this is data loss, not a missing trace.**
`ktp-identity-reconcile` prints its findings and exits 1 to raise them; the
weekly cadence guarantees a read long after two days. `ktp-systemd-alert` now
appends every capture to `/var/log/ktp-systemd-alert.log`
(`scripts/ktp-systemd-alert.logrotate`), which is where a failed unit's output
should be read from first.

rsyslog is a second copy — `ForwardToSyslog=yes` is in effect, so `/var/log/syslog*`
carried findings the journal had already dropped — but not a durable one: its
logrotate stanza is `rotate 4` with `maxsize 1G`, and on this box the size trigger
fires every couple of days, so that window is around a week and varies with load.
Useful for a recovery, never something to design around.

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

## A map's texture WADs are NOT under `maps/`, and one 404 there is correct

The engine prepends `dod/` to every download request and asks for a map's texture wads at
`/dod/<name>.wad` — **one level above `maps/`**. So `fastdl.ktpdod.com/dod/maps/` carries `.bsp`,
`.res` and `.txt` and **zero** `.wad`, which reads to a human browsing for one as "they aren't
hosted" while the client is fetching them without trouble.

⛔ **Do not copy wads into `/var/www/fastdl/dod/maps/`.** No client ever requests that path, so a
copy there is dead weight that also has to be kept in sync. The fix is to list them where they
are; `scripts/ktp-fastdl-indexes.py` renders the `/dod/` page's wads as their own linked section
and points `maps/` at it.

⛔ **`halflife.wad` 404s and that is correct.** 28 of the 78 maps on FastDL name it in their
worldspawn `wad` key, and it ships with the base game — every client already owns it. A sweep that
treats every unresolved wad reference as a gap reports it as the biggest one.

⚠️ **A BSP wad reference is not proof a texture is missing.** Textures can be embedded in the BSP's
own texture lump, so a map can name a wad nobody hosts and still render correctly. Measured
2026-09-15: 78 `.bsp`, 14 with no `wad` key at all, 80 distinct wads referenced, 70 on disk; **39
distinct wads unresolved, of which `halflife.wad` is one.** The other 38 span eight maps
(`dod_harrington`, `dod_saints_b1`, `dod_heutau`, `dod_dog1`, `dod_schwetz`, `dod_thunder`,
`dod_ramelle`, `para_glider`) and are absent from `/home/dod/distribute/` too, so they are not a
publish gap. Only `dod_harrington` is in the live mapcycle. Controls on that probe: `dod_anzio.wad`
present in both trees, `zzzNOPE.wad` in neither.

⚠️ **`.res` files are a weaker surface than the BSP.** Only 46 of the 78 maps have one and only 31
name a wad, so a `.res`-only sweep sees 35 distinct wads where the BSP `wad` key sees 80. Read the
BSP entity lump; `scripts/precache_audit.py` already does.
