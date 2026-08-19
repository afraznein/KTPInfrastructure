# Match report readiness package

This package turns a local Lane B SQL fixture into three complementary artifacts:

1. an aggregate-only `PASS`/`WARN`/`FAIL` source-quality gate; and
2. for `dod_anzio`, a spatial atlas containing aggregate heatmaps, event
   windows, combat lanes, objective summaries, and a synthetic baseline; and
3. one sanitized match-report bundle joining the canonical box score,
   readiness findings, optional shadow accumulation totals, and optional
   aggregate atlas.

Both commands are local-only. They do not contain an HTTP client, connect to a
shared database, update ratings, or publish positional data.

## Match readiness gate

Run against a plain or gzipped SQL fixture:

```powershell
python scripts/match_readiness.py build/hlstatsx-fixture.sql `
  --match-id MATCH-ID `
  --output-dir build/match-readiness
```

When a fixture contains exactly one match, `--match-id` may be omitted. The
command writes:

- `MATCH_READINESS.md`, for operator review; and
- `match-readiness.json`, for CI or another reporting process.

The public payload contains aggregate counts and checks only. It contains no
player names, Steam IDs, player IDs, coordinates, individual heatmaps, or
routes. A recursive privacy assertion runs before either file is written.

### Exit and promotion policy

| Result | Default exit | Promotion treatment |
|---|---:|---|
| `PASS` | 0 | Eligible for the next review step. |
| `WARN` | 0 | Review the named source limitation; do not reinterpret unavailable as zero. |
| `FAIL` | 1 | Blocks promotion until the source discrepancy is explained or fixed. |
| invalid input | 2 | Fix the invocation or fixture. |

Pass `--strict` to make `WARN` return 1. The default is intentionally compatible
with historical fixtures that predate roster, StatsMe, or ownership sources.

The gate currently checks:

- match-ID shape, one match record, and a closed end boundary;
- 6v6 test rosters, team balance, participant/roster consistency, and bot
  containment;
- positive half tags and presence of frags, damage, and positions;
- frag coordinate coverage and damage-to-position alignment;
- position sample cadence;
- duplicate frags, damage, captures, and samples, with same-second damage
  duplicates treated as warnings because event time has one-second precision;
- assists, capture grouping, cap breaks, StatsMe, StatsMe2, and ownership
  timeline availability.

## Anzio spatial atlas

The renderer currently supports `dod_anzio`, the only KTP match map for which
the local bot corpus and tested overview transform are available. Run it from
PowerShell with one or more fixtures separated by semicolons:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  scripts/build_anzio_spatial_atlas.ps1 `
  -FixtureSql 'build/run1.sql;build/run2.sql;build/run3.sql' `
  -TargetMatch 'MATCH-ID' `
  -OverviewBmp 'C:\Program Files (x86)\Steam\steamapps\common\Half-Life\dod\overviews\dod_anzio.bmp' `
  -OutputDirectory 'build/anzio-spatial-atlas'
```

Reviewed overview geometry, flags, event windows, thresholds, and radii live
in `config/analytics/spatial_maps/dod_anzio.json`. The wrapper accepts
`-MapConfig` for an alternate reviewed configuration; map geometry is not
embedded in the scripts.

The command invokes the aggregate preparation and renderer stages and places
all final images, the contact sheet, `README.md`, and `atlas-metadata.json` in
the same output directory. Its temporary aggregate renderer payload is removed
unless `-KeepAggregatePayload` is passed.

The image set covers:

- raw and occupancy-normalized kill/death layers;
- team, half, role, weapon-class, headshot, and distance splits;
- kill angles, recurring lanes, openings, trades, fast multikills, and
  isolated deaths;
- the 30 seconds before captures, cap breaks, and reconstructable capouts;
- sample-aligned damage and per-objective efficiency;
- Allied/Axis control and target-versus-leave-one-match-out baselines; and
- explicit coverage panels when a requested dimension is unavailable.

Damage coordinates are approximate: capped damage is assigned to the nearest
attacker position sample within three seconds. Grenade explosion heatmaps are
not produced until exact explosion events are persisted.

## Unified match-report bundle

After Phase A, readiness, private-shadow accumulation, and the optional atlas
have been generated for the same match, assemble the review artifact with:

```powershell
python scripts/match_report_bundle.py `
  --analytics-json build/match-analytics/MATCH-ID.json `
  --readiness-json build/match-readiness/match-readiness.json `
  --accumulation-json build/accumulation/shareable/MATCH-ID.json `
  --atlas-metadata build/anzio-spatial-atlas/atlas-metadata.json `
  --copy-atlas `
  --output-dir build/match-report
```

Omit the accumulation or atlas arguments when those products are unavailable.
The command refuses cross-match inputs and runs a recursive privacy guard. Its
`MATCH_REPORT.md` and `match-report.json` contain player box-score facts and
derived shadow totals, but no Steam IDs, database IDs, coordinates, routes, or
individual heatmaps.

Confidence thresholds live in `config/analytics/metric_confidence.json`.
Synthetic observations validate the calculation but never become competitive
evidence. Human rates below their configured denominator are `low_sample`;
map baselines progress from `emerging` at five human matches to `reviewable` at
20 and `established` at 50. Source completeness and statistical interpretation
are kept separate, so an exact count can still be labeled synthetic or
descriptive.

## Cross-map readiness

Generate the complete KTP match-map inventory with:

```powershell
python scripts/spatial_map_registry.py `
  --output-dir build/spatial-map-readiness
```

The command scans every `config/local/dod-configs/ktp_*.cfg`, merges reviewed
evidence from `config/analytics/spatial_maps/registry.json`, and writes JSON and
Markdown readiness reports. `synthetic_ready` requires reviewed overview/flag/
topology geometry, verified bot waypoints, and five synthetic matches.
`competitive_ready` additionally requires 20 human matches. At present only
Anzio is synthetic-ready; no map is competitive-ready. Other maps must not
inherit Anzio coordinates or objective weights.

## Pre-release hardening

Before identifying candidate commits for another push, run the deliberate
failure suite. It proves that missing hard sources block while optional or
low-sample sources remain visible warnings:

```powershell
python -m pytest tests/unit/test_match_readiness_failures.py `
  tests/unit/test_match_report_bundle.py `
  tests/unit/test_spatial_map_registry.py -q
```

Measure the saved fixture and compare it with the synthetic corpus using
`match_fixture_storage.py`. The report separates the exact portable SQL dump,
match-tagged INSERT payload, and a canonical gzip projection. It explicitly
does not claim to measure live InnoDB allocation or an average human match.

After all candidate work is committed and every checkout is clean, use
`release_candidate_manifest.py` with exactly one `--repository NAME=PATH@REF`
for KTPAMXX, KTPHLStatsX, and KTPInfrastructure. Add the compiled modules,
plugin, daemon files, and configuration with repeated `--artifact NAME=PATH`,
and the staged SQL directory with `--migration-dir`. The resulting JSON and
Markdown bind the rehearsal to exact commits and SHA-256 values; they do not
authorize a merge or deployment.

`measure_command.py` can wrap database-backed report commands inside the
network-disabled Lane B container. It records exit status, elapsed/CPU time,
and peak process/child RSS where the operating system exposes it.

## Golden regression corpus

`tests/e2e_stats/fixtures/regression-2026-08-14-anzio-5match/` is the committed
five-match golden corpus. Its match-tagged row counts are locked in
`readiness-golden.json` and exercised by:

```powershell
python -m pytest tests/unit/test_match_readiness.py `
  tests/unit/test_match_readiness_failures.py `
  tests/unit/test_prepare_anzio_spatial_atlas.py -q
```

Those fixtures are deliberately legacy 16-bot captures. Their expected result
is `WARN`, not `PASS`, because they predate the current 6v6 roster, 5-second
sampling, StatsMe coverage, and flag ownership timeline. The regression tests
ensure those limitations remain visible and that source facts are never
silently repaired.

## First real-match use

The executable capture, analysis, privacy, reconciliation, sign-off, and
failure procedure is in `runbooks/FIRST_REAL_MATCH_ANALYTICS.md`. The first
human match validates capture behavior. It is not enough to establish a
competitive map baseline or recalibrate points.
