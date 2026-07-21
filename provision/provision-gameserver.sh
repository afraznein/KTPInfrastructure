#!/bin/bash
# KTP Game Server Provisioning Script
# Prepares a fresh Ubuntu 22.04 server for KTP game server hosting
#
# Usage: sudo ./provision-gameserver.sh [OPTIONS]
#
# OPTIONS:
#   -y, --yes           Non-interactive mode (accept all defaults, install Netdata)
#   --no-netdata        Skip Netdata installation (only with -y)
#   --password <pass>   Set dodserver password (default: randomly generated,
#                       recorded to /root/ktp-gameserver-credentials.txt)
#   --num-servers <N>   Number of game server instances (default: 5)
#   --with-hltv         Set up co-located HLTV proxies + API on the same machine
#
# This script:
# 1. Creates dodserver user
# 2. Sets timezone and NTP (chrony)
# 3. Configures UDP buffers and performance sysctls
# 4. Enables noatime on all filesystems
# 5. Configures swap
# 6. Installs LinuxGSM dependencies (32-bit libs, steamcmd)
# 7. Configures firewall (UFW)
# 8. Optionally installs Netdata monitoring
# 9. Installs lowlatency kernel
# 10. CPU performance: governor=performance, ALL C-states disabled (max_cstate=0), mitigations=off
# 11. Memory optimizations: THP disabled, KSM disabled, compaction disabled
# 12. Network optimizations: GRO/LRO/TSO disabled, conntrack bypass, IRQ affinity
# 13. Dirty ratio tuning (vm.dirty_ratio=5)
# 14. Network budget tuning (netdev_budget=1200)
# 15. File descriptor limits (65535)
# 16. Installs fail2ban for SSH protection
# 17. CPU pinning + SCHED_FIFO scheduling (auto-applied every 30s)
# 18. CPU isolation: isolcpus + nohz_full + rcu_nocbs (baremetals with 8+ CPUs only)
# 19. Deploys ktp-fleet-health.sh + cron (Discord alerter on instance shortfall)
# 20. (Optional) Co-located HLTV: proxies, control script, API, systemd service

set -e

# ============================================
# Parse Arguments
# ============================================
NON_INTERACTIVE=false
INSTALL_NETDATA=true
# Empty = generate a random password at user creation (never a well-known
# default); --password overrides. The value used is recorded in
# /root/ktp-gameserver-credentials.txt and the final summary.
DODSERVER_PASSWORD=""
NUM_SERVERS=5
WITH_HLTV=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -y|--yes)
            NON_INTERACTIVE=true
            shift
            ;;
        --no-netdata)
            INSTALL_NETDATA=false
            shift
            ;;
        --password)
            DODSERVER_PASSWORD="$2"
            shift 2
            ;;
        --num-servers)
            NUM_SERVERS="$2"
            shift 2
            ;;
        --with-hltv)
            WITH_HLTV=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# ============================================
# Configuration
# ============================================
DODSERVER_USER="dodserver"
# TIMEZONE is overridable via env (e.g., LAN deployments outside ET).
TIMEZONE="${TIMEZONE:-America/New_York}"
SWAP_SIZE="2G"

# Derived port ranges
BASE_PORT=27015
MAX_PORT=$((BASE_PORT + NUM_SERVERS - 1))
GAME_PORT_RANGE="$BASE_PORT:$MAX_PORT"

# HLTV port range (starts after last game port)
if [ "$WITH_HLTV" = true ]; then
    HLTV_BASE_PORT=$((MAX_PORT + 1))
    HLTV_MAX_PORT=$((HLTV_BASE_PORT + NUM_SERVERS - 1))
    HLTV_PORT_RANGE="$HLTV_BASE_PORT:$HLTV_MAX_PORT"
fi

# For non-interactive apt
export DEBIAN_FRONTEND=noninteractive

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# ============================================
# Pre-flight Checks
# ============================================
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root"
    exit 1
fi

# Check for supported Ubuntu versions (22.04, 24.04, 26.04)
if grep -q "Ubuntu 22.04\|Ubuntu 24.04\|Ubuntu 26.04" /etc/os-release 2>/dev/null; then
    UBUNTU_VERSION=$(grep VERSION_ID /etc/os-release | cut -d'"' -f2)
    log_info "Detected Ubuntu $UBUNTU_VERSION"
else
    log_warn "This script is designed for Ubuntu 22.04, 24.04, or 26.04"
    if [ "$NON_INTERACTIVE" = false ]; then
        read -p "Continue anyway? (y/n) " -n 1 -r
        echo
        [[ ! $REPLY =~ ^[Yy]$ ]] && exit 1
    fi
fi

echo "========================================"
echo "KTP Game Server Provisioning"
echo "========================================"
echo ""

# ============================================
# 1. Create dodserver User
# ============================================
log_info "Creating dodserver user..."

if id "$DODSERVER_USER" &>/dev/null; then
    log_warn "User $DODSERVER_USER already exists"
    # An explicitly-passed --password must still converge on a re-run —
    # otherwise the orchestrator records a password that was never applied.
    # (Non-empty here ⟺ --password was given; generation only happens in the
    # creation branch below.)
    if [ -n "$DODSERVER_PASSWORD" ]; then
        echo "$DODSERVER_USER:$DODSERVER_PASSWORD" | chpasswd
        log_info "Applied --password to existing user $DODSERVER_USER"
    fi
else
    if [ -z "$DODSERVER_PASSWORD" ]; then
        DODSERVER_PASSWORD=$(head -c 512 /dev/urandom | tr -dc 'A-Za-z0-9' | head -c 32)  # pipefail-safe form
        log_warn "No --password given — generated a random dodserver password"
        umask 077
        echo "DODSERVER_PASSWORD=$DODSERVER_PASSWORD  # generated $(date -Iseconds)" >> /root/ktp-gameserver-credentials.txt
        chmod 600 /root/ktp-gameserver-credentials.txt
        log_warn "Recorded in /root/ktp-gameserver-credentials.txt"
    fi
    useradd -m -s /bin/bash "$DODSERVER_USER"
    echo "$DODSERVER_USER:$DODSERVER_PASSWORD" | chpasswd
    usermod -aG sudo "$DODSERVER_USER"
    log_info "Created user: $DODSERVER_USER"
fi

# ============================================
# 2. Set Timezone
# ============================================
log_info "Setting timezone to $TIMEZONE..."
timedatectl set-timezone "$TIMEZONE"

# Ensure RTC uses UTC (prevents Netdata clock sync warnings)
timedatectl set-local-rtc 0

# ============================================
# 3. Install NTP (chrony)
# ============================================
log_info "Installing chrony for NTP sync..."
apt-get update
apt-get install -y chrony

systemctl enable chrony
systemctl start chrony

# Wait for sync
sleep 2
if chronyc tracking | grep -q "Leap status.*Normal"; then
    log_info "NTP synchronized successfully"
else
    log_warn "NTP may not be fully synchronized yet"
fi

# ============================================
# 4. Configure UDP Buffers & Performance Sysctls
# ============================================
log_info "Configuring UDP buffers and performance settings..."

# Write to a drop-in, NOT /etc/sysctl.conf. On Ubuntu 26.04 systemd-sysctl no
# longer applies /etc/sysctl.conf at boot (only /etc/sysctl.d/*.conf), so values
# appended there silently revert to kernel defaults on reboot (rmem_max back to
# 4MB, busy_poll to 0, etc.). A drop-in is applied on every boot.
cat > /etc/sysctl.d/98-ktp-network.conf << 'EOF'
# KTP Game Server UDP buffers (25MB)
net.core.rmem_max=26214400
net.core.rmem_default=26214400
net.core.wmem_max=26214400
net.core.wmem_default=26214400

# KTP Game Server Performance Tuning
kernel.nmi_watchdog = 0
# No soft-lockup watchdog timers on isolated game cores (fleet-wide 2026-07-02)
kernel.watchdog = 0
net.ipv4.tcp_low_latency = 1
net.core.busy_read = 100
net.core.busy_poll = 100
net.core.netdev_max_backlog = 5000
EOF

sysctl --system >/dev/null

log_info "UDP buffers set to 25MB, performance sysctls applied"

# ============================================
# 5. Enable noatime on All Filesystems
# ============================================
log_info "Enabling noatime on all filesystems..."

# noatime eliminates a write I/O for every file read (no access time updates).
# Reduces SSD wear and eliminates intermittent I/O latency spikes from atime writes
# hitting SSD garbage collection pauses.

# Update fstab: add noatime to all ext2/ext3/ext4 mount entries
if grep -qP 'ext[234]' /etc/fstab; then
    cp /etc/fstab /etc/fstab.bak.provision
    # Add noatime to "defaults" entries
    sed -i '/ext[234]/{s/defaults/defaults,noatime/}' /etc/fstab
    # Add noatime to entries with "errors=" but no "defaults" (e.g., Chicago)
    sed -i '/ext[234]/{/noatime/!s/errors=/noatime,errors=/}' /etc/fstab
    log_info "Updated /etc/fstab with noatime"
fi

# Remount all ext filesystems with noatime immediately
mount -o remount,noatime / 2>/dev/null || true
for mp in $(mount | grep 'type ext[234]' | awk '{print $3}' | grep -v '^/$'); do
    mount -o remount,noatime "$mp" 2>/dev/null || true
done

log_info "noatime enabled on all filesystems"

# ============================================
# 6. Configure Swap
# ============================================
log_info "Configuring swap..."

# Check if swap already exists (file or partition)
EXISTING_SWAP=$(swapon --show --noheadings | wc -l)
if [ "$EXISTING_SWAP" -gt 0 ]; then
    log_warn "Swap already configured:"
    swapon --show
else
    log_info "Creating $SWAP_SIZE swap file..."
    fallocate -l $SWAP_SIZE /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile

    # Add to fstab for persistence
    echo '/swapfile none swap sw 0 0' >> /etc/fstab

    log_info "Swap configured: $SWAP_SIZE"
fi

# ============================================
# 7. Install Dependencies
# ============================================
log_info "Installing system dependencies..."

# Enable 32-bit architecture
dpkg --add-architecture i386
apt-get update -qq

# Pre-accept Steam license agreement (required for steamcmd)
echo "steamcmd steam/question select I AGREE" | debconf-set-selections
echo "steamcmd steam/license note " | debconf-set-selections

# Install game server dependencies
apt-get install -y \
    lib32gcc-s1 \
    lib32stdc++6 \
    lib32z1 \
    libsdl2-2.0-0:i386 \
    steamcmd \
    curl \
    wget \
    ca-certificates \
    file \
    bzip2 \
    gzip \
    unzip \
    bsdmainutils \
    python3 \
    util-linux \
    binutils \
    bc \
    jq \
    tmux \
    netcat-openbsd \
    pigz \
    xz-utils \
    ethtool \
    iptables

# 32-bit libcurl: Ubuntu's 64-bit time_t transition renamed libcurl4 -> libcurl4t64
# (24.04+), and the old name has no i386 package on 26.04. Install whichever the
# release actually provides so 22.04/24.04/26.04 all work.
CURL_I386_DONE=0
for pkg in libcurl4t64:i386 libcurl4:i386; do
    if apt-cache show "$pkg" >/dev/null 2>&1; then
        apt-get install -y "$pkg" && { CURL_I386_DONE=1; break; }
    fi
done
[ "$CURL_I386_DONE" -eq 1 ] || log_warn "No i386 libcurl package found (libcurl4t64:i386/libcurl4:i386) — amxxcurl may fail to load"

log_info "Dependencies installed"

# ============================================
# 8. Configure Firewall (UFW)
# ============================================
log_info "Configuring firewall..."

apt-get install -y ufw

ufw allow 22/tcp comment "SSH"
ufw allow $GAME_PORT_RANGE/udp comment "DoD Game Servers"
ufw allow $GAME_PORT_RANGE/tcp comment "DoD RCON"

# HLTV ports (if co-located)
if [ "$WITH_HLTV" = true ]; then
    ufw allow $HLTV_PORT_RANGE/udp comment "HLTV Proxies"
    ufw allow 8087/tcp comment "HLTV API"
fi

# Netdata port - ask or use default based on mode
if [ "$NON_INTERACTIVE" = true ]; then
    if [ "$INSTALL_NETDATA" = true ]; then
        ufw allow 19999/tcp comment "Netdata"
    fi
else
    read -p "Enable Netdata monitoring port (19999)? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        ufw allow 19999/tcp comment "Netdata"
        INSTALL_NETDATA=true
    else
        INSTALL_NETDATA=false
    fi
fi

ufw --force enable
ufw status

# ============================================
# 9. Install Netdata (Optional)
# ============================================
if [ "$NON_INTERACTIVE" = false ]; then
    read -p "Install Netdata monitoring? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        INSTALL_NETDATA=true
    else
        INSTALL_NETDATA=false
    fi
fi

if [ "$INSTALL_NETDATA" = true ]; then
    log_info "Installing Netdata..."

    wget -q -O /tmp/netdata-kickstart.sh https://get.netdata.cloud/kickstart.sh
    sh /tmp/netdata-kickstart.sh --non-interactive

    systemctl enable netdata
    systemctl start netdata

    log_info "Netdata installed and running on port 19999"
else
    log_info "Skipping Netdata installation"
fi

# ============================================
# 10. Install Lowlatency Kernel
# ============================================
log_info "Configuring low-latency kernel..."

# Kernel strategy differs by release:
#  - 22.04 / 24.04: the generic kernel is 250Hz; the separate `linux-lowlatency`
#    image (1000Hz, PREEMPT) is worth booting. Install it.
#  - 26.04+: the GENERIC kernel is already CONFIG_HZ=1000 + NO_HZ_FULL +
#    PREEMPT_DYNAMIC, and `linux-lowlatency` there is NOT a separate image — it
#    just pulls a `lowlatency-kernel` settings pkg whose GRUB drop-in forces
#    `preempt=full rcu_nocbs=all`. preempt=full was rolled back on the fleet
#    after a p99 regression, and rcu_nocbs=all collides with our rcu_nocbs=2-7.
#    So on 26.04+ we stay on generic and strip that drop-in.
UBU_VER=$(. /etc/os-release 2>/dev/null; echo "${VERSION_ID:-unknown}")
case "$UBU_VER" in
    22.04|24.04)
        if apt-cache show linux-lowlatency >/dev/null 2>&1; then
            apt-get install -y linux-lowlatency || log_warn "linux-lowlatency install failed — staying on current kernel"
        elif apt-cache show linux-image-lowlatency >/dev/null 2>&1; then
            apt-get install -y linux-image-lowlatency linux-headers-lowlatency || log_warn "lowlatency kernel install failed"
        else
            log_warn "No lowlatency kernel package on this release — staying on generic"
        fi
        ;;
    *)
        log_info "Ubuntu $UBU_VER generic kernel is already 1000Hz/NO_HZ_FULL/PREEMPT_DYNAMIC — staying on generic"
        ;;
esac

# Never boot preempt=full (p99 regression on the fleet). If the lowlatency-kernel
# settings package slipped a drop-in in, remove it before update-grub below.
if [ -f /etc/default/grub.d/99-lowlatency.cfg ]; then
    rm -f /etc/default/grub.d/99-lowlatency.cfg
    log_info "Removed /etc/default/grub.d/99-lowlatency.cfg (avoids preempt=full/rcu_nocbs=all)"
fi

# Get the installed lowlatency kernel version
LOWLATENCY_KERNEL=$(ls /boot/vmlinuz-*-lowlatency 2>/dev/null | sort -V | tail -1 | sed 's|/boot/vmlinuz-||')
if [ -n "$LOWLATENCY_KERNEL" ]; then
    log_info "Lowlatency kernel installed: $LOWLATENCY_KERNEL"

    # Boot the lowlatency kernel by NAME, not by positional submenu index. The
    # old "1>2" (submenu 1, entry 2) silently inverts if grub's version sort
    # orders the freshly-pulled lowlatency kernel differently from the ISO's
    # generic — booting generic (250Hz, no CPU isolation) with no error. The
    # name path is stable across sort order.
    GRUB_LL_ENTRY="Advanced options for Ubuntu>Ubuntu, with Linux ${LOWLATENCY_KERNEL}"
    log_info "Configuring GRUB to boot lowlatency kernel by name..."
    sed -i "s|^GRUB_DEFAULT=.*|GRUB_DEFAULT=\"${GRUB_LL_ENTRY}\"|" /etc/default/grub
    update-grub
    if grep -q "with Linux ${LOWLATENCY_KERNEL}'" /boot/grub/grub.cfg 2>/dev/null; then
        log_info "GRUB default set to: $GRUB_LL_ENTRY"
    else
        log_warn "Could not confirm the lowlatency menuentry in grub.cfg — VERIFY after reboot"
        log_warn "  uname -r should end in -lowlatency; if it doesn't, run:"
        log_warn "  grub-set-default '$GRUB_LL_ENTRY' && update-grub"
    fi

    log_warn "REBOOT REQUIRED to activate lowlatency kernel!"
else
    log_warn "Lowlatency kernel installation may have failed"
fi

# ============================================
# 11. CPU Performance Optimizations
# ============================================
log_info "Configuring CPU performance optimizations..."

# Set CPU governor to performance (immediate)
for gov in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    echo performance > "$gov" 2>/dev/null || true
done

# Disable ALL C-states for lowest latency (immediate)
for cpu in /sys/devices/system/cpu/cpu*/cpuidle; do
    for state in $cpu/state*/disable; do
        echo 1 > "$state" 2>/dev/null || true
    done
done

# Apply memory optimizations immediately
log_info "Applying memory optimizations..."
# THP fully OFF — fleet standard since 2026-07-02 (khugepaged compaction
# stalls; HLDS gets no THP benefit). Was `madvise` before that. Persisted via
# tmpfiles.d below, NOT rc.local: rc-local.service runs AFTER
# systemd-tmpfiles-setup, so an rc.local THP line would silently override the
# tmpfiles value at every boot.
echo never > /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null || true
echo never > /sys/kernel/mm/transparent_hugepage/defrag 2>/dev/null || true
echo 'w /sys/kernel/mm/transparent_hugepage/enabled - - - - never' > /etc/tmpfiles.d/ktp-thp.conf
echo 0 > /proc/sys/vm/compaction_proactiveness 2>/dev/null || true
echo 0 > /sys/kernel/mm/ksm/run 2>/dev/null || true
echo 1000 > /sys/kernel/mm/lru_gen/min_ttl_ms 2>/dev/null || true

# Apply network optimizations immediately
log_info "Applying network optimizations..."
IFACE=$(ip route | grep default | awk '{print $5}' | head -1)
if [ -n "$IFACE" ] && command -v ethtool &>/dev/null; then
    ethtool -K $IFACE gro off 2>/dev/null || true
    ethtool -K $IFACE lro off 2>/dev/null || true
    ethtool -K $IFACE tso off 2>/dev/null || true
    ethtool -G $IFACE rx 4096 tx 4096 2>/dev/null || true
    ethtool -C $IFACE rx-usecs 1 2>/dev/null || true
    tc qdisc replace dev "$IFACE" root pfifo_fast 2>/dev/null || true
fi

# Apply conntrack bypass immediately
if command -v iptables &>/dev/null; then
    iptables -t raw -D PREROUTING -p udp --dport $GAME_PORT_RANGE -j NOTRACK 2>/dev/null || true
    iptables -t raw -D OUTPUT -p udp --sport $GAME_PORT_RANGE -j NOTRACK 2>/dev/null || true
    iptables -t raw -A PREROUTING -p udp --dport $GAME_PORT_RANGE -j NOTRACK 2>/dev/null || true
    iptables -t raw -A OUTPUT -p udp --sport $GAME_PORT_RANGE -j NOTRACK 2>/dev/null || true
    # HLTV conntrack bypass (if co-located)
    if [ "$WITH_HLTV" = true ]; then
        iptables -t raw -D PREROUTING -p udp --dport $HLTV_PORT_RANGE -j NOTRACK 2>/dev/null || true
        iptables -t raw -D OUTPUT -p udp --sport $HLTV_PORT_RANGE -j NOTRACK 2>/dev/null || true
        iptables -t raw -A PREROUTING -p udp --dport $HLTV_PORT_RANGE -j NOTRACK 2>/dev/null || true
        iptables -t raw -A OUTPUT -p udp --sport $HLTV_PORT_RANGE -j NOTRACK 2>/dev/null || true
    fi
fi

# Persist NOTRACK in ufw's before.rules too — not just rc.local. rc.local only
# re-applies at BOOT, so a mid-event `ufw reload`/`ufw enable` would flush the
# raw-table NOTRACK rules and per-packet conntrack overhead returns until the
# next reboot. The *raw table block must be a complete block with its own COMMIT.
UFW_BEFORE=/etc/ufw/before.rules
if [ -f "$UFW_BEFORE" ] && ! grep -q "KTP NOTRACK" "$UFW_BEFORE"; then
    RAW_BLOCK="*raw
:PREROUTING ACCEPT [0:0]
:OUTPUT ACCEPT [0:0]
# KTP NOTRACK - bypass conntrack for game UDP (survives ufw reload)
-A PREROUTING -p udp --dport ${GAME_PORT_RANGE} -j NOTRACK
-A OUTPUT -p udp --sport ${GAME_PORT_RANGE} -j NOTRACK"
    if [ "$WITH_HLTV" = true ]; then
        RAW_BLOCK="${RAW_BLOCK}
-A PREROUTING -p udp --dport ${HLTV_PORT_RANGE} -j NOTRACK
-A OUTPUT -p udp --sport ${HLTV_PORT_RANGE} -j NOTRACK"
    fi
    RAW_BLOCK="${RAW_BLOCK}
COMMIT
"
    # Prepend the complete *raw block above before.rules' existing *filter block.
    printf '%s\n%s\n' "$RAW_BLOCK" "$(cat "$UFW_BEFORE")" > "$UFW_BEFORE"
    log_info "Added KTP NOTRACK *raw block to $UFW_BEFORE (survives ufw reload)"
fi

# Create rc.local for persistence across reboots
cat > /etc/rc.local << 'RCEOF'
#!/bin/bash
# KTP Game Server Performance - applied at boot
# See: KTPInfrastructure/docs/UBUNTU_OPTIMIZATION_RESEARCH.md

# ============================================
# CPU Performance
# ============================================

# Lock CPU to max frequency (performance governor)
for gov in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    echo performance > "$gov" 2>/dev/null
done

# Disable ALL C-states for lowest latency (including C1/C1E)
for cpu in /sys/devices/system/cpu/cpu*/cpuidle; do
    for state in $cpu/state*/disable; do
        echo 1 > "$state" 2>/dev/null
    done
done

# ============================================
# Memory Optimizations
# ============================================

# THP fully OFF — fleet standard 2026-07-02. /etc/tmpfiles.d/ktp-thp.conf is
# the primary owner; this line writes the SAME value so the (later-running)
# rc-local can never fight it. The pre-2026-07-07 version wrote `madvise`
# here, silently overriding tmpfiles' `never` at every boot.
echo never > /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null
echo never > /sys/kernel/mm/transparent_hugepage/defrag 2>/dev/null

# Disable proactive memory compaction (reduces random micro-stalls)
echo 0 > /proc/sys/vm/compaction_proactiveness 2>/dev/null

# Disable KSM memory deduplication (saves CPU cycles)
echo 0 > /sys/kernel/mm/ksm/run 2>/dev/null

# MGLRU min TTL - keep hot pages in memory longer (kernel 6.1+)
echo 1000 > /sys/kernel/mm/lru_gen/min_ttl_ms 2>/dev/null

# ============================================
# Network Optimizations
# ============================================

IFACE=$(ip route | grep default | awk '{print $5}' | head -1)
if [ -n "$IFACE" ] && command -v ethtool &>/dev/null; then
    # Disable NIC offloading for lower latency (process each packet immediately)
    ethtool -K $IFACE gro off 2>/dev/null
    ethtool -K $IFACE lro off 2>/dev/null
    ethtool -K $IFACE tso off 2>/dev/null

    # Increase ring buffers to max (4096) to handle burst traffic
    ethtool -G $IFACE rx 4096 tx 4096 2>/dev/null

    # Lower interrupt coalescing for lower latency
    ethtool -C $IFACE rx-usecs 1 2>/dev/null

    # pfifo_fast qdisc — avoids fq_codel's per-packet overhead on the game
    # NIC (fleet standard; expected-rc-local.conf audits for this line, and
    # the pre-2026-07-07 version of this script never generated it — every
    # freshly provisioned host failed that audit pattern forever)
    tc qdisc replace dev "$IFACE" root pfifo_fast 2>/dev/null
fi

# Conntrack bypass for game server ports (eliminates per-packet lookup overhead)
# Only apply if iptables is available
if command -v iptables &>/dev/null; then
    # Clear any existing NOTRACK rules first to avoid duplicates
    iptables -t raw -D PREROUTING -p udp --dport GAME_PORT_RANGE_PLACEHOLDER -j NOTRACK 2>/dev/null
    iptables -t raw -D OUTPUT -p udp --sport GAME_PORT_RANGE_PLACEHOLDER -j NOTRACK 2>/dev/null

    # Add fresh rules
    iptables -t raw -A PREROUTING -p udp --dport GAME_PORT_RANGE_PLACEHOLDER -j NOTRACK
    iptables -t raw -A OUTPUT -p udp --sport GAME_PORT_RANGE_PLACEHOLDER -j NOTRACK
fi

# ============================================
# IRQ Affinity - Steer to Housekeeping CPUs
# ============================================

# Steer all IRQs to housekeeping CPUs 0,1 (bitmask 0x03)
# Only on baremetals (8+ CPUs) where CPU isolation is active
if [ $(nproc) -gt 4 ]; then
    echo 3 > /proc/irq/default_smp_affinity 2>/dev/null
    for irq_dir in /proc/irq/[0-9]*; do
        irq=$(basename "$irq_dir")
        [ "$irq" = "0" ] || [ "$irq" = "2" ] && continue
        echo 3 > "$irq_dir/smp_affinity" 2>/dev/null || true
    done
fi

exit 0
RCEOF
chmod +x /etc/rc.local

# Substitute dynamic port range into rc.local (heredoc is single-quoted, so variables don't expand)
sed -i "s|GAME_PORT_RANGE_PLACEHOLDER|$GAME_PORT_RANGE|g" /etc/rc.local

# Add HLTV conntrack bypass to rc.local if co-located
if [ "$WITH_HLTV" = true ]; then
    sed -i "/NOTRACK$/a\\
    # HLTV conntrack bypass\\
    iptables -t raw -D PREROUTING -p udp --dport $HLTV_PORT_RANGE -j NOTRACK 2>/dev/null\\
    iptables -t raw -D OUTPUT -p udp --sport $HLTV_PORT_RANGE -j NOTRACK 2>/dev/null\\
    iptables -t raw -A PREROUTING -p udp --dport $HLTV_PORT_RANGE -j NOTRACK\\
    iptables -t raw -A OUTPUT -p udp --sport $HLTV_PORT_RANGE -j NOTRACK" /etc/rc.local
fi

# Enable rc-local service - Ubuntu 22.04+ doesn't have this by default
# Create systemd service file if it doesn't exist
if [ ! -f /etc/systemd/system/rc-local.service ]; then
    cat > /etc/systemd/system/rc-local.service << 'SVCEOF'
[Unit]
Description=KTP rc.local Compatibility
ConditionPathExists=/etc/rc.local
After=network.target

[Service]
Type=forking
ExecStart=/etc/rc.local start
TimeoutSec=0
RemainAfterExit=yes
GuessMainPID=no

[Install]
WantedBy=multi-user.target
SVCEOF
fi

systemctl daemon-reload
systemctl enable rc-local
systemctl start rc-local 2>/dev/null || true

log_info "rc.local service configured and enabled"

# Add C-state limit to GRUB for full persistence
# Using max_cstate=0 disables ALL C-states including C1/C1E for lowest latency
if [ -f /etc/default/grub.d/gth.cfg ]; then
    GRUB_CFG="/etc/default/grub.d/gth.cfg"
else
    GRUB_CFG="/etc/default/grub"
fi

if ! grep -q "intel_idle.max_cstate" "$GRUB_CFG"; then
    sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT="\(.*\)"/GRUB_CMDLINE_LINUX_DEFAULT="\1 intel_idle.max_cstate=0 processor.max_cstate=0 mitigations=off"/' "$GRUB_CFG"
fi

# ============================================
# CPU layout detection (shared by isolation + pinning below)
# ============================================
# Detect the real core count so the layout adapts to whatever chip the box
# actually has — more cores than expected is fine (we use them); fewer than
# needed triggers a loud alert (see below). Reserve CPUs 0,1 for the OS, IRQs,
# HLTV and TeamSpeak; everything from CPU 2 up is available to pin game servers.
NUM_CPUS=$(nproc --all)
RESERVED_CPUS=2
[ "$NUM_CPUS" -le 4 ] && RESERVED_CPUS=1          # tiny VPS: reserve only CPU 0
FIRST_GAME_CPU=$RESERVED_CPUS
AVAIL_GAME_CPUS=$((NUM_CPUS - RESERVED_CPUS))
[ "$AVAIL_GAME_CPUS" -lt 1 ] && AVAIL_GAME_CPUS=1

# Pre-flight: alert the installer if there aren't enough dedicated cores for one
# core per server. Not a hard fail (we still pin round-robin), but the operator
# MUST know timing will be degraded. Skipped for tiny VPS (<=4), which is
# intentionally oversubscribed.
if [ "$NUM_CPUS" -gt 4 ] && [ "$AVAIL_GAME_CPUS" -lt "$NUM_SERVERS" ]; then
    log_warn "================================================================"
    log_warn " NOT ENOUGH CORES FOR ONE-CORE-PER-SERVER PINNING"
    log_warn " Detected $NUM_CPUS CPUs -> $AVAIL_GAME_CPUS usable for game servers,"
    log_warn " but $NUM_SERVERS servers were requested."
    log_warn " $((NUM_SERVERS - AVAIL_GAME_CPUS)) server(s) will SHARE a core -> expect timing jitter."
    log_warn " For $NUM_SERVERS servers, use a CPU with at least $((NUM_SERVERS + RESERVED_CPUS)) cores."
    log_warn "================================================================"
    if [ "${YES:-0}" != "1" ]; then
        read -p "Continue with oversubscribed cores anyway? (y/n) " -n 1 -r; echo
        [[ ! $REPLY =~ ^[Yy]$ ]] && exit 1
    fi
elif [ "$NUM_CPUS" -gt 4 ]; then
    log_info "Detected $NUM_CPUS CPUs — $AVAIL_GAME_CPUS usable for $NUM_SERVERS game servers ($((AVAIL_GAME_CPUS - NUM_SERVERS)) core(s) spare)"
fi

# Isolation list = exactly the CPUs game servers get pinned to.
GAME_CPU_COUNT=$NUM_SERVERS
[ "$GAME_CPU_COUNT" -gt "$AVAIL_GAME_CPUS" ] && GAME_CPU_COUNT=$AVAIL_GAME_CPUS
if [ "$NUM_CPUS" -eq 8 ] && [ "$NUM_SERVERS" -le 5 ]; then
    # Preserve the proven cloud-fleet 4c/8t map exactly — no drift on reprovision.
    ISOLCPUS_LIST="2,3,4,5,6,7"
else
    ISOLCPUS_LIST=$(seq -s, "$FIRST_GAME_CPU" "$((FIRST_GAME_CPU + GAME_CPU_COUNT - 1))")
fi

# isolcpus only makes sense on multi-core hosts (skip tiny VPS).
if [ "$NUM_CPUS" -gt 4 ] && ! grep -q "isolcpus" "$GRUB_CFG"; then
    sed -i "s/GRUB_CMDLINE_LINUX_DEFAULT=\"\(.*\)\"/GRUB_CMDLINE_LINUX_DEFAULT=\"\1 isolcpus=$ISOLCPUS_LIST nohz_full=$ISOLCPUS_LIST rcu_nocbs=$ISOLCPUS_LIST\"/" "$GRUB_CFG"
    log_info "Added CPU isolation params (isolcpus=$ISOLCPUS_LIST)"
fi

update-grub

log_info "CPU governor set to performance, ALL C-states disabled (max_cstate=0)"

# ============================================
# 10.5. Dirty Ratio & Network Budget Tuning
# ============================================
log_info "Configuring dirty ratio and network budget tuning..."

# Create sysctl config for memory/write behavior and network tuning
cat > /etc/sysctl.d/99-ktp-gameserver.conf << 'EOF'
# KTP Game Server - Dirty ratio tuning
# Smaller write batches = reduced I/O stutter
vm.dirty_ratio = 5
vm.dirty_background_ratio = 5

# KTP Game Server - Network device budget
# Higher values allow more packets per softirq cycle, reducing latency spikes
net.core.netdev_budget = 1200
net.core.netdev_budget_usecs = 8000

# KTP Game Server - Phase 2 performance tuning (fleet-wide since 2026-04-13).
# These were historically applied by hand and were missing from this script.
# sched_rt_runtime_us=-1 is the important one: the default 950000 RT-throttles
# SCHED_FIFO to 95%, which would starve the chrt-pinned game servers.
kernel.sched_rt_runtime_us = -1
kernel.timer_migration = 0
kernel.sched_autogroup_enabled = 0
vm.swappiness = 1
vm.stat_interval = 120
net.core.netdev_tstamp_prequeue = 0
net.core.netdev_max_backlog = 5000

# Core dump path for KTPCrashReporter (apport is masked above so it can't
# re-clobber this at boot).
kernel.core_pattern = /tmp/core.%e.%p.%t
EOF

sysctl -p /etc/sysctl.d/99-ktp-gameserver.conf

log_info "Dirty ratio and netdev_budget tuning applied"

# ============================================
# 11. File Descriptor Limits
# ============================================
log_info "Configuring file descriptor limits..."

cat >> /etc/security/limits.conf << 'EOF'

# KTP Game Server - increased limits
dodserver soft nofile 65535
dodserver hard nofile 65535
dodserver soft nproc 65535
dodserver hard nproc 65535
dodserver        -       nice            -5
# Allow crash cores to actually be written: core_pattern=/tmp/core.%e.%p.%t is
# configured via sysctl.d, but without an unlimited core ulimit hlds may write
# no core at all.
dodserver soft core unlimited
dodserver hard core unlimited
EOF

log_info "File descriptor limits increased to 65535"

# ============================================
# 12. Install fail2ban
# ============================================
log_info "Installing fail2ban for SSH protection..."

apt-get install -y fail2ban

cat > /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
bantime = 1h
findtime = 10m
maxretry = 5
banaction = ufw

[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 24h
EOF

systemctl enable fail2ban
systemctl restart fail2ban

log_info "fail2ban installed and configured"

# ============================================
# 12b. Mask Apport Units (prevent core_pattern override)
# ============================================
# Apport (still present/enabled on 26.04) rewrites /proc/sys/kernel/core_pattern
# at boot even with enabled=0, clobbering KTPCrashReporter's core harvesting.
# Mask here in the root provisioning context — clone-ktp-stack.sh also tries this
# but runs as the dodserver user whose sudoers only allows renice/chrt/taskset,
# so its `sudo systemctl mask` fails silently. Idempotent; safe if apport absent.
log_info "Masking apport units (prevents core_pattern override at next reboot)..."
systemctl mask apport.service apport-autoreport.timer apport-autoreport.service \
    apport-autoreport.path apport-forward.socket >/dev/null 2>&1 \
    && log_info "apport units masked" \
    || log_warn "apport mask returned non-zero (verify: systemctl is-enabled apport.service)"

# ============================================
# 12c. Disable thermald (conflicts with performance governor)
# ============================================
# thermald can throttle/rescale CPUs out from under the performance governor.
log_info "Disabling thermald..."
systemctl disable --now thermald >/dev/null 2>&1 \
    && log_info "thermald disabled" \
    || log_info "thermald not present/already disabled"

# ============================================
# 13. Create Server Directories
# ============================================
log_info "Creating server directories..."

su - "$DODSERVER_USER" -c 'mkdir -p ~/log ~/backups'

# ============================================
# 14. Set Process Priority
# ============================================
log_info "Configuring process priority..."

# Add to sudoers for renice, chrt, and taskset without password
cat > /etc/sudoers.d/dodserver << 'EOF'
dodserver ALL=(ALL) NOPASSWD: /usr/bin/renice
dodserver ALL=(ALL) NOPASSWD: /usr/bin/chrt
dodserver ALL=(ALL) NOPASSWD: /usr/bin/taskset
EOF
chmod 440 /etc/sudoers.d/dodserver

# ============================================
# 15. Create CPU Pinning + SCHED_FIFO Service
# ============================================
# This ensures CPU pinning and real-time scheduling is applied to game servers
# even when LinuxGSM monitor restarts them after a crash.
log_info "Creating CPU pinning + SCHED_FIFO auto-apply service..."

# Build the port->CPU pinning map from the CPU layout detected earlier
# (NUM_CPUS, FIRST_GAME_CPU, AVAIL_GAME_CPUS).
if [ "$NUM_CPUS" -le 4 ]; then
    # Tiny VPS (e.g. Chicago 4 vCPU): matches scripts/deploy-chrt-service.sh
    # --chicago (27015-17 on 1-3; 27018/27019 share cpu0 with housekeeping).
    DEDICATED=(1 2 3 0 0)
    CPU_COMMENT="# vCPU layout: 0=sys+overflow"
elif [ "$NUM_CPUS" -eq 8 ] && [ "$NUM_SERVERS" -le 5 ]; then
    # The ACTUAL cloud-fleet 4c/8t map: ports 27015-19 -> CPUs 2,5,4,3,7
    # (sibling pairs (0,4)(1,5)(2,6)(3,7); cpu0/1 housekeeping). The
    # pre-2026-07-07 value here was 2,3,5,6,7 while CLAIMING to match the
    # fleet — a reprovisioned host would have put 27018 on cpu6, the HT
    # sibling of 27015's cpu2, destroying the "27015 is the only clean
    # exclusive core" match-hosting policy. Keep in sync with the root
    # CLAUDE.md placement table + scripts/deploy-chrt-service.sh.
    DEDICATED=(2 5 4 3 7)
    CPU_COMMENT="# CPU layout: 0,1=sys (NIC IRQs); sibling pairs (0,4)(1,5)(2,6)(3,7)"
else
    # General / LAN box: one game server per CPU from FIRST_GAME_CPU up.
    DEDICATED=()
    for c in $(seq "$FIRST_GAME_CPU" "$((FIRST_GAME_CPU + AVAIL_GAME_CPUS - 1))"); do
        DEDICATED+=("$c")
    done
    CPU_COMMENT="# CPU layout: 0,1=sys/HLTV/TeamSpeak"
fi

CPU_MAP_ENTRIES=""
for i in $(seq 1 $NUM_SERVERS); do
    port=$((BASE_PORT + i - 1))
    # One dedicated CPU each; if servers outnumber CPUs, wrap round-robin.
    cpu=${DEDICATED[$(( (i - 1) % ${#DEDICATED[@]} ))]}
    CPU_MAP_ENTRIES="$CPU_MAP_ENTRIES[$port]=$cpu "
    CPU_COMMENT="$CPU_COMMENT, $cpu=$port"
done
CPU_MAP_LINE="declare -A PORT_CPU_MAP=($CPU_MAP_ENTRIES)"
log_info "Detected $NUM_CPUS CPUs — pinning $NUM_SERVERS servers to CPUs ${DEDICATED[*]}"

# Create the script that applies CPU pinning + SCHED_FIFO to game servers
cat > /usr/local/bin/ktp-apply-chrt.sh << CHRTSCRIPT
#!/bin/bash
# KTP Game Server CPU Pinning + Real-Time Scheduling
# Run by: ktp-chrt.timer (every 5 minutes)
# Purpose: Safety net - ensures scheduling survives process restarts
# Primary setting is done by ktp-scheduled-restart.sh at boot
$CPU_COMMENT
$CPU_MAP_LINE

# Re-assert the performance governor every run. intel_pstate boots in powersave,
# and rc.local's early set can be reset before cpufreq init finishes, so the
# governor must be re-asserted after boot (this runs at OnBootSec=60 + every 5m).
# Done before the no-servers early-exit so it holds even with servers stopped.
for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    [ "\$(cat "\$g" 2>/dev/null)" != performance ] && echo performance > "\$g" 2>/dev/null
done

pids=\$(pgrep -f hlds_linux 2>/dev/null)
[ -z "\$pids" ] && exit 0

# Check all processes - at 5-minute intervals the overhead is negligible
for pid in \$pids; do
    port=\$(tr '\\0' ' ' < /proc/\$pid/cmdline 2>/dev/null | grep -oP '(?<=-port )\\d+')
    [ -z "\$port" ] && port=\$(ps -p "\$pid" -o args= 2>/dev/null | grep -oP '(?<=-port )\\d+')
    [ -z "\$port" ] && continue

    target_cpu=\${PORT_CPU_MAP[\$port]}
    [ -z "\$target_cpu" ] && continue

    # Pin to designated CPU
    current=\$(taskset -cp "\$pid" 2>/dev/null | grep -oP '(?<=: ).*')
    [ "\$current" != "\$target_cpu" ] && sudo taskset -cp "\$target_cpu" "\$pid" 2>/dev/null && \\
        logger -t ktp-chrt "Pinned port \$port PID \$pid to CPU \$target_cpu"

    # Apply SCHED_FIFO priority 50
    policy=\$(chrt -p "\$pid" 2>/dev/null | grep -o 'SCHED_[A-Z]*')
    [ "\$policy" != "SCHED_FIFO" ] && sudo chrt -f -p 50 "\$pid" 2>/dev/null && \\
        logger -t ktp-chrt "Applied SCHED_FIFO 50 to port \$port PID \$pid"
done

exit 0
CHRTSCRIPT
chmod +x /usr/local/bin/ktp-apply-chrt.sh

# Create systemd service (oneshot)
cat > /etc/systemd/system/ktp-chrt.service << 'CHRTSVC'
[Unit]
Description=KTP Game Server Real-Time Scheduling
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/ktp-apply-chrt.sh
CHRTSVC

# Create systemd timer (runs every 5 minutes)
cat > /etc/systemd/system/ktp-chrt.timer << 'CHRTTIMER'
[Unit]
Description=Apply real-time scheduling to KTP game servers

[Timer]
OnBootSec=60
OnUnitActiveSec=300
AccuracySec=5

[Install]
WantedBy=timers.target
CHRTTIMER

# Enable and start the timer
systemctl daemon-reload
systemctl enable ktp-chrt.timer
systemctl start ktp-chrt.timer

log_info "chrt auto-apply timer enabled (runs every 5 minutes, early-exit when already configured)"

# ============================================
# 16. Deploy ktp-fleet-health.sh Alerter
# ============================================
# Per-host alerter: fires a Discord embed when `pgrep -c hlds_linux` falls
# below the expected instance count for THRESHOLD_MINUTES consecutive
# minutes. Single post per state transition, silent when healthy.
# Source-of-truth: KTPInfrastructure/monitoring/fleet-health/.
# Config: /etc/ktp/fleet-health.conf — empty/missing WEBHOOK_URL = silent
# local-only monitoring (state file still updated, no network call).
log_info "Deploying ktp-fleet-health.sh alerter..."

# Resolve the canonical script location relative to this provision script.
# The repo layout is KTPInfrastructure/provision/<this>.sh and
# KTPInfrastructure/monitoring/fleet-health/ktp-fleet-health.sh — siblings.
PROVISION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET_HEALTH_SRC="$PROVISION_DIR/../monitoring/fleet-health/ktp-fleet-health.sh"
FLEET_HEALTH_CONF_TEMPLATE="$PROVISION_DIR/../monitoring/fleet-health/fleet-health.conf.example"

if [ ! -f "$FLEET_HEALTH_SRC" ]; then
    log_error "Cannot find canonical ktp-fleet-health.sh at: $FLEET_HEALTH_SRC"
    log_error "Run this script from a KTPInfrastructure checkout."
    exit 1
fi

DODSERVER_HOME="/home/$DODSERVER_USER"
install -o "$DODSERVER_USER" -g "$DODSERVER_USER" -m 755 \
    "$FLEET_HEALTH_SRC" "$DODSERVER_HOME/ktp-fleet-health.sh"

# Seed /etc/ktp/fleet-health.conf only when absent — preserve operator edits
# on idempotent re-runs.
mkdir -p /etc/ktp
if [ ! -f /etc/ktp/fleet-health.conf ]; then
    if [ -f "$FLEET_HEALTH_CONF_TEMPLATE" ]; then
        install -o root -g "$DODSERVER_USER" -m 640 \
            "$FLEET_HEALTH_CONF_TEMPLATE" /etc/ktp/fleet-health.conf
        log_info "Seeded /etc/ktp/fleet-health.conf from template (edit to enable Discord posts)"
    else
        log_warn "fleet-health.conf.example not found; skipping conf seed"
    fi
else
    log_info "/etc/ktp/fleet-health.conf already present — left as-is"
fi

# Install cron entry as dodserver (idempotent — only adds if not already present).
CRON_LINE="* * * * * $DODSERVER_HOME/ktp-fleet-health.sh >/dev/null 2>&1"
EXISTING_CRON=$(crontab -u "$DODSERVER_USER" -l 2>/dev/null || true)
if echo "$EXISTING_CRON" | grep -qF "ktp-fleet-health.sh"; then
    log_info "ktp-fleet-health.sh cron entry already installed"
else
    { echo "$EXISTING_CRON"; echo "$CRON_LINE"; } \
        | grep -v '^$' \
        | crontab -u "$DODSERVER_USER" -
    log_info "Installed ktp-fleet-health.sh cron entry (every minute)"
fi

# ============================================
# 17. Co-located HLTV Setup (Optional)
# ============================================
if [ "$WITH_HLTV" = true ]; then
    # Guard: this legacy section bakes credentials into a 0.0.0.0:8087 API
    # service and HLTV configs. Refuse to run with placeholder values instead
    # of silently shipping "REDACTED_*" secrets. (The LAN path doesn't come
    # through here — lan-deploy.sh Phase 4 owns HLTV with generated keys.)
    if [ -z "${HLTV_API_KEY:-}" ]; then
        log_error "--with-hltv requires HLTV_API_KEY set in the environment"
        log_error "(the embedded API would otherwise ship a placeholder key on 0.0.0.0:8087)."
        exit 1
    fi
    # The config generator below is invoked with no arguments, so its ADMIN_PASS
    # and PROXY_PASS defaults are what actually land in the HLTV configs. Guard
    # them too — the API key alone was never the whole placeholder surface.
    if [ -z "${HLTV_ADMIN_PASS:-}" ] || [ -z "${HLTV_PROXY_PASS:-}" ]; then
        log_error "--with-hltv requires HLTV_ADMIN_PASS and HLTV_PROXY_PASS set in the environment"
        log_error "(otherwise the generated HLTV configs ship REDACTED_HLTV_* as real passwords)."
        exit 1
    fi
    log_info "Setting up co-located HLTV proxies..."

    # Install Python dependencies for HLTV API
    apt-get install -y python3-venv screen

    HLTV_HOME="/home/$DODSERVER_USER"
    HLTV_DIR="$HLTV_HOME/hltv/hlds"
    HLTV_CONFIGS="$HLTV_HOME/hltv/configs"
    HLTV_DEMOS="$HLTV_HOME/hltv/demos"

    su - "$DODSERVER_USER" -c "mkdir -p $HLTV_DIR/dod $HLTV_CONFIGS $HLTV_DEMOS"

    # Create HLTV config generator
    cat > "$HLTV_HOME/hltv/generate-hltv-configs.sh" << HLTVCFGSCRIPT
#!/bin/bash
# Generate HLTV config files for co-located HLTV instances

HLTV_DIR="$HLTV_DIR"
NUM_INSTANCES=$NUM_SERVERS
BASE_PORT=$HLTV_BASE_PORT
ADMIN_PASS=\${1:-}
PROXY_PASS=\${2:-}
if [ -z "\$ADMIN_PASS" ] || [ -z "\$PROXY_PASS" ]; then
    echo "usage: \$0 <admin_pass> <proxy_pass>" >&2
    echo "Both are required — this script used to default to REDACTED_HLTV_*," >&2
    echo "which shipped placeholders into live HLTV configs." >&2
    exit 1
fi

for i in \$(seq 1 \$NUM_INSTANCES); do
    PORT=\$((BASE_PORT + i - 1))
    GAME_PORT=\$((27015 + i - 1))
    CONFIG="$HLTV_CONFIGS/hltv-\$PORT.cfg"

    cat > "\$CONFIG" << EOF
// HLTV Instance \$i - Port \$PORT
// Connected to game server on port \$GAME_PORT

hostname "KTP HLTV \$i"
port \$PORT

// Admin access
adminpassword "\$ADMIN_PASS"

// Proxy settings
proxypassword "\$PROXY_PASS"
maxclients 32

// Recording
demodelay 30
demotimeout 60

// Performance
rate 20000
updaterate 200
cmdrate 40

// Connect to local game server
autoconnect 127.0.0.1:\$GAME_PORT
EOF
    echo "Created: \$CONFIG"
done
HLTVCFGSCRIPT
    chmod +x "$HLTV_HOME/hltv/generate-hltv-configs.sh"
    chown "$DODSERVER_USER:$DODSERVER_USER" "$HLTV_HOME/hltv/generate-hltv-configs.sh"

    # Generate default configs — pass the real secrets; the script's own
    # defaults are a hard error, not a fallback.
    su - "$DODSERVER_USER" -c "$HLTV_HOME/hltv/generate-hltv-configs.sh '$HLTV_ADMIN_PASS' '$HLTV_PROXY_PASS'"

    # Create HLTV control script (screen-based)
    cat > "$HLTV_HOME/hltv/hltv-ctl.sh" << 'HLTVCTLSCRIPT'
#!/bin/bash
# HLTV Control Script (co-located)

HLTV_DIR="$(dirname "$0")/hlds"
CONFIGS_DIR="$(dirname "$0")/configs"
ACTION=$1
INSTANCE=$2

start_instance() {
    local port=$1
    local config="$CONFIGS_DIR/hltv-$port.cfg"

    if [ ! -f "$config" ]; then
        echo "Config not found: $config"
        return 1
    fi

    cd "$HLTV_DIR"
    screen -dmS "hltv-$port" ./hltv +exec "$config"
    echo "Started HLTV on port $port"
}

stop_instance() {
    local port=$1
    screen -S "hltv-$port" -X quit 2>/dev/null
    echo "Stopped HLTV on port $port"
}

status_instance() {
    local port=$1
    if screen -list | grep -q "hltv-$port"; then
        echo "Port $port: RUNNING"
    else
        echo "Port $port: STOPPED"
    fi
}

case "$ACTION" in
    start)
        if [ -n "$INSTANCE" ]; then
            start_instance $INSTANCE
        else
            for cfg in $CONFIGS_DIR/hltv-*.cfg; do
                port=$(basename $cfg .cfg | cut -d- -f2)
                start_instance $port
                sleep 1
            done
        fi
        ;;
    stop)
        if [ -n "$INSTANCE" ]; then
            stop_instance $INSTANCE
        else
            for cfg in $CONFIGS_DIR/hltv-*.cfg; do
                port=$(basename $cfg .cfg | cut -d- -f2)
                stop_instance $port
            done
        fi
        ;;
    status)
        for cfg in $CONFIGS_DIR/hltv-*.cfg; do
            port=$(basename $cfg .cfg | cut -d- -f2)
            status_instance $port
        done
        ;;
    restart)
        $0 stop $INSTANCE
        sleep 2
        $0 start $INSTANCE
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status} [port]"
        exit 1
        ;;
esac
HLTVCTLSCRIPT
    chmod +x "$HLTV_HOME/hltv/hltv-ctl.sh"
    chown "$DODSERVER_USER:$DODSERVER_USER" "$HLTV_HOME/hltv/hltv-ctl.sh"

    # Create HLTV API (Flask app)
    python3 -m venv "$HLTV_HOME/hltv/api-venv"
    "$HLTV_HOME/hltv/api-venv/bin/pip" install flask gunicorn >/dev/null 2>&1

    cat > "$HLTV_HOME/hltv/hltv-api.py" << 'HLTVAPIPY'
#!/usr/bin/env python3
"""KTP HLTV API - Co-located Version"""

import os
import subprocess
from flask import Flask, request, jsonify

app = Flask(__name__)

import sys
API_KEY = os.environ.get('HLTV_API_KEY', '')
if not API_KEY:
    sys.exit('HLTV_API_KEY empty - refusing to start (would auth anonymous requests)')

def send_hltv_command(port, command):
    """Send command to HLTV via screen."""
    screen_name = f"hltv-{port}"
    try:
        subprocess.run(
            ['screen', '-S', screen_name, '-X', 'stuff', f'{command}\n'],
            check=True, timeout=5
        )
        return True
    except Exception:
        return False

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

@app.route('/record', methods=['POST'])
def start_recording():
    auth = request.headers.get('Authorization', '')
    if auth != f'Bearer {API_KEY}':
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.json or {}
    port = data.get('port', 27020)
    filename = data.get('filename', 'demo')
    if send_hltv_command(port, f'record {filename}'):
        return jsonify({'status': 'recording', 'filename': filename})
    return jsonify({'error': 'Failed to send command'}), 500

@app.route('/stoprecording', methods=['POST'])
def stop_recording():
    auth = request.headers.get('Authorization', '')
    if auth != f'Bearer {API_KEY}':
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.json or {}
    port = data.get('port', 27020)
    if send_hltv_command(port, 'stoprecording'):
        return jsonify({'status': 'stopped'})
    return jsonify({'error': 'Failed to send command'}), 500

@app.route('/connect', methods=['POST'])
def connect_server():
    auth = request.headers.get('Authorization', '')
    if auth != f'Bearer {API_KEY}':
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.json or {}
    port = data.get('port', 27020)
    server = data.get('server', '')
    if not server:
        return jsonify({'error': 'Server address required'}), 400
    if send_hltv_command(port, f'connect {server}'):
        return jsonify({'status': 'connecting', 'server': server})
    return jsonify({'error': 'Failed to send command'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8087)
HLTVAPIPY
    chown -R "$DODSERVER_USER:$DODSERVER_USER" "$HLTV_HOME/hltv"

    # Create systemd service for HLTV API
    cat > /etc/systemd/system/hltv-api.service << HLTVSVC
[Unit]
Description=KTP HLTV API (co-located)
After=network.target

[Service]
Type=simple
User=$DODSERVER_USER
WorkingDirectory=$HLTV_HOME/hltv
Environment="HLTV_API_KEY=$HLTV_API_KEY"
ExecStart=$HLTV_HOME/hltv/api-venv/bin/gunicorn -w 2 -b 0.0.0.0:8087 hltv-api:app
Restart=always

[Install]
WantedBy=multi-user.target
HLTVSVC

    systemctl daemon-reload
    systemctl enable hltv-api

    log_info "HLTV setup complete: $NUM_SERVERS instances (ports $HLTV_BASE_PORT-$HLTV_MAX_PORT), API on 8087"
    log_warn "HLTV binaries need to be copied manually to $HLTV_DIR"
    log_warn "Required files: hltv, hltv_i686.so, proxy.so"
fi

# ============================================
# Summary
# ============================================
echo ""
echo "========================================"
echo "Provisioning Complete!"
echo "========================================"
echo ""
echo "User created: $DODSERVER_USER"
echo "Password: $DODSERVER_PASSWORD"
echo "Timezone: $TIMEZONE"
echo "Swap: $SWAP_SIZE"
echo "Kernel: $LOWLATENCY_KERNEL (lowlatency)"
echo "Game servers: $NUM_SERVERS (ports $GAME_PORT_RANGE)"
if [ "$WITH_HLTV" = true ]; then
    echo "HLTV proxies: $NUM_SERVERS (ports $HLTV_PORT_RANGE)"
    echo "HLTV API: port 8087"
fi
echo ""
echo "Performance optimizations applied:"
echo "  - Filesystem: noatime (eliminates atime write I/O)"
echo "  - CPU governor: performance"
echo "  - C-states: ALL disabled (max_cstate=0)"
echo "  - NMI watchdog: disabled"
echo "  - UDP buffers: 25MB"
echo "  - Dirty ratio: 5% (reduced I/O stutter)"
echo "  - netdev_budget: 1200 (packet processing)"
echo "  - THP: madvise (disables khugepaged stalls)"
echo "  - THP defrag: never"
echo "  - KSM: disabled"
echo "  - Memory compaction: disabled"
echo "  - NIC offloading: disabled (GRO/LRO/TSO)"
echo "  - Mitigations: off (Spectre/Meltdown disabled for performance)"
echo "  - Conntrack bypass: game ports $GAME_PORT_RANGE"
echo "  - File descriptors: 65535"
echo "  - CPU pinning: game servers pinned to dedicated CPUs"
echo "  - Real-time scheduling: SCHED_FIFO priority 50 (auto-applied every 30s)"
echo "  - CPU isolation: isolcpus + nohz_full + rcu_nocbs (baremetals only)"
echo "  - IRQ affinity: steered to housekeeping CPUs (baremetals only)"
echo "  - fail2ban: enabled"
echo ""
echo "IMPORTANT: Reboot required to activate lowlatency kernel!"
echo ""
echo "Next steps:"
echo "  1. Reboot to activate lowlatency kernel: sudo reboot"
echo "  2. Log in as $DODSERVER_USER: su - $DODSERVER_USER"
echo "  3. Run install-linuxgsm.sh to install game servers"
echo "  4. Run clone-ktp-stack.sh to deploy KTP binaries"
if [ "$WITH_HLTV" = true ]; then
    echo "  5. Copy HLTV binaries to $HLTV_DIR (hltv, hltv_i686.so, proxy.so)"
    echo "  6. Start HLTV API: sudo systemctl start hltv-api"
    echo "  7. Start HLTV proxies: ~/hltv/hltv-ctl.sh start"
fi
echo ""
echo "========================================"
