# Schema-22 telemetry preprod promotion handover

Status: local implementation only; do not ship from this document without the
reconciliation gate below.

## Branch and base identity

- Infrastructure branch: `feat/telemetry-2s-objectives-grenades-20260825`
- Isolated worktree: `branches/KTPInfrastructure-telemetry-2s-objectives-grenades`
- Frozen base: `a9b8d2fc2a68bc836965c55aa20f528ae314f815`
- That base is the exact merged Pages PR 154 head supplied for local work.

The local `origin/preprod` ref was stale and GitHub authentication was
unavailable when the worktree was created. **Live preprod reconciliation is a
required shipping gate.** Fetch the current remote, prove the frozen base is an
ancestor of live `preprod`, and rebase or merge the feature branch onto that
tip before opening the Infrastructure PR. Resolve against the live tree; do
not overwrite newer Pages or analytics work.

## Cross-repository contract

Promote the matching feature branches into preprod as one coordinated bundle:

1. KTPHLStatsX daemon `0.3.15`, schema `22`, including
   `sql/migrate_022_objective_attempts_grenade_entities.sql`.
2. KTPAMXX producer `stats_logging 1.18.0`, KTPAMXX `2.7.33`.
3. KTPInfrastructure migration artifacts, retention, analytics, Lane B, and
   bot-only Pages validation from this branch.

Do not promote any one repository to `main` until the combined preprod Lane B
run passes with exact commit provenance for all repositories.

## Contract that must remain true

- Position snapshots use a 2-second producer interval. Analytics and readiness
  accept a 1.0-3.5 second median band and report jitter; health authorization
  requires the manifest's exact 2.0-second interval and zero drops.
- Objective attempts store only factual `start`, `complete`, and `stop` rows.
  Valid stop reasons are `capture_stopped` and `context_reset`. Missing starts
  or terminals remain explicitly censored; no boundary is invented.
- Grenade entities store only `tracked` and `removed` observations for weapon
  IDs 13, 14, and 36. Rockets and mortar (29, 30, 31, and 40) are forbidden.
- `removed` is not evidence of detonation, explosion, damage, or a kill. Reports
  must use entity-lifecycle language only.
- Grenade positions are private. Public Pages output may contain only the
  strictly allowlisted aggregate bot-test counts. Production and real-player
  reports must never be sent through the Pages publisher.
- `.draft`, official, and OT data are retained. Scrim, 12man, and `-TEST` data
  older than 14 days are purged, including both new schema-22 ledgers.
- Per-shot telemetry remains backlog-only; this bundle does not implement it.

## Preprod validation gate

Run the repository's canonical local suite after reconciliation, then run Lane
B against the exact preprod bundle. The run must prove:

- migration 022 clean apply, rerun, compatible-index repair, and incompatible
  schema failure using the production-parity ephemeral MySQL path;
- schema 22 manifest authorization and exactly these ten health event types:
  `life`, `damage`, `position`, `frag`, `assist`, `break`, `flag_state`,
  `flag_position`, `objective_attempt`, and `grenade_entity`;
- objective `start -> complete`, capture-stopped, context-reset, and
  orphan/left-censored scenarios through the deterministic synthetic
  schema-22 wire -> real daemon -> ephemeral MySQL witness. This proves the
  transport/parser/ledger contract; it does **not** simulate DODX capture-area
  polling. Judge production polling separately from the live bot match's
  organic objective markers and reconciled producer/daemon health;
- grenade tracked/removed and incomplete lifecycles for 13, 14, and 36, with
  zero rocket or mortar rows;
- approximately 2-second position median, bounded jitter, and zero producer or
  daemon drops, rejects, gaps, correlation failures, or reordering;
- retention integration coverage for both new ledgers;
- Pages publication regenerated only from a five-run, 12-bot `-TEST` artifact
  with protected preprod ancestry and the existing identity/privacy gates.

After those checks pass, review the aggregate report for plausible counts and
privacy, then prepare the coordinated preprod-to-main PRs. Preserve the normal
review and branch-protection checks; do not direct-merge around them.

## Schema-23 position provenance addendum (2026-08-30)

Schema 23 is the next preprod prerequisite and does not enable positional
scoring. The coordinated bundle is `stats_logging` 1.19.0, daemon 0.3.16, and
HLStatsX migration 024 after migration 023. The producer hashes the running
`maps/<map>.bsp` with SHA-256, advertises it in each half manifest, and repeats
it with explicit `alive=1` / `spectator=0` on every alive-only position sample.

The daemon accepts schema 21/22 for their prior capabilities but requires an
accepted schema-23 manifest before persisting this position shape. State must
be exact, the row revision must match the manifest, and any rejection remains
visible in the existing position health reconciliation. Migration 024 is
idempotent and leaves historical columns NULL as honest legacy evidence.

Infrastructure adds `schema23_position_provenance` as a fail-closed
`positional_impact` prerequisite. Private provenance reports the captured BSP
SHA-256 separately from the reviewed spatial-catalog content hash. Promotion
requires all eleven health rows, including `team_membership`, and clean
producer/daemon position counts. No scoring profile or score calculation is
changed by this addendum.
