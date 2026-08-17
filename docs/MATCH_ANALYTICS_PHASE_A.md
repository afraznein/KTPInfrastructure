# Match analytics Phase A

Phase A generates a local, descriptive match report from a persisted Lane B
SQL fixture. It does not connect to a shared database, call a website, update a
rating, or publish positional data.

## Outputs

- canonical player-match box score (`JSON` and Markdown)
- per-player/per-weapon descriptive facts
- capture credits, separately from unique capture events
- explicit `PASS`, `WARN`, or `FAIL` source-quality checks
- one all-player aggregate position-sample count used only as a coverage check

Raw individual position samples, paths, zones, and heatmaps are deliberately
excluded. Coordinates can support later kill-angle derivation, but only pooled
positional products may be published.

## Run locally in the Lane B image

The image supplies the private MySQL/MariaDB server and client used by the
existing E2E harness. Network access is disabled for the report run.

```bash
docker run --rm --network none \
  -v "${PWD}/tests:/work/tests:ro" \
  -v "${PWD}/scripts:/work/scripts:ro" \
  -v "${PWD}/sql:/work/sql:ro" \
  -v "${PWD}/build:/work/build" \
  -w /work ktp-lane-b:dev \
  python3 scripts/match_analytics.py \
    tests/e2e_stats/fixtures/regression-2026-08-14-anzio-5match/match-1/hlstatsx-fixture.sql.gz \
    --output-dir build/match-analytics
```

If a dump contains more than one `match_id`, add `--match-id ID`.

The command returns nonzero when the match receives `FAIL`, making it suitable
for a regression gate while still writing the diagnostic report. `WARN` is a
successful command because older fixtures may legitimately lack an optional
capture source.

`tests/e2e_stats/fixtures/analytics-phase-a-contract.sql` is a small 12-player
query-contract fixture covering every Phase A source. It is deliberately not a
bot-behaviour or performance fixture. The committed 2026-08-14 full-match
fixtures predate the bot roster-width and StatsMe fixes, and should receive
`FAIL`/`WARN` rather than being silently repaired by the report generator.

## Source queries

All queries are checked in under `sql/analytics/` and contain only `SELECT` or
`WITH` statements. `ktp_match_stats half=0` is used only for reconciliation;
raw match-tagged event tables produce the canonical totals.

Raw accuracy is reported by weapon with a Garand chamber-clearing caveat. It is
not a player-ranking or KTPR input.
