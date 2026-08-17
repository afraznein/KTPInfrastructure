# Match analytics Phase B: real-match shadow validation

Phase B runs the Phase A facts against completed real matches without writing
to the website, ratings, preprod, production, or any shared database. A source
dump is restored into a disposable local MariaDB instance and destroyed after
the reports are written.

## Current validation corpus

The archived Philly 2026 LAN database is the first real-match corpus:

```text
/opt/ktp-lan-archive/philly-2026/lanbox-hlstatsx-20260806.sql.gz
```

It contains 100 canonical KTP match IDs and covers eight competition maps,
full two-half matches, partial starts, reconnect/substitute rosters, open match
boundaries, zero-event records, and missing aggregate-cache records. The local
copy and generated reports belong under `build/phase-b-real/`, which is ignored.

This archive predates the new telemetry pipeline. It can validate kills,
deaths, headshots, teamkills, suicides, roster identity, half/map tags, StatsMe
weapon totals, StatsMe2 hit locations, and legacy aggregate damage. It cannot
validate assists, objective events, per-hit damage/taken, or aggregate position
samples. The report records those sources as **not captured**, never as zero.

## Run locally

Fetch the read-only archive using the existing operator SSH key, then run the
batch in the Lane B image:

```powershell
New-Item -ItemType Directory -Force build\phase-b-real
scp -o BatchMode=yes krodssh@api.ktpdod.com:/opt/ktp-lan-archive/philly-2026/lanbox-hlstatsx-20260806.sql.gz build/phase-b-real/
docker run --rm --network none -v "${PWD}:/work" -w /work ktp-lane-b:dev `
  python3 scripts/match_analytics_batch.py `
  build/phase-b-real/lanbox-hlstatsx-20260806.sql.gz `
  --output-dir build/phase-b-real
```

The `--network none` boundary is intentional. After the one explicit archive
copy, report generation cannot reach any external service. The script loads the
dump only once, inventories source capabilities before compatibility is added,
audits the union of match IDs across all core source tables, writes JSON for
every match, and writes Markdown for representative shapes.

Primary output: `build/phase-b-real/PHASE_B_VALIDATION.md`.

## Legacy compatibility boundary

`sql/compatibility/legacy_optional_sources.sql` creates empty compatibility tables
only inside the disposable restored database. Its columns inherit the archived
`match_id` collation so MySQL 8 dumps can be inspected under MariaDB. It must
not be run on preprod, production, or another shared database.

When per-hit damage is absent, the player report uses `ktp_match_stats.damage`
as explicitly labeled legacy damage dealt. Damage taken and damage differential
remain unavailable because they cannot be reconstructed faithfully.

## Phase B completion gate

The historical pass establishes legacy compatibility and reveals source-data
anomalies. Phase B is fully complete only after at least one post-deployment
real match validates the newly captured assist, objective, per-hit damage, and
aggregate-position sources. That future run remains shadow-only until its
quality checks are reviewed.
