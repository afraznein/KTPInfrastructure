# Telemetry collection contract v1

This private-ingestion contract defines the facts that may enter KTP analytics.
It does not authorize a score or a public export. TELEMETRY_QUALITY_MANIFEST_V1
decides metric eligibility after collection.

## Version and ordering

- Producer schema **22** is the complete current contract. Schema 21 is
  membership-only and must be marked partial.
- Every captured marker has a producer-global monotonic sequence, a producer
  event_epoch, game_time, matchid, and half. The daemon validates the
  match-half context before persistence; a replay is idempotent and a conflict
  is rejected.
- Private analysis normalizes event order to match_id, half, game_time, and
  producer_sequence. Native source times remain audit evidence only.

## Record dictionary

| Record | Captured fields | Confidence/provenance rule |
|---|---|---|
| Match context | source match key, map, half, producer epoch, schema/capabilities | private only; downstream uses an opaque run identifier. |
| Participant membership | player key, team, old_team, time, sequence | authoritative team_membership; derive intervals from the append-only ledger. |
| Lifecycle | spawn/death/reset kind, player key, time, sequence | authoritative only when validated life boundaries cover the participant/half; otherwise analysis labels lifecycle inferred. |
| Position | player/team, X/Y/Z, game time, sequence | producer sample; no interpolation through a gap. |
| Frag context | actor/target, weapon, combat state, actor/target X/Y/Z, time, sequence | event-time origin read; nullable coordinates mean unavailable, never (0,0,0). |
| Damage | attacker/target, amount, weapon/hit data, positions, time, sequence | standalone canonical ledger; identity/context must resolve before persistence. |
| Assist | assister/target, actor/target positions, time, sequence | explicit producer assist, not inferred from co-location. |
| Objective definition | map name, flag index/name, X/Y/Z | static flag-position source; reviewed map revision is required for spatial interpretation. |
| Objective state | flag identity, owner, is_initial, time, sequence | state transition; each observed half needs a complete initial baseline before objective-control metrics are available. |
| Objective attempt | objective identity, start/stop/capture disposition, actor/team, time, sequence | validated lifecycle identity and match context. |
| Capture health | type, attempted/enqueued/dropped/emitted counts, sequence range | reconciles producer loss and makes affected metrics partial or unavailable. |

source_event_id, parent/child event links, fire outcome, stance, velocity,
view direction, and a universal map-revision registry are **not** present in
v1. Consumers must report those properties as unavailable rather than infer
them.

## Required handling

1. Raw identities, coordinates, timestamps, match keys, source paths, and
   linkable participant timelines remain inside private ingestion.
2. Direct event coordinates and aligned sample coordinates are distinct:
   analytics must retain origin/provenance and matching age where an alignment
   is used.
3. Missing initial state, objective geometry, lifecycle coverage, cadence, or
   capture health cannot be represented as zero contribution.
4. Public artifacts may contain only privacy-suppressed aggregates and a
   versioned quality/provenance summary; see the quality manifest for gates.

## Current verification

The producer/daemon self-tests cover sequence validation, replay handling,
lifecycle boundaries, objective state, membership transitions, and schema-22
capability authorization. The local bot harness additionally proves that a
6v6 -TEST match reaches MATCH_START with all twelve roster records persisted;
it is development evidence, not production certification.
