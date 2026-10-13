`#693` and `#696` changed what the analytics produce and **did not bump the schema version.** That is what this fixes, and it is worse than stale numbers: the version is the generator's **only** test for *"already current"*, so two different analytics outputs both carried `30`, and a report at 30 is skipped whichever code built it.

## Measured on the live reports table

| | reports | outcome without this bump |
|---|---|---|
| below schema 30 | **613** | regenerate on the timer, pick the fixes up ✅ |
| at schema 30 | **241** | skipped — **237** generated before the merges ⛔ |

All **237 are distinct matches, all two-half, all carrying `positional` and `shadow_explorations`** — so there is no cheaper subset and the per-id list *is* 237. Those reports publish `#693`'s 11.6%-of-frags row loss, `#696`'s `positional_shadow` (wrong for every player in half 1 of every two-half match), `flag_fights`, `damage_conversion` (+9.1%) and `objective_conversion` (12/34 → 31/56).

## The precedent is in the constant's own comment

Schema **19** names this same fix class, in these words:

> *map_control + progression.flag_differential translated engine-side -> report-team convention (were silently backwards in half 1 of every two-half match)*

This follows it. ⚠️ **`positional_shadow` is why a row-count check could never have caught this**: it lost no rows at all (`kills_located` 565 before and after) while every value in half 1 was wrong.

## Scope and safety

**Values only** — no DTO or contract shape change.

✅ **Nothing pins the literal 30** except one deliberate tripwire. Checked: zero equality or upper-bound tests against `SCHEMA_VERSION` in the serving tree; the only guard is `schema_version >= 28` in `fit_class_swing_offsets.py`, which is forward-safe. On the site, `report_schema_version` is *displayed* (`report-provenance.tsx`, `season-review.tsx`) and never compared.

The tripwire in `test_match_analytics_integration.py` asks for exactly this edit — *"Literal on purpose: a bump regenerates the whole corpus, so it should cost a deliberate edit here rather than tracking the constant silently."* The edit is paid and the comment left intact rather than refactored to track the constant, which would destroy the tripwire.

## Local verification — and the gap, stated

Both affected suites are **identical to `origin/main`**:

```
tests/unit/test_report_regeneration.py              base 2F/39P  ->  head 2F/39P
tests/e2e_stats/test_match_analytics_integration.py base 5F/11P  ->  head 5F/11P
   sorted FAILED lists byte-identical, md5 166e74d3216e571947747b03f9d6ff1b both sides
   comm -23 empty, comm -13 empty  =>  zero regressions
```

⚠️ **The assertion I changed is NOT verified on this workstation.** Its test, `test_contract_fixture_generates_complete_private_report`, is one of those five pre-existing failures: it aborts on `MysqlUnavailable: no mysqld/mariadbd binary found` before reaching line 341. **CI's MySQL-backed lane is what reaches it** — if the bump were wrong there, that job is where it shows.

## Deploying it

The serving checkout is already current (`f6c4aa0`). On merge it needs the new commit, then the regeneration. ✅ There is an **operator-held manual regeneration workflow** for this (`tests/unit/test_report_regeneration.py` pins it: operator environment, dry-run default, manual dispatch only, runs on the tier-2 runner against the reports checkout) — so this does not depend on waiting for the timer. Ledgered under `dpl-66bd`.

Coordination-Workstream: infra-half-side-correction

