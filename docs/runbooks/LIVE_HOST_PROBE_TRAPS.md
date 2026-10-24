# Runbook: probes against a live host that match more than they mean

Every trap here has the same shape: a probe answers, the answer looks like a measurement, and the
glob or the key behind it covered more — or less — than the question did. Each one has produced a
wrong conclusion on this estate, and each is cheap to avoid once named.

The common defence is a **positive control in the same breath as the probe**. A zero whose control
also returns zero is not a measurement, and in every case below the control is what caught it.

See also `monitoring/crashreporter/README.md` § Sidecar files, where the `/tmp` core glob matches a
processed core's `.bt` and `.reported` siblings and inflates a crash count by one per core — the
same defect in the crash-capture lane.

## Resolve a live script to its source by PATH, never by basename

A file in `/usr/local/bin` and a file in this repo share a name far more often than they share a
role, so matching them by basename manufactures DRIFT out of two correct files.

Measured: `/usr/local/bin/ktp-review-integrity-guard` resolved to
`scripts/cron.d/ktp-review-integrity-guard` — a cron file, which of course has different bytes —
instead of to `scripts/ktp-review-integrity-guard.py`, the executable it was installed from. The
comparison reported drift on a host that was correct.

The collision is structural rather than a one-off. Three directories carry the same stems with
three different roles: `scripts/` holds the executable, `scripts/cron.d/` the cron file that runs
it, and `scripts/systemd/` the unit that schedules it — and `scripts/` also holds `.logrotate` twins
for some of them. Derive the live set rather than trusting a figure written here:

```bash
git ls-tree -r --name-only origin/main scripts/ \
  | awk -F/ '{f=$NF; sub(/\.[^.]*$/,"",f); print f}' | sort | uniq -d
```

**What to do instead.** Read `source_path` off the path's last row in the deploy manifest
(`docs/DEPLOY_MANIFEST.md`); that column exists because the mapping is not derivable from the name.
For a path with no manifest row, derive the candidate set and require **exactly one** — more than
one candidate is the finding, not a tie to break by preferring `scripts/`. And strip CR before
hashing either side, per `docs/LIVE_SCRIPT_INVENTORY.md`.

## KTP plugin lines are not under `dod/logs/`, and the log name carries no year

Two independent ways for a producer-log grep to read clean while blind. Both fired on one morning,
hours after a plugin had gone fleet-wide and was demonstrably emitting.

**The path.** Plugin output goes to `dod/addons/ktpamx/logs/L<YYYYMMDD>.log`, not to the engine's
`dod/logs/`. A grep of `dod/logs` for a producer marker returned zero on every game host while that
producer was live. What caught it was the control: a marker from a known-live producer returned zero
in the same files, which no healthy fleet can do.

**The glob.** A GoldSrc log name is `L<MMDD>` with **no year**, so `dod/logs/L1024*.log` matches
every October 24 in that host's history, not this morning's. On one host that is hundreds of files
and six figures of lines — enough that a per-day figure derived from it reads entirely plausible and
is years wide.

**What to do instead.** Select by mtime, never by the log name:

```bash
find ~/dod-*/serverfiles/dod/addons/ktpamx/logs -name 'L*.log' -newermt '-1 day'
```

and pair every producer grep with a marker you know is live, so a zero is distinguishable from a
blind probe.
