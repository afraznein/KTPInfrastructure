# Runbook: monthly stats-capture audit

**What:** a full-stack run of the stats-capture pipeline against real bot
matches, producing a fresh KTPR fixture and a drift check against a known
baseline.

**Cadence:** monthly, or before anything that changes the capture path.

**Cost:** ~2h20m unattended. Start it and walk away.

**Not a merge gate.** Nightly Lane B and the corpus replay cover the fast
feedback; this exists to catch slow drift — a plugin rebuilt against a newer
DODX, a schema change nobody replayed, an upstream daemon bump.

---

## Why a long run rather than more short ones

Three things only show up at length:

- **Both halves of a real match.** Halftime is a map reload, and the second
  half only works because the roster is re-added by name. A short run
  exercises the same code, but drift in bot behaviour or map load timing shows
  up as a flaky halftime, and one sample cannot tell that from bad luck.
- **A player's history across matches.** The whole point of one roster over
  three matches is that a player accumulates stats on both sides, which is what
  KTPR reads. A single match cannot produce that shape.
- **Rare events.** cap_breaks arrive at roughly one per twenty minutes of play.
  Three matches is six halves; a three-minute run is a coin flip.

## Running it

```bash
# One roster, three matches, two 20-minute halves each, sides swapping.
run_series.sh 3 1200 0 "3,5,7"
#             |  |    |  |
#             |  |    |  bot_skill per match
#             |  |    instance (port 27015 + n, own output dir)
#             |  half length in seconds
#             matches
```

Output lands in `~/lane-b-out/series-0/ktpr-fixture/`:

| File | What it is |
|---|---|
| `hlstatsx-fixture.sql` | the whole database, schema and data — the KTPR artifact |
| `match-series.log` | the game log; `replay_daemon.py` can rebuild the database from it |
| `manifest.json` | every count and verdict from the run |
| `hlstats.out` | the daemon's own output, including its `(IGNORED)` reasons |

Then run the fast checks, which need no game server:

```bash
run_corpus.sh                    # the three stored matches, exact comparison
python3 -m pytest tests/e2e_stats -q
```

## What good looks like

Baseline from **2026-08-10**, three independent 20-minute matches at bot skill
3/5/7. Use these as orders of magnitude, not thresholds — bot AI is not
repeatable, and only the *carriage* columns are exact.

| | skill 3 | skill 5 | skill 7 |
|---|---|---|---|
| frags | 401 | 373 | 424 |
| tagged | 401 | 372 | 423 |
| assists emitted → PPA rows | 37 → 37 | 42 → 42 | 48 → 48 |
| cap_breaks emitted → PA rows | 3 → 3 | 10 → 10 | 4 → 4 |
| suicides | 13 | 28 | 26 |
| players | 16 | 17 | 17 |
| attribution violations | 0 | 0 | 0 |
| real SQL errors | 0 | 0 | 0 |

**The rule that matters: everything emitted must be carried.** Kills equal
frags, assists equal PPA rows, cap_breaks equal PA rows. Those are exact, and a
gap is a defect regardless of how the volumes moved.

Also expected, and not a problem:

- **~16-17 players rather than 12.** new_bot restores bots of its own after
  each map change and KTP's plugin blocks console kicks, so they cannot be
  removed. The twelve named bots are stable; the strays have few stats.
- **five "benign" SQL errors per run.** `ktp_match_players.steam_id` is
  `VARCHAR(32)` and a bot's synthetic id is 36 characters. Real Steam IDs are
  ~19, so production never hits it. Classified, reported, never silent.
- **one untagged frag.** A warmup kill before the match went live. Correct.

## When it differs

Work outward from the cheapest signal.

1. **Did the corpus replay also move?** If yes, the change is in the daemon,
   the seeds or the schema — the corpus is fixed input, so nothing else can
   have moved it. If no, the change is in the game side or in bot behaviour.
2. **Is it a carriage gap or a volume change?** Fewer kills is bot AI. Kills
   that did not become frags is a defect.
3. **Read `hlstats.out` for `(IGNORED)` reasons.** `(IGNORED) BOT:` means
   `IgnoreBots` is not 0; `NOTMINPLAYERS:` means the roster is too small. Both
   are configuration, and both lose rows silently.
4. **Replay the run's own log.** `replay_daemon.py --log match-series.log`
   rebuilds the database without bots, so a failure is reproducible in seconds
   rather than two hours.

## Keeping the fixture

Keep the most recent audit's `hlstatsx-fixture.sql` and its log. If the run
produced something materially new — a map that has waypoints for the first
time, a much larger match, a genuinely different score shape — consider adding
its log to `tests/e2e_stats/corpus/` and re-baselining with
`run_corpus.sh --update`. Say in the commit what moved and why; a baseline
updated to make a test pass is a test deleted with extra steps.

## Known gaps this audit does NOT cover

Stated so a green audit is not read as more than it is:

- **`hlstats_Events_Statsme`.** `stats_logging.sma` skips bots in
  `dod_stats_flush`, so weaponstats are structurally unreachable on an all-bot
  lane. Deployment plan Unit 2 step 6 needs a human on a server with real
  clients.
- **Everything is `dod_anzio`.** No other KTP map has bot waypoints.
- **The stack is a reconstruction**, built from repo refs, and the daemon libs
  come from pinned upstream rather than production — every run records this in
  `daemon/PROVENANCE` as `RECONSTRUCTION`.
- **Steam auth, real network conditions, and the fleet's own configs** are not
  exercised. The lane runs `sv_lan 1` in a container.
