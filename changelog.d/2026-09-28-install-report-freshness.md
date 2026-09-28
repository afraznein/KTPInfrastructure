### `scripts`: `ktp-install --report` can now answer "is this the merged version", not only "has anyone touched it" (2026-09-28)

The deploy manifest has recorded, per installed file, which commit its bytes came
from since it was introduced. `--report` re-hashed each file and compared it to
its row. That answers whether anyone has edited the file in place — a real
question, and not the one anybody was reading it as.

Measured on the data server 2026-09-28, before this change:

```
OK  /usr/local/bin/ktp-tier2-stack-drift.py  f5937dab4c25…  KTPInfrastructure@a029be244fc6:scripts/ktp-tier2-stack-drift.py
```

`OK`, and eight weeks plus two merged PRs behind `origin/main`. The bytes matched
the row; the row was what had gone stale. That file is the Tier 2 stack-drift
checker, so every drift conclusion the heartbeat drew over that window came from
superseded logic, and the integrity report could not say so. The monitoring had
the disease it exists to detect.

It is not one file. Thirteen of the forty non-backup scripts in `/usr/local/bin`
were behind `origin/main` that morning. The 2026-09-15 alert-routing refactor
shows the shape: `ktp-alert-routing.sh` was new, so it got installed and is
current, while every producer it was meant to centralise stayed on its
pre-refactor copy — each one greps zero for `ktp-alert-routing`. The refactor is
half-live, and nothing anywhere is red about it. Nothing installs these files; a
person copies them.

`--report --repo DIR --against-ref REF` resolves each row's `source_path` at REF
and compares the **installed bytes** to what REF holds, so an untouched file
reports `STALE` once the repo moves past it. New verdicts: `CURRENT`, `STALE`,
`SOURCE-GONE` (the ref no longer holds that path), `OTHER-REPO` (a row from a
different repo — one manifest carries several, and those are printed, not
guessed at). A ref that does not resolve exits 2 rather than 0: a freshness
check that could not run must not read as fresh.

One correction falls out of the same work. The existing `--repo` provenance leg
reported `SOURCE-MISMATCH` whenever `git show <recorded commit>:<path>` failed,
which conflates "that commit does not hold these bytes" with "this checkout does
not have that commit". A shallow clone — the default `actions/checkout` — turned
every row from another repo and every older row into a mismatch. It is now noted
and not counted, so an inability to check no longer reads as a verdict.

Run on the live manifest against a full clone of `main`, the new leg reproduces
the survey independently: 59 `CURRENT`, 14 `STALE`, 2 `TEMPLATED`, 10 `DRIFT`,
35 `OTHER-REPO`, exit 1. It also catches what a filename comparison cannot —
`/usr/local/bin/ktp-precache-audit` is installed from `scripts/precache_audit.py`
and a basename sweep misses the rename entirely.

Nothing is wired to run this yet. The intended home is a job on the Tier 2
runner, which already executes on the host that holds the manifest; making it a
required check is the property that matters, because then a runner that stops
reporting blocks a merge instead of going quiet.
