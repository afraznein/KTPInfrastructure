# Proposed CVAR Changes for 1000 Tick Linux Servers

**Date:** February 6, 2026
**Context:** KTP servers moved from Windows (~500 actual FPS due to timer resolution) to Linux (true 1000 FPS). Several client cvars were tuned for the old tick rate and need updating.

**Reference:** See `docs/NETCODE_RESEARCH.md` for full engine source analysis.

---

## Priority 1: Fix Quick Reference (Actively Bad Advice)

The "Quick Reference" copy/paste block in `KTP Cvar List.md` currently recommends:

```
cl_updaterate 101
cl_cmdrate 101
rate 100000
ex_interp 0
fps_max 100
```

**Problems:**

| Setting | Current Recommendation | Issue | Proposed |
|---------|----------------------|-------|----------|
| `cl_cmdrate` | 101 | Most players run fps_max 240. At cmdrate 101, they're discarding ~140 movement commands/sec. Each discarded command is lost input granularity for hit registration. | `240` |
| `fps_max` | 100 | Players with 144/240Hz monitors should match their refresh rate. Recommending 100 is counterproductive. | `240` |
| `rate` | 100000 | This is the enforced *minimum*. With higher cmdrate and updaterate, players need more bandwidth headroom. | `1000000` |

**Proposed Quick Reference:**
```
cl_updaterate 120
cl_cmdrate 240
rate 1000000
ex_interp 0
fps_max 240
```

---

## Priority 2: cl_fixtimerate (Clock Drift Correction)

**Current:** Fixed at `7.5` (enforced, no range)

### What It Does

`cl_fixtimerate` controls how aggressively the client corrects its clock to match server timestamps. The client doesn't blindly accept the server clock — it uses it as a target and gradually corrects toward it by `cl_fixtimerate` milliseconds per client frame.

From Valve: *"cl_fixtimerate is the # of msec per frame of 'clock drift' fixup. Since the server is sending timestamps in every packet, but we only read networking once per frame, we don't want to just 'accept' the server clock, so we use it as a target and 'correct' toward it."*

### The Formula

Valve's recommended value: **`fps_max / 10`**

| fps_max | Recommended cl_fixtimerate | Currently Enforced | Correction Speed |
|---------|---------------------------|-------------------|-----------------|
| 75 | 7.5 | 7.5 | Correct |
| 100 | 10 | 7.5 | 75% of optimal |
| 144 | 14.4 | 7.5 | 52% of optimal |
| 240 | 24 | 7.5 | 31% of optimal |
| 500 | 50 | 7.5 | 15% of optimal |

A player running 240fps with cl_fixtimerate 7.5 is correcting clock drift at **less than 1/3 of the recommended rate**. Their client takes 3x longer to re-sync with the server after any drift event.

### Why This Matters More at 1000 Tick

On Windows (~500 actual server FPS), drift between client and server clocks was smaller because the server was closer to client frame rates. On Linux at true 1000 FPS, the server clock advances with higher granularity, creating more potential for drift that the client needs to correct. Slow correction = weapon prediction errors, "skipping," and inconsistent hit registration.

### Proposed Change

Change from fixed value to range-based: **`6` - `50`** (matching fps_max 60-500 / 10)

Players would set `cl_fixtimerate` to match their `fps_max / 10`:
- fps_max 100 -> cl_fixtimerate 10
- fps_max 144 -> cl_fixtimerate 14.4
- fps_max 240 -> cl_fixtimerate 24

### Code Change Required

In `KTPCvarChecker/ktp_cvar.sma`:
- Move `cl_fixtimerate` from fixed cvars (index 4) to range-based cvars (index 51+)
- Set min value `6` (fps_max 60 / 10), max value `50` (fps_max 500 / 10)
- Update Quick Reference with recommended value

### Risk

Low. This is purely client-side clock correction speed. Too-fast correction is harmless (slightly more aggressive sync). Too-slow correction (current state for 240fps players) causes the actual problems we're seeing.

---

## Priority 3: cl_updaterate Ceiling

**Current:** Range `100` - `120`, server config `sv_maxupdaterate 120`

### The Issue

At 1000 tick, the server can send updates far more frequently than 120/sec. Higher updaterate means:
- More frequent world state snapshots sent to client
- Client prediction has more reference points, reducing prediction errors
- Smoother entity movement and more accurate interpolation

### Tradeoff: Bandwidth

Each update packet is ~500-800 bytes in DoD. Bandwidth impact per 12-player server:

| updaterate | Per Player Outbound | 12 Players Total |
|-----------|-------------------|-----------------|
| 120 Hz | 60-96 KB/s | 720 KB - 1.15 MB/s |
| 200 Hz | 100-160 KB/s | 1.2 - 1.9 MB/s |
| 240 Hz | 120-192 KB/s | 1.44 - 2.3 MB/s |

All KTP servers are on dedicated hardware with 1 Gbps connections, so bandwidth is not a constraint.

### HLTV Note

The HLTV proxy has a separate hardcoded cap: `MAX_PROXY_UPDATERATE = 100` in `Proxy.h`. Raising game server updaterate does NOT affect HLTV — HLTV stays at 100 Hz max regardless. No HLTV recompile needed.

### Proposed Change

- Raise `sv_maxupdaterate` in `dodserver.cfg` from `120` to `240`
- Update KTPCvarChecker range from `100-120` to `100-240`
- Update Quick Reference to recommend `240`

### Risk

Medium. More bandwidth usage, but servers can handle it. Should test with a full 12-player server first to verify no issues. Can always lower back.

---

## Priority 4: cl_smoothtime

**Current:** Range `0` - `0.1`

### What It Does

Controls how long the client smooths view position after a prediction error. When the server corrects the client's predicted position, `cl_smoothtime` determines how gradually that correction is applied visually.

### 1000 Tick Consideration

At 1000 tick, prediction mismatches between client (240fps) and server (1000fps) may be different than at ~500fps Windows. The server resolves physics at 2x the rate it was running on Windows, so prediction corrections could be more frequent or different in magnitude.

### Proposed Change

No change for now. The current range of 0-0.1 should be sufficient. Worth monitoring — if players report jerky corrections, consider widening the range or adjusting the default.

---

## No Change Needed

| Cvar | Current | Why It's Fine |
|------|---------|---------------|
| `cl_lc` | Fixed `1` | Must stay 1. Lag compensation math now runs against 1000 tick server state, which is actually an improvement — more precise hit detection. |
| `cl_lw` | Fixed `1` | Must stay 1. Client-side weapon prediction. Disabling also disables lag compensation. |
| `ex_interp` | Range `0` - `0.03` | Setting 0 = auto (1/updaterate). The 0.05f buffer is hardcoded engine-side in HLTV proxy code, not affected by this cvar. |
| `r_bmodelinterp` | Fixed `1` | Stays 1. More important at higher tick for smooth brush model interpolation. |
| `rate` | Range `100000` - `1000000` | Range is fine. Just need to update the Quick Reference recommendation from minimum to maximum. |

---

## Summary of All Changes

| Item | Current | Proposed | Type |
|------|---------|----------|------|
| Quick Reference cl_cmdrate | 101 | 240 | Documentation |
| Quick Reference fps_max | 100 | 240 | Documentation |
| Quick Reference rate | 100000 | 1000000 | Documentation |
| Quick Reference cl_updaterate | 101 | 120 (or 240 if ceiling raised) | Documentation |
| `cl_fixtimerate` | Fixed `7.5` | Range `6` - `50` | Code + Documentation |
| `cl_updaterate` ceiling | 120 | 240 | Code + Server Config |
| `sv_maxupdaterate` | 120 | 240 | Server Config |

---

## Testing Plan

1. **cl_fixtimerate** — Have a few players test with `cl_fixtimerate` set to their `fps_max / 10` and report if weapon skipping improves. This can be tested immediately without any code changes by having players manually set the cvar.
2. **updaterate** — Change `sv_maxupdaterate` on one test server, have players connect with `cl_updaterate 240`, monitor bandwidth and gameplay feel.
3. **Quick Reference** — Update documentation after testing confirms changes.

---

*This document proposes changes only. No code or server config modifications have been made.*
