# Ubuntu 22.04 vs 24.04 Game Server Optimization Research

**Date:** February 2026
**Target:** KTP DoD Game Servers (GoldSrc/HLDS)

---

## Executive Summary

Ubuntu 24.04 (kernel 6.8) provides several advantages over 22.04 (kernel 5.15):
- **EEVDF scheduler** replaces CFS - better latency characteristics
- **Newer network stack** with improved UDP handling
- **Better hardware support** for modern CPUs

However, we're missing several optimizations on our current deployment.

---

## Current Atlanta Baremetal Status (74.91.121.9)

| Setting | Current | Optimal | Status |
|---------|---------|---------|--------|
| Kernel | 6.8.0-90-lowlatency | 6.8.0-lowlatency | OK |
| Scheduler | EEVDF | EEVDF | OK |
| Timer (HZ) | 1000 | 1000 | OK |
| UDP Buffers | 25MB | 25MB | OK |
| CPU Governor | **schedutil** | **performance** | NEEDS FIX |
| C-States | **C1/C1E enabled** | **Disabled** | NEEDS FIX |
| Mitigations | Enabled | Consider disabling | OPTIONAL |
| CPU Isolation | None | Consider isolcpus | OPTIONAL |
| NIC Coalescing | Default | Minimize for latency | CHECK |

---

## 1. Scheduler Comparison

### Ubuntu 22.04: CFS (Completely Fair Scheduler)
- Classic Linux scheduler since 2007
- Uses "red-black tree" for task ordering
- Many ad-hoc tuning parameters accumulated over time
- Can have latency spikes under load

### Ubuntu 24.04: EEVDF (Earliest Eligible Virtual Deadline First)
- Replaced CFS in kernel 6.6+
- Algorithmic approach to fairness
- Lower worst-case latency
- Better behavior under heavy load
- "Working extremely good under heavy load" per user reports

**Verdict:** EEVDF is an improvement. No action needed - already using it.

### Future: sched_ext (Kernel 6.12+)
Meta and Valve are using **SCX-LAVD** (Latency-criticality Aware Virtual Deadline) for:
- Steam Deck gaming (frame timing)
- Meta's data center latency-sensitive workloads

**Not available on Ubuntu 24.04** (requires kernel 6.12+). Worth monitoring for future Ubuntu releases.

**Sources:**
- [Linux Kernel EEVDF Documentation](https://docs.kernel.org/scheduler/sched-eevdf.html)
- [sched-ext GitHub](https://github.com/sched-ext/scx)
- [Meta Using Steam Deck Scheduler](https://www.phoronix.com/news/Meta-SCX-LAVD-Steam-Deck-Server)

---

## 2. Kernel Choice: Lowlatency vs PREEMPT_RT

### Lowlatency Kernel (Current)
- Full preemption (PREEMPT)
- HZ_1000 (4x generic kernel's HZ_250)
- Good for latency requirements in milliseconds
- Lower overhead than full RT

### PREEMPT_RT Kernel
- Hard real-time guarantees
- ~100μs worst-case latency
- **Higher CPU overhead**
- **Can reduce throughput under load**
- Designed for industrial control, professional audio

**Verdict:** Lowlatency kernel is correct choice for game servers. RT kernel would hurt throughput.

**Source:** [Ubuntu Low Latency Blog](https://ubuntu.com/blog/industrial-embedded-systems-iii)

---

## 3. Immediate Fixes Needed

### 3.1 CPU Governor: schedutil → performance

**Current:** `schedutil` (dynamic frequency scaling)
**Problem:** Adds latency when ramping CPU frequency
**Fix:** Lock to `performance` governor

```bash
# Immediate fix
for gov in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    echo performance > "$gov"
done

# Verify
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
```

**Persistent fix:** Already in `/etc/rc.local` but not taking effect. Need to verify rc.local is running.

### 3.2 C-States: Enable Deeper Disable

**Current:** Only disabling C3/C4, but C1E still enabled
**Problem:** C1E transition adds ~10μs latency
**Fix:** Disable all C-states except C0

```bash
# Add to GRUB for full disable
GRUB_CMDLINE_LINUX_DEFAULT="... processor.max_cstate=0 intel_idle.max_cstate=0"

# Or via sysfs for C1E
echo 1 > /sys/devices/system/cpu/cpu*/cpuidle/state2/disable
```

---

## 4. Optional Optimizations (Security/Performance Tradeoffs)

### 4.1 Disable CPU Mitigations

**Current:** Full Spectre/Meltdown mitigations enabled
**Performance impact:** 5-30% depending on workload (context switches hit hardest)

```bash
# Add to GRUB
GRUB_CMDLINE_LINUX_DEFAULT="... mitigations=off"
```

**Security risk:** Only safe if:
- No untrusted code runs on server
- Server is not multi-tenant
- No web browsers or user-facing services

**For dedicated game servers:** Relatively low risk - only trusted game server code runs.

**Source:** [Ubuntu Spectre/Meltdown Wiki](https://wiki.ubuntu.com/SecurityTeam/KnowledgeBase/SpectreAndMeltdown/MitigationControls)

### 4.2 CPU Isolation (isolcpus)

**Concept:** Reserve specific CPU cores exclusively for game servers

```bash
# Reserve cores 2-7 for game servers (example for 8-core system)
GRUB_CMDLINE_LINUX_DEFAULT="... isolcpus=2-7 nohz_full=2-7 rcu_nocbs=2-7"

# Then pin game servers to isolated cores
taskset -c 2 ./hlds_linux ...
taskset -c 3 ./hlds_linux ...
```

**Benefits:**
- No kernel tasks interrupt game server
- No scheduler migration overhead
- Consistent cache behavior

**Drawbacks:**
- Requires careful planning
- Harder to manage
- May not help with our 5-server setup

**Verdict:** Worth testing but complex to implement correctly.

**Source:** [CPU Isolation Guide](https://manuel.bernhardt.io/posts/2023-11-16-core-pinning/)

### 4.3 NIC Interrupt Coalescing

**Concept:** Reduce interrupt batching for lower latency

```bash
# Check current settings
ethtool -c eth0

# Minimize coalescing for latency
ethtool -C eth0 adaptive-rx off rx-usecs 0 rx-frames 1
```

**Tradeoff:** More interrupts = lower latency but higher CPU usage

**Source:** [Linux Network Performance Guide](https://ntk148v.github.io/posts/linux-network-performance-ultimate-guide/)

---

## 5. Additional sysctls for Game Servers

Already configured in provision script, but verify:

```bash
# Performance sysctls
kernel.nmi_watchdog = 0              # Disable NMI watchdog
net.ipv4.tcp_low_latency = 1         # Prefer latency over throughput
net.core.busy_read = 50              # Busy polling for sockets
net.core.busy_poll = 50              # Busy polling for sockets

# UDP buffers (already set)
net.core.rmem_max = 26214400
net.core.wmem_max = 26214400

# Optional additions
net.core.netdev_max_backlog = 5000   # Increase packet queue
net.core.somaxconn = 4096            # Increase connection backlog
vm.swappiness = 10                   # Reduce swap usage
```

---

## 6. Recommended Action Plan

### Phase 1: Immediate Fixes (Low Risk)
1. Fix CPU governor to `performance`
2. Verify C-state disabling is working
3. Verify rc.local is executing at boot

### Phase 2: Testing (Medium Risk)
4. Test `mitigations=off` on one server
5. Benchmark NIC coalescing settings
6. Test busypoll sysctl settings

### Phase 3: Advanced (Higher Complexity)
7. Consider CPU isolation for heavily loaded servers
8. Monitor kernel 6.12+ for sched_ext availability
9. Consider custom kernel with additional patches

---

## 7. Monitoring Commands

```bash
# Check CPU governor
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor | sort | uniq -c

# Check C-state usage
cat /sys/devices/system/cpu/cpu0/cpuidle/state*/usage

# Check for UDP errors
cat /proc/net/snmp | grep Udp | tail -1 | awk '{print "RcvbufErrors:", $6}'

# Check interrupt distribution
cat /proc/interrupts | grep eth

# Check scheduling latency (requires kernel tracing)
perf sched latency

# Check for soft lockups
dmesg | grep -i "soft lockup\|rcu\|stall"
```

---

## 8. References

- [EEVDF Scheduler - Linux Kernel Docs](https://docs.kernel.org/scheduler/sched-eevdf.html)
- [sched_ext GitHub](https://github.com/sched-ext/scx)
- [Meta SCX-LAVD Deployment](https://www.phoronix.com/news/Meta-SCX-LAVD-Steam-Deck-Server)
- [Ubuntu Low Latency Kernels](https://ubuntu.com/blog/industrial-embedded-systems-iii)
- [Ubuntu Spectre/Meltdown Controls](https://wiki.ubuntu.com/SecurityTeam/KnowledgeBase/SpectreAndMeltdown/MitigationControls)
- [Linux Network Performance Guide](https://ntk148v.github.io/posts/linux-network-performance-ultimate-guide/)
- [CPU Isolation Guide](https://manuel.bernhardt.io/posts/2023-11-16-core-pinning/)
- [Red Hat Network Tuning](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/monitoring_and_managing_system_status_and_performance/tuning-the-network-performance_monitoring-and-managing-system-status-and-performance)
