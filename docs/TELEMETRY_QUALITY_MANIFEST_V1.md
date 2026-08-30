# Telemetry quality manifest v1

`scripts/match_readiness.py` publishes `metric_eligibility` with contract
version 1. It is an aggregate-only statement of whether source evidence may be
used by a downstream metric; it does not calculate or authorize a numerical
score.

| Metric | Required evidence |
|---|---|
| `positional_impact` | Closed match, positions, valid halves, authorized schema-22 cadence, and adequate frag/damage spatial coverage. |
| `combat_context` | Closed match, frags and damage, valid halves, roster consistency, and adequate frag/damage spatial coverage. |
| `objective_control` | Closed match, valid halves, authorized schema-22 capture, objective lifecycle reconciliation, and flag ownership coverage. |

Schema-21 capture is a membership-only partial contract. It may support private
roster-interval diagnostics, but it never satisfies the schema-22 requirements
for `positional_impact` or `objective_control`.

States are deterministic:

- `available`: every required check is `PASS`.
- `partial`: no required check failed, but at least one is `WARN`.
- `unavailable`: a required check is `FAIL` or missing.

The manifest carries only check codes and check levels. It must not include
player identifiers, raw coordinates, routes, or per-player evidence.

## Reproducibility provenance

Lane B normalized facts also carry a private `analytics_provenance` record.
Its `build_id` is a deterministic hash of the source-adapter version, scoring
profile, objective rules, reviewed map catalog revision, map name, and objective
geometry source. A different adapter or any of those reviewed inputs therefore
produces a different identifier. Absolute paths, match IDs, participant IDs,
raw times, and raw coordinates are deliberately excluded.

`map_revision.status=unavailable` prevents the source from claiming reviewed
spatial interpretation for an unregistered map. Lane B upgrades lifecycle
confidence to `authoritative_life_boundary_events` only when retained producer
start/death boundaries are valid for the roster and observed halves; otherwise
it remains `inferred_from_frag_and_reset_events`. No consumer may present the
latter as authoritative spawn/death/respawn telemetry.

## Local bot-match verification

After a local `-TEST` match has completed and its SQL fixture is exported, run:

```sh
python scripts/verify_bot_match_telemetry.py path/to/fixture.sql.gz \
  --require positional_impact=available \
  --require combat_context=available
```

The verifier requires a completed `-TEST` match, a passing 6v6 roster check,
and bot containment before applying requested metric expectations. The local
bot topology remains a development harness, not production evidence.
