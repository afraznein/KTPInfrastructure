# Custom-Kernel Experiment Runbook

**Status:** Experiment A (preempt=full) ROLLED BACK 2026-05-05 (p99 regression). Experiment C (idle=poll) ACTIVE on ATL since 2026-05-10 — soak in progress, rollback path in §2/Experiment C.
**Target TODO:** `Custom-kernel research — can we beat 6.8.0-110-lowlatency?`
**Last updated:** 2026-05-10

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

#### Experiment D: `nohz=off` — **SKIP unless new evidence surfaces**

Disables the tickless kernel. Would cause isolated CPUs to receive periodic scheduling-clock interrupts again. Counter-productive given `nohz_full` is already reducing tick rate on isolated cores. Only worth trying if we start seeing evidence that missing periodic ticks cause deterministic issues — no such evidence today.

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
