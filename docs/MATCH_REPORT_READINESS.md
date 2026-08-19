# Match report readiness package

This package turns a local Lane B SQL fixture into two complementary artifacts:

1. an aggregate-only `PASS`/`WARN`/`FAIL` source-quality gate; and
2. for `dod_anzio`, a spatial atlas containing aggregate heatmaps, event
   windows, combat lanes, objective summaries, and a synthetic baseline.

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

## Golden regression corpus

`tests/e2e_stats/fixtures/regression-2026-08-14-anzio-5match/` is the committed
five-match golden corpus. Its match-tagged row counts are locked in
`readiness-golden.json` and exercised by:

```powershell
python -m pytest tests/unit/test_match_readiness.py `
  tests/unit/test_prepare_anzio_spatial_atlas.py -q
```

Those fixtures are deliberately legacy 16-bot captures. Their expected result
is `WARN`, not `PASS`, because they predate the current 6v6 roster, 5-second
sampling, StatsMe coverage, and flag ownership timeline. The regression tests
ensure those limitations remain visible and that source facts are never
silently repaired.

## First real-match use

For the first post-deployment human match:

1. save the untouched SQL fixture and server log;
2. run the readiness gate before interpreting any metric;
3. stop on `FAIL`; review every `WARN` explicitly;
4. run canonical Phase A box-score analytics;
5. generate the aggregate atlas only after its coordinate and timing checks
   are acceptable;
6. reconcile the report with the game scoreboard and match log; and
7. retain the report schema version, metric-contract version, fixture hash,
   and generated artifacts together.

The first human match validates capture behavior. It is not enough to establish
a competitive map baseline or recalibrate points.
