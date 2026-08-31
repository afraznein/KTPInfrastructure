# First real-match analytics runbook

Use this runbook for the first human match captured after the stats release. It
creates a read-only, local report from a preserved SQL fixture. None of these
commands connects to the production database, updates KTPR, or publishes a
report.

## Safety boundary

- Analyze an untouched local `.sql` or `.sql.gz` fixture, never the live
  database.
- Run database-backed analytics in `ktp-lane-b:dev` with `--network none`.
- Keep the original fixture and server log immutable. Work from copies if a
  repair experiment is needed.
- Keep `build/first-real/private/` private. It contains per-player positional
  working data and must never be attached to CI, Discord, a website, or a
  shareable report.
- Position and total accumulation points remain shadow-only. They are not
  KTPR.
- Do not change map weights from this match. One human match is descriptive,
  not a baseline.

## 1. Pre-match release record

Before the server opens, record the deployed commit or artifact hash for each
stats component and confirm that the expected migrations, including flag-state
migration 015, are present. Confirm that this is a normal `.ktpmatch`, not
`.testmatch`, and that no test bots can reach a real KTP server.

Record these facts in the operator ticket or match notes:

| Field | Required value |
|---|---|
| KTPAMXX artifact hash | deployed and independently verified |
| KTPHLStatsX commit/artifact hash | deployed and independently verified |
| KTPInfrastructure commit | deployed configuration version |
| Database migration | latest expected migration, including 015 |
| Server clock | synchronized; timezone recorded |
| Expected map and roster | map name, two teams, six players per team |
| Match command | `.ktpmatch`; never `.testmatch` on a real server |

If any version is unknown, capture the match but do not use it to approve the
release until the version is established.

## 2. Preserve the evidence

Immediately after the match, obtain a read-only fixture through the existing
approved backup/export process and copy the complete game-server log. Do not
run an analytical query against production. Put the two files in a new local,
ignored directory:

```powershell
$MatchId = 'MATCH-ID'
$Fixture = 'build/first-real/source/hlstatsx-fixture.sql.gz'
$ServerLog = 'build/first-real/source/server.log.gz'
New-Item -ItemType Directory -Force build/first-real/source | Out-Null
Get-FileHash -Algorithm SHA256 $Fixture, $ServerLog |
  Format-Table -AutoSize |
  Out-File -Encoding utf8 build/first-real/SHA256SUMS.txt
```

The fixture must have a closed match end boundary. Preserve the source files
even if a later gate fails.

## 3. Run the source-readiness gate

```powershell
python scripts/match_readiness.py $Fixture `
  --match-id $MatchId `
  --output-dir build/first-real/readiness
```

- `FAIL`: stop. Preserve all artifacts and investigate capture/ingest before
  interpreting player or positional metrics.
- `WARN`: review every finding and write down whether it is an expected source
  limitation or a release issue. A warning is never silently treated as zero.
- `PASS`: continue, while still reconciling the final report.

For the first human match, specifically verify 12 participants, both half
tags, assists, capture grouping, cap breaks, StatsMe/StatsMe2 coverage,
five-second positional cadence, coordinate coverage, and the flag-ownership
baseline/transitions.

## 4. Build the canonical box score

The image starts an ephemeral database inside the container. Network access is
disabled.

```powershell
docker run --rm --network none -v "${PWD}:/work" -w /work ktp-lane-b:dev `
  python3 scripts/match_analytics.py /work/$Fixture `
  --match-id $MatchId `
  --output-dir /work/build/first-real/analytics
```

Stop if Phase A returns `FAIL`. Its canonical JSON will be
`build/first-real/analytics/$MatchId.json`.

## 5. Calculate private shadow accumulation

```powershell
docker run --rm --network none -v "${PWD}:/work" -w /work ktp-lane-b:dev `
  python3 scripts/match_accumulation.py /work/$Fixture `
  --match-id $MatchId `
  --output-dir /work/build/first-real/accumulation/shareable `
  --private-output-dir /work/build/first-real/private
```

Only `accumulation/shareable/$MatchId.json` may feed the final bundle. The
private JSON exists to audit the calculation locally and must remain private.

## 6. Build the aggregate spatial atlas when supported

First generate the current map-readiness matrix:

```powershell
python scripts/spatial_map_registry.py `
  --output-dir build/first-real/map-readiness
```

Generate an atlas only when the exact map is `synthetic_ready` or
`competitive_ready`. At present that limits the workflow to `dod_anzio`.
Blocked maps must not inherit Anzio coordinates, topology, or flag weights.

For Anzio, combine the human target fixture with the preserved Anzio corpus so
the renderer can make explicitly labeled comparisons:

```powershell
$AnzioCorpus = 'tests/e2e_stats/fixtures/regression-2026-08-14-anzio-5match/match-1/hlstatsx-fixture.sql.gz;tests/e2e_stats/fixtures/regression-2026-08-14-anzio-5match/match-2/hlstatsx-fixture.sql.gz;tests/e2e_stats/fixtures/regression-2026-08-14-anzio-5match/match-3/hlstatsx-fixture.sql.gz;tests/e2e_stats/fixtures/regression-2026-08-14-anzio-5match/match-4/hlstatsx-fixture.sql.gz;tests/e2e_stats/fixtures/regression-2026-08-14-anzio-5match/match-7/hlstatsx-fixture.sql.gz'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  scripts/build_anzio_spatial_atlas.ps1 `
  -FixtureSql "$AnzioCorpus;$Fixture" `
  -TargetMatch $MatchId `
  -OverviewBmp 'PATH-TO-DOD-ANZIO-OVERVIEW-BMP' `
  -OutputDirectory build/first-real/atlas
```

The bot corpus validates calculations only. It is never a competitive norm.
Skip this step for a blocked map and build the final report without atlas
arguments.

## 7. Assemble the review bundle

With a supported atlas:

```powershell
python scripts/match_report_bundle.py `
  --analytics-json "build/first-real/analytics/$MatchId.json" `
  --readiness-json build/first-real/readiness/match-readiness.json `
  --accumulation-json "build/first-real/accumulation/shareable/$MatchId.json" `
  --atlas-metadata build/first-real/atlas/atlas-metadata.json `
  --copy-atlas `
  --output-dir build/first-real/report
```

Without an atlas, omit `--atlas-metadata` and `--copy-atlas`. The review entry
point is `build/first-real/report/MATCH_REPORT.md`; the sanitized machine
payload is `match-report.json` in the same directory.

## 8. Reconcile and sign off

Two reviewers should compare the report to the scoreboard, match log, and
fixture inventory. Complete this checklist before the result is shared or used
as release evidence:

- [ ] Match ID, map, start/end, halves, and teams are correct.
- [ ] Exactly 12 intended human participants appear; no test bot appears.
- [ ] Team and player kills/deaths reconcile, including suicides/teamkills.
- [ ] Assists, damage, capture credits, unique captures, and cap breaks agree
      with the underlying event inventory and known scoreboard semantics.
- [ ] Every readiness `WARN` has a written disposition and no `FAIL` remains.
- [ ] The public bundle contains no Steam/database IDs, coordinates, routes,
      individual heatmaps, or private positional details.
- [ ] Accuracy is labeled descriptive; Garand chamber-clearing behavior is not
      ranked as missed aim.
- [ ] Position/total shadow points are not called KTPR.
- [ ] Atlas layers pool players and disclose whether an input is synthetic,
      low-sample, or human.
- [ ] Source and output SHA-256 hashes, component versions, metric-contract
      version, and report-schema versions are retained together.
- [ ] A second reviewer signs the release evidence.

Counts from a complete source may describe this match exactly. Rates below the
v1 denominators are labeled `low_sample`; the first through fourth human map
matches cannot define a baseline. Five human matches are `emerging`, 20 are
`reviewable`, and 50 are `established`. Only a separately reviewed future
change may use a mature baseline to recalibrate map weights or production
ratings.

## Failure and rollback behavior

These report commands are read-only with respect to shared systems, so there is
no analytics rollback. If capture or ingest is wrong, stop the reporting path,
retain the original fixture/log and diagnostics, and correct the producing
component through the normal preprod release process. Do not repair production
rows in place and do not replay a fixture into production. A corrected report
must identify its new source hash and retain the failed result for comparison.
