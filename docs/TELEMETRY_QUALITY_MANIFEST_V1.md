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

States are deterministic:

- `available`: every required check is `PASS`.
- `partial`: no required check failed, but at least one is `WARN`.
- `unavailable`: a required check is `FAIL` or missing.

The manifest carries only check codes and check levels. It must not include
player identifiers, raw coordinates, routes, or per-player evidence.

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
