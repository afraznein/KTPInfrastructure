### `scripts`: `demo_coverage.py` — a tail test that can fail, a `t0` with no anchor, and a gate that cannot skip (2026-10-18)

⚠️ **This supersedes the second half of `2026-10-17-demo-coverage-head-not-tail.md`, which is in the
same unreleased batch.** That entry's headline stands — the demos were never losing their tails — but
the two instruments it shipped as the replacement are both retired here, for reasons measured since.
`afraznein/KTPInfrastructure`#720.

**The wall-clock tail band could not fail.** It read
`tail_s = (close mtime − the stamp in the demo's name) − playback length` as a verdict. But playback
length is the directory's `fTrackTime`, which is wall time since the demo's first write, so the
expression reduces to `first_write − stamp` — the stamp's own minute rounding and nothing else. A
recording killed mid-half shortens `close` and `fTrackTime` by the same amount, so the one failure
the band claimed to detect could not move its value. Measured over the official archive, `tail_s`
ran 0.1 to 59.6 with a median of 33.0: it filled the band edge to edge, which is the rounding
distribution and not a measurement of a demo. The "105 of 105 in band" result the previous entry
cited as evidence was that rounding, reported as a pass.

**The tail test is now structural, and it has a positive case.** `nDirectoryOffset` is written by
`DemoFile::Close()`, so a recording killed before close has no directory at all — and those files
are the only genuine tail losses in the corpus. A sweep of 5,366 `.dem` across the archive and its
FastDL mirror finds exactly 5 such demos (DEN4 08-21 h1, NY1 08-31 h1, NY1 10-08 h2, and DEN3 and
DEN1 in `S9-ARCHIVE/` from 2026-03-01), with 0 unparseable. `tail_verdict` reads that field, a
truncated demo is a row and a finding rather than a skipped line on stderr, and the run exits 1.
A new `DemoTruncatedError` keeps "a demo that lost its tail" separate from "not a demo" — collapsing
those two is why the positive set was invisible. 🔑 **3 of the 5 are `12man`, and `--types` defaults
to `ktp`**, so the retired band was never exercised against a positive case even in principle.

**`t0` is fitted from two clocks instead of anchored on the half end.** The previous derivation,
`half_end − playback length`, is biased LOW: the demo stops at the `changelevel`, not at the engine
half end, and the gap between them is not zero. The event tables carry `event_epoch` beside
`game_time`, so the wall-to-game offset is recoverable from the half's own rows:

    t0 = (closed_at − playback length) − epoch_offset − broadcast_delay

Validated against demo CONTENT — every `DeathMsg` matched to `hlstats_Events_Frags` on killer and
victim SteamID, which shares no term with either derivation. On the ground-truth halves the retired
derivation reads **−9.28 to −10.30 s** against the content fit; the new one reads the content fit to
**±0.45 s** once the delay is accounted. On the same 96 official halves the retired derivation
overstated `head_margin` by a median of **+10.1 s**, always in the optimistic direction, and the
closest any half has come to starting un-recorded is **30.1 s, not the 55.2 s** the old column
reported.

`epoch_offset` is fitted in a window at the START of the half, because a tech pause freezes game time
while the wall clock runs and steps the offset up mid-half. `event_epoch` is whole seconds against a
sub-second `game_time`, so the offset approaches its value from below and the MAX is the estimator;
the range inside the window is the control, and above `MAX_EPOCH_FIT_SPREAD` the fit is refused
rather than averaged across the step. ✅ **This does not cost coverage: of 9 official halves the new
instrument withholds, 7 have no go-live row and neither instrument could judge them. The only 2 it
newly refuses are pause halves where the retired derivation returned a confidently wrong answer.**

**`--broadcast-delay` is a named parameter, not a buried constant**, and it is the proxy's configured
`delay` rather than a residual fitted to make `t0` come out. The mechanism predicts `t0` itself lands
near it, so the run prints that comparison as a self-check: on the official archive `t0` median
**62.4 s against a delay of 60.0 s**. Independently, the HUD observer measures `broadcastLagMs` at
60.0–61.0 s on all 24 — two unrelated instruments on the same value. A wrong delay shows up in that
line instead of silently shifting every margin.

**The gate can no longer skip what it cannot judge.** `--max-head-gap` now fails on a half with no
computable `head_margin` and names the missing term, with `--allow-unmeasured` as the deliberate
opt-out. An unjudged half reading as a pass is the same defect class as the band above, and it is how
the band stayed invisible. `--max-loss` remains gone; `--demo-tz` goes with the stamp, which nothing
needs now. ⚠️ Nothing installed calls this script (0 scheduled callers, 0 uses of `--max-loss` across
`/etc/cron.d`, `/etc/systemd/system`, `/usr/local/bin`, `/opt/ktp-infra` and `/opt/ktp-reports`), so
the CLI changes break no caller.

A NEGATIVE `t0` now means the recording began before the level loaded, which covers the half
outright; it is reported rather than clamped.
