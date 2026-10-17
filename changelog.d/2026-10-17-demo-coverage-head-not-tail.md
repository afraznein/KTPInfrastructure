### `scripts`: the demos were never losing their tails — `demo_coverage.py` was measuring its own anchor (2026-10-17)

`demo_coverage.py` reported a ~45-49 s loss on every official half, and the whole of it was the
script's hardcoded `DEMO_T0_GAME_TIME = 3.0`. A demo written through the play-out path does not
start at game_time 3: the proxy broadcasts behind live, so the first frame written carries
whatever the delay buffer was holding, and that puts the demo's t=0 **tens of seconds into the
level**. The constant charged that head offset to the tail. `loss`, `covers_to`, the constant and
`--max-loss` are gone.

**The tails are complete, measured without the game clock at all.** `tail_s =
(close mtime − the `YYMMDDHHMM` stamp in the demo's own name) − playback length`, which lands in
[0,60) for a complete tail and [60,120) for a 60 s tail freed at the level change. The stamp
resolves to a minute, so it is a band and not a figure. Over the last 45 days: **105 of 105
official halves in [0,60), median 33.0, none at or above 60** — an independent reproduction of the
whole-corpus pass in `afraznein/KTPAMXX`#160 (2,292 of 2,294 back to April). It shares no term
with the engine clock, which is exactly what makes it evidence for the next paragraph.

**`t0` is now derived per half rather than assumed**: `half_end − playback length`, printed only
where the tail check vouches for the tail. There is no right constant to have used instead. Over
48 halves with an engine clock, 38 came back in [50,60) — but **four sit at ~0** (a proxy that
reconnected at the changelevel and had nothing to drain, so the demo covers the whole level) and
four between 20 and 40 (a partial drain). `t0` is the buffer depth at `record` time, and it
varies by ~52 s between those regimes. The old column's *negative* losses, impossible for a lost
tail, were the ~0 cases.

**What is actually un-recorded is the head, and `--max-head-gap` is the gate for it.**
`head_margin = live_at − t0` is how much demo sits in front of the moment play went live: min
**55.2 s**, median 358.9 s over 46 halves, and **none at or below zero**, because warmup is long.
A half going live within `t0` of a map change would begin un-recorded with nothing anywhere
saying so. That is the exposure the old gate could not express, because it was scoring the head
as a loss.

Two deliberate refusals rather than numbers:

- **Every half out of the tail band at once exits 2 and says so.** The stamp carries no timezone;
  at the wrong offset all of them move together, so this is what a wrong `--demo-tz` looks like
  and not a fleet of lost tails. A real tail loss is a minority of halves. `--demo-tz` defaults to
  `America/New_York` and DST is resolved per date, so a January demo and a July one both decode.
- **A remote demo with no `Last-Modified` reports its tail `unknown`, and `t0` is withheld with
  it.** Vouching for a tail on no evidence is how the previous version read plausible for weeks.

A negative `t0` is reported rather than clamped: it means `playback length` exceeds the engine
half end, which is the pause/overtime shape the 1200 s model never described. Two of the 48 are
that, at −143.9 and −64.4, both with a very late go-live.

Also: `nDirectoryOffset = 0` is a recording killed mid-match (3 of 2,297 in the corpus) and is
where the real tail losses are, and a local path passed to `--demos` as a string now splits
correctly on Windows instead of reading as an unrecognised demo name.
