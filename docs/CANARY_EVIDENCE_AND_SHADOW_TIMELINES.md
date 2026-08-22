# Canary evidence and private shadow timelines

These tools turn a post-deployment SQL dump into reviewable evidence without
connecting to production or changing any data. They are staging aids, not a
replacement for the existing Lane B, preprod, or human-canary gates.

## Canary evidence bundle

`scripts/canary_evidence.py` accepts a local `.sql` or `.sql.gz` dump and one
match ID. It restores the dump into a disposable MySQL instance, executes only
checked-in `SELECT` queries, then destroys the instance. It has no production
database or HTTP configuration.

Run it inside the Lane B image so the database engine matches CI and
production:

```bash
docker run --rm --network none \
  -v "$PWD/tests:/work/tests:ro" \
  -v "$PWD/scripts:/work/scripts:ro" \
  -v "$PWD/sql:/work/sql:ro" \
  -v "$PWD/build/canary-evidence:/out" \
  -v "/path/to/canary:/input:ro" \
  -w /work ktp-lane-b:ci \
  python3 scripts/canary_evidence.py /input/hlstatsx-canary.sql.gz \
    --match-id MATCH_ID \
    --expected-server-id SERVER_ID \
    --game-log /input/game.log.gz \
    --daemon-log /input/daemon-stdout.log.gz \
    --output-dir /out
```

The command creates `<match-id>-canary-evidence.json` and `.md`. The JSON is
the full machine-readable evidence; Markdown is the operator summary.

The gate checks:

- persisted match type is non-null and consistent across every half;
- the match is closed and passes the shared roster/aggregate quality checks;
- damage, assists, captures, positions, weapon facts, and flag ownership are
  present;
- every observed flag/half has exactly one ownership baseline at game time 0,
  followed by valid neutral/Allies/Axis transitions;
- producer clocks are populated on the match's frag and damage rows, rather
  than merely present in the schema;
- physical-life capture is active and canonical timed assists reconcile with
  the generic box-score assist count;
- capout and last-flag-defense classifications are marked untrusted unless
  every observed flag has a static position and each half's ownership timeline
  demonstrates at least one complete, non-neutral two-team partition;
- cap-break credits (individual cappers stopped) are reported separately from
  the best available lower bound on distinct break incidents;
- StatsMe kills are reconciled against enemy frags plus teamkills, while its
  death delta is reported explicitly and never substituted for the canonical
  frag/teamkill/suicide ledgers;
- the dump came from the expected server, when `--expected-server-id` is set;
- supplied logs contain no `KTP_HEALTH` failures/retries/unresolved actions,
  explicit unresolved-action warnings, or SQL errors;
- the match's retention class, age, and current 14-day eligibility are visible.

Omitting logs produces `WARN`, not a false pass. Zero producer-clock coverage,
inactive physical-life capture, a canonical-assist mismatch, or a failed
required source, classification, ownership, server, analytics, or log check
produces `FAIL` and exit code 1. Partial producer-clock coverage and unproven
objective topology produce `WARN`: raw evidence remains usable, but dependent
timed or objective classifications must stay suppressed. The retention result
is evidence only; this tool never purges.
Draft and draft-OT remain retained. Scrim, 12man, and `*-TEST` remain eligible
only after the configured retention window.

## Private shadow timelines

`scripts/match_analytics.py` schema version 6 contains `shadow_timelines` plus
aggregate-only `shadow_explorations`:

- fast 2k/3k-or-higher sequences;
- basic time-window trade kills;
- the first kill/duel in each half;
- pairwise head-to-head kills and differential;
- the next same-team flag capture after a fast multikill;
- symmetric basic-trade/death-traded and life-reset revenge analysis;
- producer-clock damage conversion;
- sampled objective pressure with temporal-coverage gates;
- weapon kill-time player separation; and
- DoD-native KAT coverage over completed physical lives.

Defaults are 10 seconds for a fast multikill, 5 seconds for a trade, and 30
seconds for objective conversion. Every report records these values. Override
them with `--multikill-seconds`, `--trade-seconds`, and
`--objective-conversion-seconds`; comparisons are meaningful only when reports
use the same configuration.

The definitions are deliberately conservative:

- a multikill is a non-overlapping same-player sequence whose first and last
  kills fit inside the configured window;
- a basic trade is a same-team reply killing the original killer in the same
  half and inside the trade window; one reply credits the most recent eligible
  death, while the denominator remains team deaths rather than proof of an
  individual opportunity;
- objective conversion is the next same-team flag-control event inside its
  window, not an inferred capout, score, or causal claim;
- replay-compressed fixtures retain opening-duel and head-to-head ordering but
  suppress all timed multikill, trade, and conversion inferences.

This data is `private_shadow_only`. It stays in local report artifacts, makes
no database/API/site writes, and has no KTPR or other rating impact. The
explicit `shadow_timelines` section retains private event-level kill/objective
diagnostics; `shadow_explorations` remains aggregate-only. Raw coordinates,
paths, position timelines, and reconstructed per-life timelines are excluded
from both. Trade distance, line of sight, and individual opportunity are not
available, so the output must continue to say "basic trade" rather than
"trade eligible." See
`FPS_STAT_EXPLORATION_BUNDLE.md` for the exact source and definition contracts.

## Preprod review order

1. Run unit and query-contract tests locally across all affected repositories.
2. Commit the coordinated collection branches and run full Lane B against the
   exact Infrastructure, MatchHandler, AMXX, and HLStatsX SHAs.
3. Open all affected PRs to `preprod` together and do not merge any until the
   complete bundle and its shared manifest are approved and green.
4. Merge in dependency order, rerun full Lane B on the resulting `preprod`
   SHAs, then deploy in the documented schema/daemon/full-restart order.
5. After deployment to the canary game port, collect the real SQL dump plus
   game and daemon logs and require a `PASS` bundle.
6. Review the private shadow output for plausible windows and identities. Do
   not publish it or feed it into ratings.
7. Only then raise the separately reviewed `preprod` to `main` PRs.
