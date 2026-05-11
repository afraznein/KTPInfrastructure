# Custom-Kernel Experiment Runbook

**Status:** Phase 3 closed-as-not-needed 2026-05-11. Phase 3a diagnostic (`nanosleep_bench.c` micro-benchmark) ran on ATL host pinned to CPU 6 with SCHED_FIFO 50: kernel sleeps with **~2µs precision at every requested interval from 100µs to 5ms** (no CONFIG_HZ rounding, p99 = p50 + 1µs). Falsifies the runbook's pre-Stage C hypothesis. The 1.435ms absgrid floor is **engine-side**, not kernel-side. Custom-kernel build was a hypothesis-driven gamble that would NOT have fixed the problem. New investigation track: instrument the absgrid loop in `KTPReHLDS/dedicated/src/sys_ded.cpp` to find the ~400µs/iteration overhead. Filed as separate research TODO.

Operational answer remains NY:27019's perpetual `-pingboost 4` (1009 fps @ 100% CPU) for any 999fps-critical instance until the engine-side absgrid investigation closes.

**Target TODO:** `Custom-kernel research — can we beat 6.8.0-110-lowlatency?`
**Last updated:** 2026-05-11

This runbook exists to make the Phase 2 kernel-cmdline experiments (and the Phase 3 custom-kernel build, if warranted) executable from a pre-planned script rather than improvised during a maintenance window.

---

## 1. Audit findings (2026-04-24, ATL:74.91.121.9)

### What's already active

```
Kernel:           6.8.0-110-lowlatency  (PREEMPT_DYNAMIC mode)
GRUB cmdline:     intel_idle.max_cstate=0
                  processor.max_cstate=0
                  mitigations=off
                  isolcpus=2,3,4,5,6,7
                  nohz_full=2,3,4,5,6,7
                  rcu_nocbs=2,3,4,5,6,7
CPU governor:     performance (all CPUs)
cpuidle:          Disabled per-CPU on isolated cores (echo 1 > cpuidle/state*/disable via rc.local)
Boot time:        1.7s kernel + 2m3s userspace = ~2m5s total — **expected outage window per reboot**
psycachy:         Cleanly purged from /boot (no residuals)
GRUB mode:        saved (requires `grub-set-default` after kernel update before reboot)
```

### What's NOT currently active (Phase 2 candidates)

```
idle=poll          — force idle task to busy-poll instead of HLT. Skip: equivalent cost to pingboost 4.
rcu_nocb_poll      — RCU callbacks via polling instead of kthreads. Try.
preempt=full       — force PREEMPT_DYNAMIC into full-preempt mode. Try — this is the highest-priority experiment.
nohz=off           — force periodic tick. Counter-intuitive. Skip unless we suspect nohz_full is causing jitter.
```

### Honest expected outcomes

The 977→999 fps gap is dominated by one specific kernel behavior: **`nanosleep` / `clock_nanosleep` rounds sub-ms sleeps up to the next HZ tick**, which is what broke our Stage C abs-time experiments (raised 977 fps baseline to 643 fps under ATL:27019 `-absgrid`, see CHANGES_SUMMARY_2026-05-08 Stage C entry). No cmdline flag fixes that; it's compile-time CONFIG_HZ and the specific nanosleep implementation in `kernel/time/`.

**So cmdline experiments will NOT close the fps gap to NFO's claimed window.** What they CAN do:
- Reduce p99 interframe jitter (current p99=5.16ms) — `preempt=full` most likely to help
- Reduce residual micro-jitter from RCU grace-period scheduling — `rcu_nocb_poll` might help
- Characterize which variables matter and which don't — useful data for Phase 3 design

If we want 999 fps at low CPU cost, the realistic path is Phase 3 (custom kernel with CONFIG_HZ_2000 and patched `hrtimer_nanosleep` that doesn't round). Phase 2 is primarily **due diligence** — rule out cheap wins before committing to a multi-week custom-kernel build.

---

## 2. Phase 2 experiment plan

### Test host selection

**ATL:27019 (ATL5)** — already the `-absgrid` research slot per 2026-04-23 canary topology (see `CHANGES_SUMMARY_2026-05-08.md` canary topology update). But kernel cmdline is **host-level**, not per-instance, so the entire Atlanta baremetal takes the hit — 27015 through 27019 all reboot together.

Alternative host: **Dallas**. Similar baremetal, identical setup, tightest σ in pre-JIT baseline (7.96). But pulling Dallas offline pulls 5 instances.

**Recommendation:** use **Atlanta** — we've already committed it to the research role, and the other 4 hosts continue serving as production control.

### Measurement methodology

- Pre-experiment baseline: 24h of `[KTP_PROFILE]` data from the target host. If this can piggy-back on the **post-JIT** snapshot planned for 2026-04-25 evening, use that as the control.
- During experiment: 48h of `[KTP_PROFILE]` data on the target host. Compare against the other 3 baremetals (Dallas / Denver / New York) during the same wall-clock window — they serve as same-day control, isolating the experiment from daily traffic variation.
- Key metrics to extract:
  - fleet-wide fps p50, p95, max, σ
  - interframe p50, p99, max
  - spike rates per phase (`read`, `steam`, `phys`, `send`)
  - Any new spike patterns that weren't present pre-experiment

Use the same script that produced `fleet_fps_2026-04-23_pre-jit.json` — per-host aggregation is already in it.

### Priority-ordered experiments

#### Experiment A: `preempt=full` (highest priority)

**Hypothesis:** PREEMPT_DYNAMIC defaults to voluntary preemption. Forcing full preempt reduces worst-case latency for SCHED_FIFO tasks (which our game servers are — priority 50) when the kernel is holding non-preemptible locks. Should tighten interframe p99.

**GRUB edit:** Add `preempt=full` to `GRUB_CMDLINE_LINUX_DEFAULT` in `/etc/default/grub`.

```bash
# On ATL host:
sudo cp /etc/default/grub /etc/default/grub.preempt-experiment-bak
sudo sed -i 's|^\(GRUB_CMDLINE_LINUX_DEFAULT="\)|\1preempt=full |' /etc/default/grub
# Verify the edit:
grep GRUB_CMDLINE_LINUX_DEFAULT /etc/default/grub
# Regenerate grub.cfg (Ubuntu way):
sudo update-grub
# Because GRUB_DEFAULT=saved, explicitly set the default menuentry to the lowlatency kernel:
sudo grub-set-default "Advanced options for Ubuntu>Ubuntu, with Linux 6.8.0-110-lowlatency"
# Verify:
sudo grub-editenv list
# Reboot:
sudo reboot
```

**Soak:** 48 hours. Pull `[KTP_PROFILE]` data, compare against the other 3 baremetals during the same window.

**Success criteria:** p99 interframe shifts from ~5.16ms to ≤3ms on ATL, while control hosts hold steady. Any measurable fps p50 bump is a bonus.

**Rollback:** `sudo cp /etc/default/grub.preempt-experiment-bak /etc/default/grub && sudo update-grub && sudo reboot`. ~3min window.

#### Experiment B: `rcu_nocb_poll` (secondary)

**Hypothesis:** We already set `rcu_nocbs=2,3,4,5,6,7` which offloads RCU callback kthreads off the isolated cores. `rcu_nocb_poll` changes those kthreads from event-driven (woken by RCU grace period completion, which involves IPIs) to polling-based — eliminates IPI wakes on the housekeeping cores 0,1.

**GRUB edit:** Add `rcu_nocb_poll` to `GRUB_CMDLINE_LINUX_DEFAULT`.

Same mechanical steps as Experiment A.

**Soak:** 24 hours (lower expected impact).

**Success criteria:** No regression on the isolated-core game servers; slight reduction in housekeeping-core IPI rate (check via `/proc/interrupts` delta). This experiment is mostly about ruling out that RCU-callback overhead is contributing to residual jitter; if it makes no difference, that's useful negative data.

**Rollback:** Same pattern.

#### Experiment C: `idle=poll` (revised 2026-05-10 — was SKIP, now active)

**Original 2026-04-24 SKIP rationale (preserved):** would force idle task to busy-poll → CPU stays at 100% on isolated cores → ~same power/thermal cost as running pingboost 4 on every instance. NY:27019 already on pingboost 4 as the 999 fps canary; forcing the whole host into idle=poll just extends that pattern at higher aggregate CPU cost. Argued no additional data over pingboost 4.

**Why that was stale (Stage C evidence + cpuidle inspection):** Stage C's `-absgrid` test on ATL:27019 (2026-04-23) hit a 643 fps ceiling with `clock_nanosleep(TIMER_ABSTIME)` on isolated CPU + SCHED_FIFO + `PR_SET_TIMERSLACK=1`. Process at 2.8% CPU, sleep path active — kernel was waking the thread at ~500µs avg latency from hrtimer-fire. Inspection of ATL cpuidle state on 2026-05-10 confirmed POLL + C1 are disabled via rc.local (`disable=1` per state), but `intel_idle.max_cstate=0 + processor.max_cstate=0` only blocks the C-state drivers — the kernel falls back to `default_idle()` (HLT) when a core is idle. **idle=poll replaces HLT with `cpu_relax()`**, eliminating the HLT-exit + IRQ-deliver wakeup-latency floor. Different mechanism than pingboost 4 (which never sleeps in the first place).

**Hypothesis:** absgrid + idle=poll = 999 fps at the absgrid instance's existing ~3% CPU (clock_nanosleep wakes instantly into a polling core). Pingboost 4's 100% CPU cost is then a function of `Sleep_Never` busy-wait, not the idle-state floor — so absgrid + idle=poll could be a 3rd operational path between pingboost 2 (977 fps @ 1-3%) and pingboost 4 (999 fps @ 100%).

**GRUB edit:** Add `idle=poll` to `GRUB_CMDLINE_LINUX_DEFAULT` in `/etc/default/grub`.

```bash
# On ATL host (74.91.121.9):
TS=$(date +%Y%m%d-%H%M%S)
sudo cp /etc/default/grub /etc/default/grub.idle-poll-experiment-bak-${TS}
sudo sed -i 's|^\(GRUB_CMDLINE_LINUX_DEFAULT="\)|\1idle=poll |' /etc/default/grub
grep GRUB_CMDLINE_LINUX_DEFAULT /etc/default/grub
sudo update-grub
sudo grub-set-default "Advanced options for Ubuntu>Ubuntu, with Linux 6.8.0-110-lowlatency"
sudo grub-editenv list
sudo reboot
```

**Soak:** 24-48 hours. Pull `[KTP_PROFILE]` data from ATL:27015-27019 + compare against the other 3 baremetals during the same window.

**Success criteria (per-instance, NOT fleet-aggregate):**
- ATL:27019 (`-absgrid`): fps p50 ≥ 990 (vs current 643 ceiling under absgrid). This is the primary signal.
- ATL:27015-27018 (`-pingboost 2`): no regression in fps p50 / interframe p99 / spike rate vs control hosts. These instances aren't asking for sub-ms sleeps; idle=poll is overhead-without-benefit for them. Acceptable if neutral.
- p99 interframe on ATL:27019 tightens (currently dominated by the wakeup-latency floor).

**Cost expectations:** isolated cores 2-7 will report ~100% CPU utilization in `top` / `htop` because the idle task is now busy-polling instead of HLTing. This is cosmetic — the SCHED_FIFO game-server tasks still preempt the idle task as needed. Real "useful CPU" stays at the same ~3-5% per game-server core. Power/thermal: baremetal, ATL room, no concern in off-season.

**Rollback:** `sudo cp /etc/default/grub.idle-poll-experiment-bak-<TS> /etc/default/grub && sudo update-grub && sudo grub-set-default 'Advanced options for Ubuntu>Ubuntu, with Linux 6.8.0-110-lowlatency' && sudo reboot`. ~3 min window.

**Stop conditions during soak:**
- Any ATL instance shows >5% fps p50 regression vs control hosts in the same window
- Any ATL instance shows new spike pattern (`steam`/`phys`/`send` >2.5σ) absent from control hosts
- Player report of perceived perf change on ATL:27015-27018

**Outcomes that close TODOs:**
- ATL:27019 hits 990+ fps under absgrid: Stage C closes; absgrid+idle=poll documented as the 3rd 999fps path; consider rolling absgrid (NOT idle=poll) to wider canary on existing cmdline
- ATL:27019 stays at ~643 fps: rules out wakeup-latency-from-HLT as the bottleneck; the floor is somewhere else (timer interrupt rate, cache miss?), Stage C closes as won't-fix on existing CONFIG_HZ=1000
- ATL:27015-27018 regress: rollback + close idle=poll as not-host-safe; revisit per-CPU idle approaches if any exist

#### Experiment C results (2026-05-10) — FAILED, ROLLED BACK

**Test setup:** ATL host on `idle=poll` cmdline. ATL:27019 on `-pingboost 2 -absgrid` (clock_nanosleep TIMER_ABSTIME path). ATL:27015-27018 on plain `-pingboost 2` as same-host control. DAL/DEN/NY/CHI as cross-host control.

**Result @ 21:23-21:25 ET (post-restart steady state, 8 consecutive samples):**

| Configuration | avg interframe | implied fps | vs. hypothesis |
|---|---|---|---|
| ATL:27019 absgrid+idle=poll | 1.435 ms | 696 | hoped 999, got 696 |
| ATL:27015-27018 idle=poll only | 1.005 ms | 995 | identical to control hosts |
| ATL 4/23 absgrid (HLT idle) | ~1.555 ms | 643 | original Stage C ceiling |
| DAL/DEN/NY:27015-27018 (no idle=poll) | 1.005-1.008 ms | ~993-995 | control |
| NY:27019 -pingboost 4 (Sleep_Never) | 0.991 ms | 1009 | known 100% CPU canary |

**Interpretation:** absgrid+idle=poll only gained +53 fps over absgrid alone (643→696). Removing HLT-exit wakeup latency was insufficient. The remaining gap to 995/1009 fps confirms the runbook's pre-Stage C prediction (line 41): **`clock_nanosleep` rounds sub-ms sleeps up to the next CONFIG_HZ tick (1ms granularity), so absgrid wants to sleep ~1ms but actually sleeps ~1.4ms.** No cmdline flag can override this — it's compile-time kernel behavior in `kernel/time/hrtimer.c`.

**On pingboost-2 control instances (ATL:27015-27018), idle=poll showed ZERO measurable change** — same 1.005ms avg as DAL/DEN/NY baremetal controls. Sleep_Select returns near-immediately on quiet/empty servers; HLT-exit latency was never on the critical path for the default config.

**Rollback executed 2026-05-10 21:28 ET:**
1. Reverted `dodserver5.cfg` startparameters (removed `-absgrid`), restarted dodserver5 only (~30s outage on 27019).
2. Restored `/etc/default/grub` from `grub.idle-poll-experiment-bak-20260510-204044`, ran `update-grub > /tmp/log 2>&1` (NO `head` pipe — see memory `update_grub_sigpipe_pitfall.md`), pinned saved_entry to 110, rebooted host (~3-5 min full ATL outage). Total experiment downtime ~10 min across 3 reboots (one wasted on the SIGPIPE bug).

**Conclusion: Phase 2 is exhausted.** preempt=full (Experiment A) and idle=poll (Experiment C) both negative. rcu_nocb_poll (Experiment B) was lower-priority secondary; not worth running independently given the cmdline-floor evidence. The 977→999 fps gap at low CPU requires Phase 3 (custom kernel with CONFIG_HZ=2000+ + patched `hrtimer_nanosleep`). Multi-week build + monthly rebuild cost. **Recommended deferral:** accept NY:27019's `-pingboost 4` pattern as the operational answer for instances needing 999 fps; revisit Phase 3 only if a forcing function appears (e.g., a single-instance perf complaint that pingboost-4 can't address).

#### Experiment D: `nohz=off` — **SKIP unless new evidence surfaces**

Disables the tickless kernel. Would cause isolated CPUs to receive periodic scheduling-clock interrupts again. Counter-productive given `nohz_full` is already reducing tick rate on isolated cores. Only worth trying if we start seeing evidence that missing periodic ticks cause deterministic issues — no such evidence today.

---

## 2.5 Phase 3a diagnostic (2026-05-11) — CLOSED Phase 3 as not-needed

Before committing to the multi-week Phase 3 build, ran a direct measurement of `clock_nanosleep(TIMER_ABSTIME)` granularity on the actual ATL hardware. Source + raw results: `KTPInfrastructure/research/nanosleep-bench-2026-05-11/`.

**Tool:** `nanosleep_bench.c` (~145 LoC, BCL only). Sweeps requested sleep intervals 100µs / 200µs / 500µs / 800µs / 900µs / 999µs / 1000µs / 1100µs / 1500µs / 2000µs / 5000µs; 10000 iterations each + 100-iter warm-up. Reports min / p50 / p90 / p99 / max / mean of actual elapsed time. Optional `--rt` (SCHED_FIFO 50) + `--cpu N` (pin) flags.

**Run conditions:**
- Host: ATL baremetal (74.91.121.9), kernel 6.8.0-110-lowlatency
- Cmdline: standard isolcpus=2-7 / nohz_full / rcu_nocbs / max_cstate=0 / mitigations=off (matches production fleet)
- CPU 6: free isolated core (game servers on 2,3,4,5,7)
- 2 runs back-to-back: default (SCHED_OTHER) + `--rt --cpu 6` (matches absgrid runtime conditions)

**SCHED_FIFO 50 + pinned to CPU 6 results (the apples-to-apples match for absgrid):**

| Requested | Actual min | p50 | p99 | max | Overshoot |
|---|---|---|---|---|---|
| 100µs | 102µs | 102µs | 103µs | 105µs | +2µs |
| 500µs | 502µs | 502µs | 504µs | 505µs | +2µs |
| 999µs | 1001µs | 1002µs | 1003µs | 1005µs | +2µs |
| 1500µs | 1503µs | 1503µs | 1504µs | 1506µs | +3µs |
| 5000µs | 5003µs | 5004µs | 5007µs | 5010µs | +3µs |

`p99 = p50 + 1µs` across the entire range. `max = p50 + 3µs` worst case. **The kernel sleeps with high precision at sub-millisecond requests.** No CONFIG_HZ rounding observed. Pre-Stage C hypothesis falsified.

(Default SCHED_OTHER run shows the expected ~50µs scheduler-quantum overshoot + occasional 2-7ms jitter from preemption — confirms the SCHED_FIFO+pin path is the right baseline for production-style measurements. See `results.tsv` for the full table.)

**Implications:**

1. **Phase 3 custom kernel build is NOT needed.** ~2-3 weeks of build effort + monthly Ubuntu kernel-update rebuild commitment is avoided. We dodged a bullet.
2. The Stage C absgrid 1.435ms floor (Experiment C, 5/10) is **engine-side**, not kernel-side. The kernel can sleep at sub-ms granularity; the engine isn't taking advantage.
3. The runbook's pre-Stage C prediction (line 41 of original revision) was wrong. Documenting it here so future-me doesn't re-hypothesize the same thing.

**New investigation: engine-side absgrid loop overhead**

Initial source read of `KTPReHLDS/rehlds/rehlds/dedicated/src/sys_ded.cpp:155-235` shows the absgrid loop:

```c
if (g_use_abs_grid) {
    clock_gettime(CLOCK_MONOTONIC, &now);
    bool past_target = (now > grid_target);
    if (!past_target) {
        clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &grid_target, nullptr);
    }
    grid_target.tv_nsec += 1000000LL;  // advance 1ms regardless
}
// ... RunFrame + UpdateStatus + console-poll throttle ...
```

Loop math: sleep ~1.002ms + RunFrame ~16µs (per KTP_PROFILE empty-server data) + overhead ~3µs ≈ **~1.020ms per iteration → expected ~980 fps**. Measured under absgrid: 1.435ms / 696 fps. **Unaccounted ~415µs per iteration.**

Candidate sinks (pre-instrumentation hypotheses):
- `sys->UpdateStatus(FALSE)` — might involve a stat() / write() call I haven't traced
- `engineAPI->RunFrame()` — KTP_PROFILE may not measure all sub-phases (Steam packet handling, edict loop in extreme detail)
- The `clock_gettime` call at the top of each iteration — should be ~50ns but worth measuring
- `Sys_PrepareConsoleInput` — throttled to every 50ms but worth confirming

**Required next step: instrumented build of KTPReHLDS that logs per-iteration sleep + work + total times for ~10 seconds, then writes a histogram.** Cheap (~100 LoC patch) but needs a deploy-and-test cycle. Filed as a separate engine-side investigation TODO.

### Step 1 follow-up (2026-05-11 13:01-13:09 ET) — eliminates idle=poll as confound

Question: was idle=poll the actual cause of the 5/10 absgrid regression, not a Stage C bottleneck disambiguator? Cheap test: re-add `-absgrid` to ATL:27019's dodserver5.cfg, restart that one instance (~30s outage), measure on the stock kernel (idle=poll OFF since 5/10 21:28 rollback).

Result: **identical regression.** absgrid alone on stock kernel produces 686-691 fps / 1.43ms interframe — within 5 fps of the 5/10 measurement that had idle=poll active (696 fps / 1.435ms). idle=poll was NOT a confound.

| Configuration | interframe avg | fps | sample |
|---|---|---|---|
| Default pingboost-2 (control) | 1.005ms | 978-979 | ATL:27015,27018 same minute |
| **absgrid alone, stock kernel** | **1.426-1.438ms** | **685-691** | ATL:27019, 6 samples |
| absgrid + idle=poll (5/10) | 1.435ms | 696 | ATL:27019, 8 samples |
| Sleep_Never (`-pingboost 4`) reference | 0.991ms | 1009 | NY:27019, perpetual canary |

**Per-iteration time budget reconciliation** (steady-state, empty server):

| Component | Default pingboost-2 | absgrid (broken) | Δ |
|---|---|---|---|
| Sleep | ~989µs (Sleep_Select) | ~1002µs (clock_nanosleep, per diagnostic) | +13µs |
| RunFrame work (KTP_PROFILE `full`) | ~16µs | ~16µs | 0 |
| Block B + clock_gettime | ~3µs | ~3µs | 0 |
| **Loop period (math)** | **~1008µs** | **~1021µs** | +13µs |
| **Loop period (measured)** | **1005µs** | **1432µs** | **+427µs unaccounted** |

The math predicts absgrid should be ~13µs slower than default. Measurement says it's ~427µs slower. **The 414µs gap is engine-side and reproducible.** Sources to instrument:
- Inside `engineAPI->RunFrame()` outside SV_Frame_Internal (Host_Frame's wrapper work — Cmd_Buf_Execute, Sys_Frame, etc., not currently measured by KTP_PROFILE)
- The `prctl(PR_SET_TIMERSLACK, 1, ...)` call in `Sys_InitPingboost` may have a kernel-side side effect on subsequent timer interrupt handling — worth toggling to confirm
- Some interaction between `clock_nanosleep(TIMER_ABSTIME)` and the TSC-deadline timer subsystem that doesn't manifest in the standalone benchmark

**Phase 3a follow-up:** the kernel diagnostic was correct (kernel sleep is fine). The Step 1 follow-up confirms the bug is engine-side. Phase 3 stays closed-as-not-needed; the engine-side investigation moves to a clear "deploy instrumented build, collect, analyze" workstream.

---

## 3. Phase 3 custom-kernel notes (only if Phase 2 suggests it's warranted)

If Experiments A + B together show meaningful fleet improvement (say, p99 interframe tightens by 20%+ and `steam` spike rates drop), that's a signal that further kernel work is worthwhile. If they show no change, the remaining gap to NFO's 1000 fps window is in the `nanosleep` / CONFIG_HZ domain — Phase 3 is the only path.

### Build targets for a custom kernel

- Base: 6.8.0-110-lowlatency source (already running)
- CONFIG_HZ=2000 (currently 1000) — doubles timer resolution, halves nanosleep granularity
- CONFIG_PREEMPT_RT=y (if we didn't already get the benefit from `preempt=full` in Phase 2)
- Patch `hrtimer_nanosleep` to not round sub-HZ sleeps to the next HZ tick — this is the specific behavior that broke Stage C

### Build procedure (not executed; pre-planned only)

```bash
# Fetch Ubuntu lowlatency source
apt-get source linux-image-unsigned-6.8.0-110-lowlatency
cd linux-6.8.0/

# Copy running config as baseline
cp /boot/config-6.8.0-110-lowlatency .config

# Modify CONFIG_HZ
./scripts/config --set-val HZ 2000
./scripts/config --disable HZ_1000
./scripts/config --enable HZ_2000

# Confirm PREEMPT_DYNAMIC stays
./scripts/config --enable PREEMPT_DYNAMIC

# Apply oldconfig for new options
make olddefconfig

# Patch hrtimer_nanosleep rounding behavior
# (specific patch TBD — need to inspect kernel/time/hrtimer.c hrtimer_nanosleep_restart behavior)

# Build — ~30-60 min on modern Xeon
make -j$(nproc) deb-pkg LOCALVERSION=-ktp-1
```

### Risks / ongoing maintenance cost

- Must rebuild on every Ubuntu kernel security update (~monthly)
- One-off test on Atlanta first; if it holds for 2 weeks of matchday traffic, consider Dallas next
- Keep stock kernel installed as fallback — `grub-set-default` to flip back is ~3min

### Don't build if

- Phase 2 `preempt=full` + post-JIT baseline close the fps gap to within ±5 of NFO's window
- Phase 2 shows no interframe p99 improvement (suggests the jitter source is not kernel-latency-bound; probably the game DLL or network)

---

## 4. Decision gates

| Signal | Action |
|--------|--------|
| Post-JIT baseline (2026-04-25) shows fleet-wide p50 ≥ 990 fps, σ ≤ 8 | **De-escalate TODO to Low.** JIT closed the gap. No custom-kernel work needed. |
| Post-JIT baseline shows improvement but fleet still at ~980 fps | Proceed to Experiment A (preempt=full) |
| Post-JIT baseline shows no improvement | Interpret carefully — this TODO may not have a solvable signal. Pause kernel work, investigate what else dominates jitter. |
| Experiment A tightens p99 interframe meaningfully | Proceed to B. Then evaluate Phase 3. |
| Experiment A shows no change | Phase 3 (custom kernel) unlikely to help either. Close TODO as won't-fix. |

---

## 5. NFO FPS Locker context

NFO's marketing claim: "~1000 ±2 FPS on busy stock HLDS DoD servers at 1000Hz, 20-player test, 0.00% CPU, FPS 999.71-1003.00 across 7 consecutive `stats` samples" (posted 2025-06-14).

**What we've proven:**
- 999 fps at 1000Hz is reachable on our existing kernel via pingboost 4 / never-sleep (`Sleep_Never`), BUT at 100% CPU — so NFO's "0.00% CPU" is the specific thing that makes their kernel interesting.
- 0.00% CPU suggests they don't busy-poll. They must be achieving sub-ms sleep granularity while staying in HLT/C-states somehow.
- That's consistent with a custom timer/hrtimer patch in their kernel.

**What we DON'T know:**
- NFO's actual kernel source (proprietary).
- Whether their 0.00% CPU claim is measurement artifact (e.g., measuring after the tick has been reduced to idle-dominated).
- Whether the claim holds under actual matchday 20-player traffic vs a synthetic `stats` sampler.

This runbook doesn't try to replicate NFO. It tries to close the gap between our 977 fps baseline and NFO's claimed window using public-kernel knobs. If cmdline experiments close most of the gap, great. If they don't, we have a choice: build a custom kernel (multi-week, ongoing maintenance cost) or accept NY:27019's pingboost 4 pattern as the operational answer for 999-fps-critical instances.
