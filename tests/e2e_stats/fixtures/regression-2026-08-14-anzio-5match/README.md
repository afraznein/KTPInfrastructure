# dod_anzio, 5-match combined positional baseline

Five real 16-bot Lane B matches on `dod_anzio`, run **simultaneously** as five
isolated containers (`ktp-lane-b:dev`, each with its own ephemeral MySQL +
`hlds` instance, no shared state between them) to build out the first
multi-match positional/"holding" baseline, per the operator's original framing
in this work: "we would need a process for having a baseline for this on each
map, possible over time once we start collecting positional stats." This is
five matches of that process running at once, not one.

KTPAMXX build: `feat/stats-break-context` @ `34b28b72` (includes the
`ksc_flag_positions_task` fix from earlier today — without it every fixture
here would have zero `ktp_flag_positions` rows, same as every fixture before
today). KTPHLStatsX build: `feat/break-context-parse` @ `a0ae198`.

## A real staging bug, caught before it produced wrong numbers

The first pass at this (all 5 matches, replayed) came back **100% of samples
excluded** — every one of 10,982 position samples found zero known-enemy
flags. Root cause: the daemon tree staged into these 5 fresh containers came
from a host-side copy (`scratchpad/laneb-build/daemon/`) assembled *before*
`ktp_flag_captures`/`doEvent_KTPFlagCapture` existed — a stale artifact from
yesterday's `assemble_daemon_tree.sh` run, never refreshed after that feature
was validated directly inside the original single-match container (which got
`hlstats.pl` patched in place, not re-assembled). Confirmed via
`grep -c doEvent_KTPFlagCapture` on the staged copy: zero matches. Fixed by
re-copying `hlstats.pl`/`HLstats.plib`/`HLstats_EventHandlers.plib` from the
`KTPHLStatsX-isolated` clone (which has every commit) and re-running all 5
replays — same raw logs, no new matches needed, since `dod_capture_area`
lines were present in the original logs all along; only the replay's daemon
was wrong. Second pass: 0% excluded, real numbers below.

## Result

| match | kills | assists | cap_break | flag_captures |
|---|---|---|---|---|
| 1 | 150 | 13 | 4 | 36 |
| 2 | 119 | 14 | 3 | 28 |
| 3 | 197 | 26 | 8 | 41 |
| 4 | 123 | 13 | 0 | 40 |
| 5 | 211 | 20 | 2 | 60 |

Combined baseline (`scripts/positional_baseline.py`, all 5 fixtures as
arguments — it accumulates across fixtures by design):

```
=== overall: 10982 samples, 0 excluded (0%) ===

=== baseline: dod_anzio (n=10982) ===
  mean=1396  median=1178  min=0  max=3967  (map units)
```

Per-player advancement vs. baseline ranged from **+331 to -896** map units
across the accumulated set — bot names repeat across matches (`new_bot`
draws from a fixed roster), so a name's `n` and average are a genuine
cross-match accumulation for that identity, not five separate numbers. This
is real evidence the accumulation mechanism works as designed, not evidence
about any specific bot's "skill" — these are AI bots with match-to-match
randomized behavior, not persistent human players, so the leaderboard shape
here validates the *pipeline*, not a real player-holding ranking.

## Still one map, five matches — not yet a trustworthy per-flag baseline

The script's own `n<30` confidence gate never fires here (n=10,982 clears it
by two orders of magnitude), but that gate is about *raw sample count*, not
about *map coverage breadth*. Five matches is real accumulation, further
along than the single-match baseline from earlier today, but still only one
source of variance (bot AI on one map, one server config). The next
meaningful step is more matches over time and, eventually, other maps —
exactly the "possible over time" framing this whole feature was scoped
around from the start.
