# Official team-score telemetry v1

This slice retains and projects the game engine's team score as
`source: "engine-team-score-v1"`. Rows come from the `hltv-demo` importer, which
reads the score out of HLTV demos. It is deliberately separate from player
points, capture credits, KTPR, and the experimental accumulation models.

## Provenance

**Authority (operator ruling 2026-10-05):** for official team scores, the
`hltv-demo` importer's ledger (demo-derived rows in
`ktp_team_score_observations`) is authoritative. The in-game result that
KTPHudObserver relays, stored in `ktp_match_reports` and built by
`scripts/in_game_result.py`, is its cross-check, not a second source of truth.
Demo-derived rows are retained.

What is true of the data today:

- The HUD-observer "engine team-score" importer never produced production rows
  and was removed on 2026-09-18 (commit `a64f5cb`). Every row in the ledger comes
  from the `hltv-demo` importer, first loaded 2026-09-18.
- A 2026-10-01 re-measure found the HUD in-game result and the demo-derived score
  agreeing on 56 of 56 per-half scores across 28 matches.
- `ktp_score_events` cannot produce a team final: it has no team column and the
  sides swap between halves.

These tables hold the game engine's own team score. They are **not** the
captain-reported league score. That one is `ktp.match.home_score` / `away_score`
in the website's database, and nothing copies between the two.

Each row names its writer in a `producer` column (`hltv-demo` for every current
row, `KTPHudObserver` for the retired path). Migration 032 added the column with
a CHECK pinning it to `KTPHudObserver`; migration 033 widened that CHECK to admit
`hltv-demo` and 034 scoped the settlement check to the HUD producer. The column
has no default, so a writer that leaves it out fails.

## Authority and ordering

- Only official-v1 `team_score` rows are eligible, and `hltv-demo` rows are the authority for official scores.
- `tick` is fractional `get_gametime()` seconds since the current map started.
  It is stored as `DECIMAL(20,9)` without a tick-rate conversion; no
  `engine_tick` is invented.
- Retained order is `(match_id, half, tick_seconds, event_sequence)`. JSONL is
  HTTP arrival order and may be out of order during the observer's bounded
  settlement window.
- Every row contains Allies and Axis scores plus their opaque stable match-team
  slots. Regulation side swaps and explicit OT mappings are producer facts.
- `ktp_match_end` is comparison-only quality evidence. It never overwrites the
  last valid final `team_score` row.

## Local migration and import

Apply `sql/migrate_023_team_score_observations.sql`, then
`sql/migrate_032_team_score_producer.sql`, `sql/migrate_033_team_score_demo_producer.sql`
and `sql/migrate_034_team_score_demo_settlement.sql`, with the normal local
MySQL/MariaDB migration account. All are forward-only and idempotent. 023 creates a
closed-file ingestion-manifest ledger, an append-only observation ledger, and a
separate conflict-audit ledger. 032 adds the `producer` column and its CHECK to
the observation and manifest ledgers and rewrites their table comments.

Reapplying migration 023 verifies the exact table/column/collation/unique-index
contract, repairs only compatible missing named indexes, and fails on partial or
incompatible pre-existing schema. It accepts the schema both before and after
032, so it stays safe to re-run in either state. 032 refuses to run unless the
tables have exactly the migration-023 shape (optionally with a partial 032 it
can finish), and it verifies its own result before returning.

The order is always 023, 032, 033, 034:

| Database | What to apply |
|---|---|
| Fresh (LAN, test) | 023, 032, 033, 034. `--migrate` applies all four, in that order. |
| Production `hlstatsx` | Already through 034; the hourly import runs `--migrate`. |
| Re-run, once 023 is in place | Any file, any number of times. |

If a table already holds rows when 032 runs, the column default backfills them
with `KTPHudObserver` before the default is dropped.

### Importing: `hltv-demo`

Rows come from `scripts/import_demo_team_score.py` (`producer = hltv-demo`,
migrations 033/034). On the data server it runs hourly from the
`ktp-demo-publish.sh` labels hook; the same invocation works by hand from the
repo root:

```bash
python3 -m scripts.import_demo_team_score   --dod-tools /usr/local/bin/dod-tools-cli   --demos-root /home/hltvserver/hlds/dod/demos --types ktp --since-days 3   --database hlstatsx --defaults-extra-file /etc/ktp/team-score-import.cnf   --migrate --apply
```

Drop `--apply` and add `--sql-out FILE` to print the SQL without touching a
database.

### HUD observer import: retired (2026-09-18)

`scripts/import_team_score_events.py` (the `events.jsonl` + `metadata.json` path
written by KTPHudObserver) was removed in `a64f5cb`; it never produced a
production row. The `read_event_files` validator in `team_score_telemetry.py`
stays: the Lane B e2e fixture and `in_game_result.py` still read observer-format
files, which is the cross-check described under Provenance.

`ktp_team_score_observations` rows with `producer = KTPHudObserver`, if any exist,
remain valid ledger rows; nothing here rewrites or purges them.

## Post-match projection

After ingestion settlement and match finality:

```bash
python3 scripts/project_team_score.py \
  --defaults-extra-file /etc/ktp/team-score-client.cnf \
  --database hlstatsx_lan \
  --match-id MATCH_ID \
  --output-dir build/objective-score/MATCH_ID
```

The output directory contains:

- `objective-score-timeline.json`: canonical key-sorted JSON containing only
  neutral `team-1` / `team-2` labels, half-relative seconds, both scores,
  observation kinds, and quality metadata.
- `objective-score-release.json`: deterministic release id, SHA-256, byte
  length, immutable marker, and draft publication state. A correction produces
  a new digest/release; prior published bytes are not mutated.
- `objective-score-private-release.json`: internal match selector, file and
  manifest digests, lifecycle/finality context, and objective digest used for
  the later analytics join. This file is private and is never a Pages/report
  artifact.

Missing boundaries, score regression, unknown mapping, carryover mismatch,
source-time regression, sequence ties, and duplicate-order conflicts produce an
explicit unavailable projection with no points. A sequence gap, late recovery,
or match-end disagreement produces a partial projection with a quality flag.
Multi-point jumps are retained as the single observed change.

**Do not build on `project_official_score` as it stands: every real observer
stream comes back unavailable.** It reads the 0/0 dip just after a half opens as
a score movement rather than as the not-yet-restored carry, and it compares
`ktp_match_end` through the terminal half's side slots when that row states the
total in half 1's. The match report therefore does not use it; it reads the same
stream through `scripts/in_game_result.py`, whose docstring carries both rules.

The automated Lane B report join validates the private selected match, map,
objective digest, and exact normalized-analytics facts digest, then strips the
entire private binding. Only the strict neutral DTO and its SHA-256 reach JSON,
Markdown, HTML, verification, manifests, or Pages outputs. The supported secondary
`match_report_bundle.py` CLI applies the same rule: `--objective-score-json`
must be paired with `--objective-score-private-release`; it never accepts a
bare public DTO as sufficient join authority. A score-enabled Lane B run
uses the repository-owned paired observer fixture and requires an available
projection; any lane without explicit score collection publishes unavailable
with `incomplete-stream`. The Denver fixtures predate this stream and remain
explicitly unavailable--no score is inferred from them.

## Retention and rollout boundary

The scheduled match retention allowlist includes all four score ledgers. Scrim,
12man, and `-TEST` match rows therefore follow the existing 14-day purge;
competitive, draft, and explicit OT classifications remain retained under the
existing policy.

This change supplies migration, import, settlement/finality validation,
projection, and test/report artifacts. It does not install a service, deploy a
production UI, tail a live file, or alter existing authorization, health, and
diagnostic gates.
