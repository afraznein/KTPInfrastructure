### `scripts`: a file that is already correct can now be recorded, and the freshness report has a proposed schedule (2026-09-29)

`ktp-install --report --against-ref` landed on 2026-09-28 and immediately raised
the question of what runs it. The answer had to come second, and the reason is
the more useful half of this entry.

**Nothing runs `--report` today.** Measured on the data server, read-only, with
a positive control: `grep -rl ktp-install` over `/etc/cron.d`, `/etc/cron.daily`,
`/etc/cron.hourly`, `/var/spool/cron` and `/etc/systemd/system` returns nothing,
while the same sweep for `ktp-data-server-health` returns two hits. And the
report is not clean: 10 `DRIFT`, 108 `OK`, 2 `TEMPLATED` over 120 recorded paths,
exit 1.

**`ktp-install` refuses a no-op** — *"already has md5 …; nothing to install"* —
which is right, because an install is a copy and copying bytes that are already
there would be a lie in the manifest. But it made one state unreachable: a file
that is correct and was never recorded could not be recorded, since the only way
into the manifest was through a copy that would not happen. Scheduling the report
first would therefore have produced a daily alert naming ten paths that nobody
had any mechanism to clear, which is how a detector gets muted. This estate
already has one that alerted for weeks with nobody consuming it.

So, first: **`--record-only`**. It hashes what is on disk, resolves the blob at
the given commit, and appends the manifest row only if they are equal. It copies
nothing. It refuses bytes that are not that blob; it refuses to run without
`--repo`, because without the blob on the box the row would rest on the caller's
word, which is exactly the drift it exists to clear; it refuses `--template`,
since a filled template cannot equal any blob and there would be nothing to
check; and it refuses `--file`, `--blob-md5` and `--mode`, each of which would
name something other than the file being recorded. A recorded row carries
`previous_md5` equal to `md5`, which the install path can never write because it
refuses a no-op — so the two kinds of row are distinguishable with no new column.
Recording states *which* blob these bytes are, not that they are the newest: an
old commit still reports `STALE` against `origin/main`.

Nine mutations of the new code were run to confirm the tests can fail: dropping
the bytes-match refusal, allowing `--template`, allowing it without `--repo`,
ignoring `--expect-md5`, recording a missing file, writing `previous_md5` as `-`,
dropping the duplicate-row refusal, failing open on an unreadable manifest, and
letting `--file` through. Each one turns a test red; reverting turns it green.

Second, proposed and **not installed**: `ktp-install-freshness.sh` with a daily
timer, an `OnFailure` drop-in and a conf example. Two properties decided its
shape, both from measured failures here. It keys on a durable artifact it writes
rather than on the unit being alive, because a hung unit reads as `active` and
`hltv-demo-renamer` sat "healthy" for 53h while every demo in the window was
lost. And it alerts on a **set transition** rather than a count, because ten
stale paths today will be ten tomorrow and a standing number trains everyone past
it; an unchanged set is silent at any size, a first run records a baseline and
says nothing, and a gap since the last completed run is posted because a gap is
always news. A dirty estate exits 0 on purpose — non-zero means the check could
not run, which is the only thing the `OnFailure` drop-in should ever see.

Exercised end to end against a fake relay: current → silent; one path goes stale
→ one post naming it; unchanged → silent; reconciled with `--record-only` → one
recovery post; unchanged → silent; a five-day backdated gap with the same set →
one post; mirror removed → exit 1 with the result file untouched; relay refused
→ exit 0 with the transition unsaved, and re-announced when the relay returned;
`/opt/ktp-infra` as the mirror → refused outright.

`/usr/local/bin/ktp-install` is `3a8b80ce…`, recorded from `8be1d8f2` on
2026-09-11, and `grep -c against-ref` on it returns 0. Both halves of this entry
exist in git only until that file is installed. `docs/runbooks/INSTALL_FRESHNESS.md`
has the steps, including the one that is easy to get wrong: enabling the timer and
adding it to `CRITICAL_TIMERS` have to happen in the same change, or either the
health check pages for a unit that does not exist or the watcher goes unwatched.
The report is deliberately **not** a required CI check while ten paths are
non-fresh.
