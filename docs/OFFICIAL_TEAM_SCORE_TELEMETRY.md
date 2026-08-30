# Official team-score telemetry v1

This slice retains and projects the authoritative in-game team score emitted by
the HUD observer as `source: "engine-team-score-v1"`. It is deliberately
separate from player points, capture credits, KTPR, and the experimental
accumulation models.

## Authority and ordering

- Only official-v1 `team_score` rows are eligible.
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

Apply `sql/migrate_023_team_score_observations.sql` with the normal local
MySQL/MariaDB migration account. The migration is forward-only and idempotent.
It creates a closed-file ingestion-manifest ledger, an append-only observation
ledger, and a separate conflict-audit ledger. Reapplying migration 023 verifies
the exact table/column/collation/unique-index contract, repairs only compatible
missing named indexes, and fails on partial or incompatible pre-existing
schema.

Each input must be a non-symlink `MATCH_ID/events.jsonl` with the producer's
adjacent `MATCH_ID/metadata.json`. The metadata must own the same match, map,
canonical match type, exact event count, and an explicitly allowlisted
`sourceServer`; `endedAt` must be non-null and at least 30 seconds old. Both
files are stat/read/restat checked so an append or replacement during import
fails closed. The importer also requires matching, closed `ktp_matches` rows.
The source literal by itself is not authentication.

After that retained local or mounted pair has settled:

```bash
python3 scripts/import_team_score_events.py \
  --defaults-extra-file /etc/ktp/team-score-client.cnf \
  --database hlstatsx_lan \
  --source-server-root denver-4-observer=/srv/hud-observer/matches \
  /srv/hud-observer/matches/MATCH_ID/events.jsonl
```

Use `--validate-only` to perform the full source/schema/settlement validation
without a database write. `--migrate` applies the repository migration first,
but production rollout should normally keep schema deployment as its own
reviewed step. The importer uses the local MySQL client and local/mounted files;
it contains no SSH or live-tail behavior.

Exact raw-row duplicates are idempotent. A different raw row at the same order
key is never chosen arbitrarily or used to overwrite an incumbent: the key is
audited in `ktp_team_score_ingest_conflicts`, future writes for that key remain
blocked, and publication fails closed.

Importer, projector, and scheduled retention all serialize on the same named
MySQL ledger lock. Each operation uses one transaction; projection reads its
manifest, observations, conflict evidence, and analytics lifecycle context in
one consistent snapshot, while retention removes conflict evidence,
observations, manifest, and match rows atomically.

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

This change supplies migration, one-shot import, settlement/finality validation,
projection, and test/report artifacts. It does not install a service, deploy a
production UI, tail a live file, or alter existing authorization, health, and
diagnostic gates.
