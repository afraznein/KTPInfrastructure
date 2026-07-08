#!/bin/bash
# KTP fleet drift-audit snapshot — runs on one host, writes a predictable
# markdown-ish snapshot of host + KTP state to stdout. The companion
# orchestrator (audit-fleet-drift.py) runs this on every fleet host in
# parallel and diffs the outputs.
#
# Format: section headers ("=== NAME ==="), then one fact per line.
# Keep lines stable — the orchestrator groups by (section, line) so any
# formatting change counts as drift.
#
# Keys expected to differ per host (IP, UUID, interface name, hostname,
# etc.) live in the orchestrator's IGNORE list. Don't try to normalize
# them here; the raw truth is more useful for debugging.
#
# KTP_SAMPLE_PORT (env, defaults to 27015) selects the dod-NNNNN instance
# used for per-port checks (binary md5, plugin md5). Orchestrator sets this
# per host so a canary occupying 27015 can be audited against a different
# non-canary port.

KTP_SAMPLE_PORT="${KTP_SAMPLE_PORT:-27015}"

echo "=== HOST ==="
echo "hostname: $(hostname)"
echo "kernel: $(uname -r)"
echo "cpu-model: $(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | xargs)"
echo "cpu-microcode: $(grep -m1 microcode /proc/cpuinfo | cut -d: -f2 | xargs)"
echo "cpu-cores: $(grep -c ^processor /proc/cpuinfo)"
echo "mem-total-kb: $(grep MemTotal /proc/meminfo | awk '{print $2}')"
echo "boot-time: $(who -b 2>/dev/null | awk '{print $3, $4}')"
echo "timezone: $(timedatectl show --property=Timezone --value 2>/dev/null)"
echo "rtc-in-local-tz: $(timedatectl show --property=LocalRTC --value 2>/dev/null)"

echo ""
echo "=== GRUB CMDLINE ==="
tr ' ' '\n' < /proc/cmdline | sort | grep -v '^$'

echo ""
echo "=== SYSCTL (KTP-relevant) ==="
# Keep this list a superset of provision/expected-sysctls.conf keys so the
# repo-vs-fleet comparison in audit-fleet-drift.py sees live values for every
# expected key (otherwise they'd all show up as false-positive "absent").
for k in \
  kernel.sched_rt_runtime_us \
  kernel.timer_migration \
  kernel.sched_autogroup_enabled \
  kernel.numa_balancing \
  kernel.nmi_watchdog \
  kernel.watchdog \
  kernel.core_pattern \
  vm.swappiness \
  vm.stat_interval \
  vm.dirty_ratio \
  vm.dirty_background_ratio \
  net.core.rmem_max \
  net.core.rmem_default \
  net.core.wmem_max \
  net.core.wmem_default \
  net.core.netdev_budget \
  net.core.netdev_budget_usecs \
  net.core.netdev_tstamp_prequeue \
  net.core.netdev_max_backlog \
  net.core.default_qdisc \
  net.core.somaxconn \
  net.core.busy_read \
  net.core.busy_poll \
  net.ipv4.tcp_congestion_control \
  net.ipv4.tcp_low_latency \
  net.ipv4.udp_rmem_min \
  net.ipv4.udp_wmem_min \
  net.netfilter.nf_conntrack_max \
  ; do
  v=$(sysctl -n "$k" 2>/dev/null)
  echo "$k = $v"
done

echo ""
echo "=== /etc/sysctl.conf (non-comment, sorted) ==="
grep -v '^#\|^$' /etc/sysctl.conf 2>/dev/null | tr -s ' ' | sed 's/ *= */ = /' | sort

echo ""
echo "=== /etc/rc.local (non-comment, sorted) ==="
grep -vE '^\s*#|^\s*$' /etc/rc.local 2>/dev/null | sort

echo ""
echo "=== CPU GOVERNOR (distinct values) ==="
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor 2>/dev/null | sort -u

echo ""
echo "=== CPU IDLE STATE DISABLES ==="
for c in /sys/devices/system/cpu/cpu*/cpuidle/state*/disable; do
  [ -f "$c" ] || continue
  val=$(cat "$c")
  if [ "$val" = "1" ]; then
    # Strip the per-cpu prefix to produce stable keys
    echo "$c" | sed 's|/sys/devices/system/cpu/cpu[0-9]*/cpuidle/||' | sort -u
  fi
done | sort -u

echo ""
echo "=== THERMALD ==="
LANG=C systemctl is-active thermald 2>/dev/null

echo ""
echo "=== KTP SYSTEMD TIMERS ==="
# Match the .timer unit name explicitly — previous `awk '{print $NF}'` was
# grabbing the ACTIVATES column (e.g. ktp-chrt.service) instead of UNIT.
systemctl list-timers 'ktp-*' --all 2>/dev/null | grep -oE 'ktp-[a-z0-9._-]+\.timer' | sort -u

echo ""
echo "=== KTP SYSTEMD UNITS STATE ==="
for u in $(systemctl list-units 'ktp-*' --all --no-legend 2>/dev/null | awk '{print $1}'); do
  state=$(systemctl is-active "$u" 2>/dev/null)
  echo "$u = $state"
done | sort

echo ""
echo "=== DODSERVER CRONTAB (non-comment, sorted) ==="
crontab -l 2>/dev/null | grep -vE '^\s*#|^\s*$' | sort

echo ""
echo "=== DOD-2701x COUNT ==="
echo "dod-dirs: $(ls -d ~/dod-2701* 2>/dev/null | wc -l)"
echo "ktp-disabled: $(ls ~/dod-2701*/.ktp-disabled 2>/dev/null | wc -l)"

echo ""
echo "=== KTP SAMPLE PORT ==="
echo "port: $KTP_SAMPLE_PORT"

echo ""
echo "=== KTP BINARIES md5 ==="
base=/home/dodserver/dod-$KTP_SAMPLE_PORT/serverfiles
for f in engine_i486.so libsteam_api.so hlds_linux \
         dod/addons/ktpamx/dlls/ktpamx_i386.so \
         dod/addons/ktpamx/modules/dodx_ktp_i386.so \
         dod/addons/ktpamx/modules/reapi_ktp_i386.so \
         dod/addons/ktpamx/modules/amxxcurl_ktp_i386.so; do
  full=$base/$f
  [ -f "$full" ] && echo "$f = $(md5sum "$full" | cut -c1-16)"
done

echo ""
echo "=== KTP PLUGINS md5 ==="
pdir=/home/dodserver/dod-$KTP_SAMPLE_PORT/serverfiles/dod/addons/ktpamx/plugins
for f in $pdir/*.amxx; do
  [ -f "$f" ] || continue
  echo "$(basename $f) = $(md5sum "$f" | cut -c1-16)"
done | sort

echo ""
echo "=== SCHEDULED RESTART SCRIPT ==="
echo "md5: $(md5sum /home/dodserver/ktp-scheduled-restart.sh 2>/dev/null | cut -c1-16)"
echo "cron: $(crontab -l 2>/dev/null | grep ktp-scheduled-restart | head -1 | awk '{print $1,$2,$3,$4,$5}')"
