### `scripts`: `ktp-install` refuses to install from `/opt/ktp-infra` (2026-10-13)

`/opt/ktp-infra` is read on purpose and should never be a source of bytes. Nothing enforced that,
and an install from it lands stale bytes while looking exactly like a deploy.

- **Measured instance, found before this guard existed.** `/usr/local/bin/ktp-fastdl-indexes.py`
  was byte-identical to `/opt/ktp-infra`'s copy and differed from `origin/main`'s. Installing
  "the new one" from that checkout would have been a **no-op that reported success**. The fix was
  to install from `/opt/ktp-reports/KTPInfrastructure` instead.
- **Why the staleness is invisible on the box.** That checkout carries its own stale `origin/main`
  ref, so `git rev-list --count HEAD..origin/main` run there answered **22** while the true
  distance to `origin/main` was **304**. Anyone judging it locally underestimates by more than an
  order of magnitude, and `--against-ref origin/main` run there compares against an eight-day-old
  snapshot — which would make an install-freshness check read fresh by construction.
- **Why it is stale at all, which is the part worth knowing.** The only thing on the box that
  fetches it is `ktp-fleet-audit.sh:31`, and that wrapper is the one we are told never to run
  because it makes a check that never ran look like it passed. The stale ref is a side effect of
  that other, correct rule rather than of neglect. `#585`'s fetch-only unit is the intended answer
  and is not installed.
- **The live cost.** `scripts/ktp-ac-retention.sh` there declares `TOKEN_RETENTION_DAYS=22` while
  the installed script runs `105`. A reinstall from that tree narrows the AC token window by 83
  days and logs nothing; the AC API already reports the gap as
  `KTP_AC_RETENTION_WINDOW_SOURCE_SKEW` at every boot.

**Scope, deliberately narrow.** Only the path that copies bytes is refused. `--report
--against-ref` still reads that tree, which is the whole point of having it, and `--record-only`
still works because it verifies bytes already on disk rather than sourcing new ones.

⛔ **Renaming the directory was considered and rejected**: `ktp-demo-publish.sh:43-44` guards on
`$INFRA_ROOT/scripts/import_demo_team_score.py` and runs it as `python3 -m
scripts.import_demo_team_score`, so a rename would have made the hourly demo team-score import
**silently skip** (its missing-file branch reports and continues). The guard fires on the dangerous
act instead of removing a path that legitimate consumers import from.

**No override.** The current checkout is right there, so an escape hatch would only ever be reached
by someone who had not read why this exists.
