# Automated KTP match reports and AI checkpoints

Status: implementation plan with an executable deterministic bundle builder.

## Outcome

The KTP website should browse immutable, versioned match-report bundles built
from normalized match facts. Code owns extraction, reconciliation, scoring,
privacy enforcement, tables, visualizations, and publication gates. An AI
agent may add evidence-linked narrative or anomaly suggestions at a bounded
checkpoint, but it cannot alter scores, gates, privacy, or publication state.

Current code:

- `scripts/accumulation_v3.py`: deterministic bounded scorer and AI contract;
- `scripts/compare_accumulation_models.py`: three-model sensitivity report;
- `scripts/build_automated_match_report.py`: immutable bundle/manifest worker;
- `config/analytics/accumulation_v3_bounded.toml`: versioned weights; and
- `scripts/match_accumulation.py`: private positional engine with v3 unopposed
  occupancy decay.

## Pipeline and checkpoints

```text
MATCH_CLOSED
    -> FACTS_EXTRACTED
    -> CODE_QUALITY_GATED
    -> DETERMINISTIC_DRAFT
    -> AI_REVIEW_PENDING (optional, non-blocking)
    -> HUMAN_REVIEW_REQUIRED
    -> PUBLISHED

Any blocking code gate or validated AI anomaly -> HOLD
Any source/profile change -> invalidate downstream artifacts and rebuild
```

### Checkpoint 1: deterministic extraction and gates

Code performs all exact work:

- match/half/roster identity and team-at-event resolution;
- capped opponent-damage and victim-life association;
- unique capture grouping and credited-capper lists;
- ownership/topology/capout reliability;
- position privacy separation;
- component scoring and event ledgers;
- model comparison and component-share diagnostics; and
- stable input/profile/report hashes.

Failure never invokes AI to guess missing data. The component is disabled or
the documented fallback is selected.

### Checkpoint 2: optional AI annotation

The worker emits `ai-request.json` after deterministic scoring. It contains
only shareable scores, aggregate facts, quality gates, and stable event IDs.
Raw personal coordinates, heatmap cells, paths, and private position breakdowns
are prohibited.

Useful AI tasks:

- propose a concise match narrative supported by event IDs;
- identify unusual but explainable sequences for a reviewer;
- flag likely collection anomalies for human investigation;
- suggest calibration questions across a real-match corpus; and
- identify aspects not captured by the deterministic taxonomy.

AI may not:

- add, remove, or change points;
- override a quality/reliability gate;
- invent capouts, lives, assists, positions, or causality;
- expose individual movement;
- publish a report; or
- write to the match/stat databases.

Every response must repeat the request's SHA-256. The validator rejects stale
responses and prohibited scoring/privacy keys. AI output remains a separate
artifact so the deterministic report hash does not change.

### Checkpoint 3: human publication review

An authenticated KTP reviewer sees:

- deterministic report and component shares;
- quality gates and disabled features;
- model/rank comparison;
- every contextual bonus with evidence event IDs;
- optional AI narrative/anomaly suggestions; and
- privacy and provenance status.

Only that reviewer can move `DRAFT` to `PUBLISHED`. A blocking anomaly places
the bundle in `HOLD`; it never silently deletes or rewrites the draft.

## Website architecture

### Report worker

Run an idempotent job when both match halves close and the ingestion grace
period expires. Its job key is:

```text
match_id + facts_schema_version + profile_name + profile_hash + source_fingerprint
```

The worker writes to a temporary version directory, verifies hashes and
privacy, then atomically registers the completed bundle. Re-running identical
inputs returns the existing version. A changed source fingerprint creates a
new draft version and marks older AI reviews stale.

### Proposed persistence

| Table/object | Purpose |
|---|---|
| `ktp_report_runs` | Match, profile, source/report hashes, state, timestamps |
| `ktp_report_files` | Immutable bundle paths, hashes, sizes, MIME types |
| `ktp_report_components` | Queryable player/component totals for website tables |
| `ktp_report_events` | Shareable streak/objective/conversion/break ledger |
| `ktp_ai_review_jobs` | Prompt version, request hash, status, retry metadata |
| `ktp_ai_reviews` | Validated advisory output and response hash |
| `ktp_report_publications` | Reviewer, decision, version, reason, audit time |

Private positional working data belongs in a separate restricted store. Public
tables receive only derived `position_points` and approved aggregate map data.

### Website API

Initial read-only endpoints:

```text
GET /api/matches/{match_id}/reports
GET /api/matches/{match_id}/reports/{version}
GET /api/matches/{match_id}/reports/{version}/events
GET /api/matches/{match_id}/reports/{version}/comparison
```

Reviewer-only endpoints:

```text
POST /api/admin/reports/{run_id}/request-ai-review
POST /api/admin/reports/{run_id}/hold
POST /api/admin/reports/{run_id}/publish
POST /api/admin/reports/{run_id}/supersede
```

The public API serves only `PUBLISHED` versions. Draft/private paths must never
be addressable through a guessed URL.

### Website views

1. Match overview: score, map, teams, quality badge, deterministic narrative.
2. Player table: total, rate, bounded components, descriptive K/D/A/damage.
3. Event timeline: streaks, team pushes, captures, conversions, breaks.
4. Model comparison: legacy/damped/v3 ranks and component shares for reviewers.
5. Aggregate spatial panels: map-level only; no personal movement layers.
6. Methodology drawer: exact profile version, formulas, disabled gates, hashes.
7. Reviewer panel: AI suggestions visibly labeled and never mixed into score.

## Bundle contract

`build_automated_match_report.py` currently writes:

```text
manifest.json
report.json
report.md
comparison.json
comparison.md
ai-request.json
ai-response.json       # only after validated optional review
```

The manifest stores file hashes, a wall-clock-independent semantic report hash,
the normalized-facts hash, profile, AI status, and publication checkpoint. Its
invariants explicitly state that AI cannot modify scores/gates or export raw
individual positions.

## Delivery phases

### Phase 1 — local shadow (implemented here)

- versioned v3 profile and deterministic engine;
- reliability gates and privacy boundary;
- comparison report;
- AI request/response validation; and
- immutable local bundle manifest.

### Phase 2 — production fact adapter

- query the canonical tables through a read-only application account;
- build the normalized v1 fact document;
- add source-count reconciliation and victim-life correlation tests;
- schedule on match close with a delayed retry for late rows; and
- store bundles in a private versioned artifact location.

### Phase 3 — reviewer website

- persist report metadata and queryable components/events;
- add authenticated draft/hold/publish workflow;
- render tables and timelines directly from deterministic JSON; and
- keep AI review opt-in until its failure modes are understood.

### Phase 4 — controlled AI worker

- pin model, system prompt, response schema, and token/cost ceilings;
- redact/check payloads before submission;
- validate hashes and response keys on return;
- record latency, failure, disagreement, and reviewer acceptance rates; and
- allow the deterministic report to proceed without AI when policy permits.

### Phase 5 — calibration and public rollout

- shadow multiple human matches across maps/sides/roles;
- review component shares and rank stability;
- version every weight change rather than rewriting old reports;
- publish methodology and reliability badges; and
- promote an official profile only after player/reviewer approval.

## Operational safeguards

- AI failure is non-destructive and does not block deterministic generation.
- A report is never regenerated in place; versions are immutable.
- Profile changes require a new profile name/version and corpus comparison.
- Publication and supersession are audited human actions.
- Website rendering treats report JSON as data, not trusted HTML.
- Raw source access remains read-only for report workers.
- Private positional artifacts have separate credentials, retention, and logs.
- Backfills are rate-limited and use the same idempotency key as live jobs.
