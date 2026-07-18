# Proposed CVAR Changes for 1000 Tick Linux

Now that we're on Linux running true 1000 tick (vs ~500 actual FPS on Windows due to timer resolution), several client cvars need updating. Here's what I'm proposing.

## 1. cl_fixtimerate — Most Likely Cause of Weapon Skipping

**Current:** Fixed at `7.5`
**Proposed:** Range `6` - `50`

This cvar controls how fast the client corrects its clock to match the server. The client doesn't blindly accept the server timestamp — it uses it as a target and gradually corrects toward it by `cl_fixtimerate` milliseconds per frame.

**Valve's recommended formula: `fps_max / 10`**

```
fps_max 75  → cl_fixtimerate 7.5  → currently correct
fps_max 100 → cl_fixtimerate 10   → currently 25% too slow
fps_max 144 → cl_fixtimerate 14.4 → currently 48% too slow
fps_max 240 → cl_fixtimerate 24   → currently 69% too slow
fps_max 500 → cl_fixtimerate 50   → currently 85% too slow
```

A player running 240fps with cl_fixtimerate 7.5 is correcting clock drift at **less than 1/3 of the recommended rate**. Their client takes 3x longer to re-sync with the server after any drift event.

This matters more at 1000 tick because the server clock advances with higher granularity than before, creating more opportunity for drift. Slow correction = weapon prediction errors, "skipping," inconsistent hit reg.

**Proposed:** Make it a range cvar (`6`-`50`) so players set it to their fps_max / 10. Low risk — too-fast correction is harmless, too-slow correction (current state) causes the problems.

**Players can test this RIGHT NOW** by manually typing `cl_fixtimerate 24` (or their fps_max / 10) in console and seeing if weapon behavior improves.

## 2. Quick Reference — Actively Bad Advice

The copy/paste block in the cvar list recommends:
```
cl_updaterate 101
cl_cmdrate 101
rate 100000
ex_interp 0
fps_max 100
```

**Problems:**
- **cl_cmdrate 101** — Most players run fps_max 240. At cmdrate 101, they're discarding ~140 movement commands/sec. Each discarded command is lost input granularity for hit registration. Should be `240`.
- **fps_max 100** — Players with 144/240Hz monitors should match their refresh rate. Recommending 100 is counterproductive. Should be `240`.
- **rate 100000** — This is the enforced *minimum*. With higher cmdrate and updaterate, players need more bandwidth headroom. Should be `1000000`.

**Proposed Quick Reference:**
```
cl_updaterate 120
cl_cmdrate 240
rate 1000000
ex_interp 0
fps_max 240
```

## 3. cl_updaterate Ceiling — Conservative for 1000 Tick

**Current:** Range `100` - `120`, server config `sv_maxupdaterate 120`
**Proposed:** Range `100` - `240`, server config `sv_maxupdaterate 240`

At 1000 tick, the server can send updates far more frequently than 120/sec. Higher updaterate means more frequent world state snapshots, better client prediction, smoother entity movement.

**Bandwidth impact per 12-player server:**
```
120 Hz → 720 KB - 1.15 MB/s outbound
200 Hz → 1.2 - 1.9 MB/s outbound
240 Hz → 1.44 - 2.3 MB/s outbound
```

All KTP servers are on dedicated hardware with 1 Gbps connections — bandwidth is not a constraint.

**HLTV is unaffected** — HLTV proxy has its own hardcoded cap at 100 Hz. Raising game server updaterate doesn't touch HLTV.

## 4. cl_smoothtime — No Change (Monitor)

**Current:** Range `0` - `0.1`

Controls how long the client smooths view position after a prediction error. At 1000 tick, prediction mismatches between client and server may behave differently. No change proposed for now, but worth monitoring.

## No Change Needed

- **cl_lc / cl_lw** — Must stay 1. Lag compensation now runs against 1000 tick state, which is an improvement.
- **ex_interp** — 0 = auto, fine as-is. The 0.05s buffer is hardcoded engine-side.
- **r_bmodelinterp** — Stays 1. More important at higher tick.
- **rate range** — 100k-1M is fine, just updating the recommendation.

## Testing Plan

1. **cl_fixtimerate** — Have players test with `cl_fixtimerate <fps_max/10>` and report if weapon skipping improves. No code changes needed to test.
2. **updaterate** — Change `sv_maxupdaterate` on one server, have players connect with `cl_updaterate 240`, monitor bandwidth and feel.
3. **Quick Reference** — Update docs after testing confirms.

No code or config changes have been made yet. This is a proposal.
