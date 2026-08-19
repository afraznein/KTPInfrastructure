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
- the dump came from the expected server, when `--expected-server-id` is set;
- supplied logs contain no `KTP_HEALTH` failures/retries/unresolved actions,
  explicit unresolved-action warnings, or SQL errors;
- the match's retention class, age, and current 14-day eligibility are visible.

Omitting logs produces `WARN`, not a false pass. A failed required source,
classification, ownership, server, analytics, or log check produces `FAIL` and
exit code 1. The retention result is evidence only; this tool never purges.
Draft and draft-OT remain retained. Scrim, 12man, and `*-TEST` remain eligible
only after the configured retention window.

## Private shadow timelines

`scripts/match_analytics.py` schema version 3 adds a `shadow_timelines` object:

- fast 2k/3k-or-higher sequences;
- basic time-window trade kills;
- the first kill/duel in each half;
- pairwise head-to-head kills and differential;
- the next same-team flag capture after a fast multikill.

Defaults are 10 seconds for a fast multikill, 5 seconds for a trade, and 30
seconds for objective conversion. Every report records these values. Override
them with `--multikill-seconds`, `--trade-seconds`, and
`--objective-conversion-seconds`; comparisons are meaningful only when reports
use the same configuration.

The definitions are deliberately conservative:

- a multikill is a non-overlapping same-player sequence whose first and last
  kills fit inside the configured window;
- a basic trade is the victim's roster teammate killing the original killer
  in the same half and inside the trade window;
- objective conversion is the next same-team flag-control event inside its
  window, not an inferred capout, score, or causal claim;
- replay-compressed fixtures retain opening-duel and head-to-head ordering but
  suppress all timed multikill, trade, and conversion inferences.

This data is `private_shadow_only`. It stays in local report artifacts, makes
no database/API/site writes, and has no KTPR or other rating impact. Trade
distance, line of sight, and opportunity are not yet available, so the output
must continue to say “basic trade” rather than “trade eligible.”

## Preprod review order

1. Run unit and query-contract tests locally.
2. Merge the feature PR into `preprod`.
3. Run Lane B and generate a bundle from its fixture; missing operational logs
   may leave this synthetic bundle at `WARN`.
4. After deployment to the canary game port, collect the real SQL dump plus
   game and daemon logs and require a `PASS` bundle.
5. Review the private shadow output for plausible windows and identities. Do
   not publish it or feed it into ratings.
6. Only then raise the separately reviewed `preprod` to `main` PR.
