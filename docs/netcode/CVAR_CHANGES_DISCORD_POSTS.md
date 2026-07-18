# MESSAGE 1 (1970 chars)

## Proposed CVAR Changes for 1000 Tick Linux

Now that we're on Linux running true 1000 tick (vs ~500 actual FPS on Windows due to timer resolution), several client cvars need updating.

### 1. cl_fixtimerate — Most Likely Cause of Weapon Skipping

**Current:** Fixed at `7.5`
**Proposed:** Range `6` - `50`

This controls how fast the client corrects its clock to match the server. The client doesn't blindly accept the server timestamp — it gradually corrects toward it by `cl_fixtimerate` milliseconds per frame.

**Valve's recommended formula: `fps_max / 10`**

```
fps_max 75  → fixtimerate 7.5  → currently correct
fps_max 100 → fixtimerate 10   → 25% too slow
fps_max 144 → fixtimerate 14.4 → 48% too slow
fps_max 240 → fixtimerate 24   → 69% too slow
fps_max 500 → fixtimerate 50   → 85% too slow
```

A player running 240fps with cl_fixtimerate 7.5 is correcting clock drift at **less than 1/3 the recommended rate**. Their client takes 3x longer to re-sync after any drift.

This matters more at 1000 tick because the server clock advances with higher granularity, creating more drift. Slow correction = weapon prediction errors, skipping, inconsistent hit reg.

**Proposed:** Range cvar `6`-`50` so players set it to their fps_max / 10.

**You can test this right now** — type `cl_fixtimerate 24` (or your fps_max / 10) in console and see if weapon behavior improves.

---

# MESSAGE 2 (1647 chars)

### 2. Quick Reference — Actively Bad Advice

The recommended copy/paste block currently says:
```
cl_updaterate 101
cl_cmdrate 101
rate 100000
ex_interp 0
fps_max 100
```

**Problems:**
- **cl_cmdrate 101** — Most players run fps_max 240. At cmdrate 101, you're discarding ~140 movement commands/sec. Each discarded command is lost input granularity for hit reg. Should be `240`.
- **fps_max 100** — If you have a 144/240Hz monitor you should match your refresh rate. Should be `240`.
- **rate 100000** — This is the enforced minimum. With higher cmdrate and updaterate, you need more bandwidth headroom. Should be `1000000`.

**Proposed Quick Reference:**
```
cl_updaterate 120
cl_cmdrate 240
rate 1000000
ex_interp 0
fps_max 240
cl_fixtimerate 24
```

(Adjust cl_fixtimerate and cl_cmdrate to match your fps_max. cl_fixtimerate = fps_max / 10, cl_cmdrate = fps_max.)

---

# MESSAGE 3 (1535 chars)

### 3. cl_updaterate Ceiling

**Current:** Range `100` - `120`, server config `sv_maxupdaterate 120`
**Proposed:** Range `100` - `240`, server config `sv_maxupdaterate 240`

At 1000 tick the server can send updates far more frequently than 120/sec. Higher updaterate = more frequent world state snapshots, better client prediction, smoother entity movement.

**Bandwidth impact per 12-player server:**
```
120 Hz → ~720 KB - 1.15 MB/s outbound
240 Hz → ~1.44 - 2.3 MB/s outbound
```

All KTP servers are on dedicated hardware with 1 Gbps — bandwidth is not a constraint. HLTV is unaffected (has its own hardcoded 100 Hz cap).

### 4. Everything Else

**No change needed:**
- `cl_lc` / `cl_lw` — Stay at 1. Lag comp now runs against 1000 tick state which is an improvement
- `ex_interp` — 0 = auto, fine as-is
- `cl_smoothtime` — Current range 0-0.1 is fine, worth monitoring
- `rate` range — 100k-1M is fine, just updating the recommendation

### Testing Plan

1. **cl_fixtimerate** — Players test with `cl_fixtimerate <fps_max/10>` and report if weapon skipping improves. No server changes needed.
2. **updaterate** — Change `sv_maxupdaterate` on one server, players try `cl_updaterate 240`, monitor feel.
3. **Quick Reference** — Update docs after testing.

No changes have been made. This is a proposal.
