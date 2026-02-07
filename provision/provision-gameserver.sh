#!/bin/bash
# KTP Game Server Provisioning Script
# Prepares a fresh Ubuntu 22.04 server for KTP game server hosting
#
# Usage: sudo ./provision-gameserver.sh [OPTIONS]
#
# OPTIONS:
#   -y, --yes           Non-interactive mode (accept all defaults, install Netdata)
#   --no-netdata        Skip Netdata installation (only with -y)
#   --password <pass>   Set dodserver password (default: ktp)
#
# This script:
# 1. Creates dodserver user
# 2. Sets timezone and NTP (chrony)
# 3. Configures UDP buffers and performance sysctls
# 4. Configures swap
# 5. Installs LinuxGSM dependencies (32-bit libs, steamcmd)
# 6. Configures firewall (UFW)
# 7. Optionally installs Netdata monitoring
# 8. Installs lowlatency kernel
# 9. CPU performance: governor=performance, ALL C-states disabled (max_cstate=0)
# 10. Memory optimizations: THP disabled, KSM disabled, compaction disabled
# 11. Network optimizations: GRO/LRO/TSO disabled, conntrack bypass
# 12. Dirty ratio tuning (vm.dirty_ratio=5)
# 13. Network budget tuning (netdev_budget=600)
# 14. File descriptor limits (65535)
# 14. Installs fail2ban for SSH protection

set -e

# ============================================
# Parse Arguments
# ============================================
NON_INTERACTIVE=false
INSTALL_NETDATA=true
DODSERVER_PASSWORD="ktp"

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
TIMEZONE="America/New_York"
SWAP_SIZE="2G"

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

# Check for supported Ubuntu versions (22.04 or 24.04)
if grep -q "Ubuntu 22.04\|Ubuntu 24.04" /etc/os-release 2>/dev/null; then
    UBUNTU_VERSION=$(grep VERSION_ID /etc/os-release | cut -d'"' -f2)
    log_info "Detected Ubuntu $UBUNTU_VERSION"
else
    log_warn "This script is designed for Ubuntu 22.04 or 24.04"
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
else
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

cat >> /etc/sysctl.conf << 'EOF'

# KTP Game Server UDP buffers (25MB)
net.core.rmem_max=26214400
net.core.rmem_default=26214400
net.core.wmem_max=26214400
net.core.wmem_default=26214400

# KTP Game Server Performance Tuning
kernel.nmi_watchdog = 0
net.ipv4.tcp_low_latency = 1
net.core.busy_read = 100
net.core.busy_poll = 100
net.core.netdev_max_backlog = 5000
EOF

sysctl -p

log_info "UDP buffers set to 25MB, performance sysctls applied"

# ============================================
# 5. Configure Swap
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
# 6. Install Dependencies
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
    libcurl4:i386 \
    ethtool \
    iptables

log_info "Dependencies installed"

# ============================================
# 7. Configure Firewall (UFW)
# ============================================
log_info "Configuring firewall..."

apt-get install -y ufw

ufw allow 22/tcp comment "SSH"
ufw allow 27015:27019/udp comment "DoD Game Servers"
ufw allow 27015:27019/tcp comment "DoD RCON"

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
# 8. Install Netdata (Optional)
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
# 9. Install Lowlatency Kernel
# ============================================
log_info "Installing lowlatency kernel for better game server performance..."

apt-get install -y linux-image-lowlatency linux-headers-lowlatency

# Get the installed lowlatency kernel version
LOWLATENCY_KERNEL=$(ls /boot/vmlinuz-*-lowlatency 2>/dev/null | sort -V | tail -1 | sed 's|/boot/vmlinuz-||')
if [ -n "$LOWLATENCY_KERNEL" ]; then
    log_info "Lowlatency kernel installed: $LOWLATENCY_KERNEL"

    # Fix GRUB to boot lowlatency kernel by default
    # Ubuntu 24.04+ puts lowlatency in Advanced submenu, GRUB_DEFAULT=0 boots generic
    # "1>2" means: submenu 1 (Advanced options), entry 2 (first lowlatency kernel)
    if ! grep -q 'GRUB_DEFAULT="1>2"' /etc/default/grub; then
        log_info "Configuring GRUB to boot lowlatency kernel..."
        sed -i 's/^GRUB_DEFAULT=.*/GRUB_DEFAULT="1>2"/' /etc/default/grub
        update-grub
        log_info "GRUB configured for lowlatency kernel"
    fi

    log_warn "REBOOT REQUIRED to activate lowlatency kernel!"
else
    log_warn "Lowlatency kernel installation may have failed"
fi

# ============================================
# 10. CPU Performance Optimizations
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
echo madvise > /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null || true
echo never > /sys/kernel/mm/transparent_hugepage/defrag 2>/dev/null || true
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
fi

# Apply conntrack bypass immediately
if command -v iptables &>/dev/null; then
    iptables -t raw -D PREROUTING -p udp --dport 27015:27019 -j NOTRACK 2>/dev/null || true
    iptables -t raw -D OUTPUT -p udp --sport 27015:27019 -j NOTRACK 2>/dev/null || true
    iptables -t raw -A PREROUTING -p udp --dport 27015:27019 -j NOTRACK 2>/dev/null || true
    iptables -t raw -A OUTPUT -p udp --sport 27015:27019 -j NOTRACK 2>/dev/null || true
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

# Disable Transparent Hugepages (eliminates khugepaged stalls)
echo madvise > /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null
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
fi

# Conntrack bypass for game server ports (eliminates per-packet lookup overhead)
# Only apply if iptables is available
if command -v iptables &>/dev/null; then
    # Clear any existing NOTRACK rules first to avoid duplicates
    iptables -t raw -D PREROUTING -p udp --dport 27015:27019 -j NOTRACK 2>/dev/null
    iptables -t raw -D OUTPUT -p udp --sport 27015:27019 -j NOTRACK 2>/dev/null

    # Add fresh rules
    iptables -t raw -A PREROUTING -p udp --dport 27015:27019 -j NOTRACK
    iptables -t raw -A OUTPUT -p udp --sport 27015:27019 -j NOTRACK
fi

exit 0
RCEOF
chmod +x /etc/rc.local

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
    # GTHost provider config
    if ! grep -q "intel_idle.max_cstate" /etc/default/grub.d/gth.cfg; then
        sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT="\(.*\)"/GRUB_CMDLINE_LINUX_DEFAULT="\1 intel_idle.max_cstate=0 processor.max_cstate=0"/' /etc/default/grub.d/gth.cfg
        update-grub
    fi
elif ! grep -q "intel_idle.max_cstate" /etc/default/grub; then
    sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT="\(.*\)"/GRUB_CMDLINE_LINUX_DEFAULT="\1 intel_idle.max_cstate=0 processor.max_cstate=0"/' /etc/default/grub
    update-grub
fi

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
net.core.netdev_budget = 600
net.core.netdev_budget_usecs = 4000
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
# 13. Create Server Directories
# ============================================
log_info "Creating server directories..."

su - "$DODSERVER_USER" -c 'mkdir -p ~/log ~/backups'

# ============================================
# 14. Set Process Priority
# ============================================
log_info "Configuring process priority..."

# Add to sudoers for renice and chrt without password
cat > /etc/sudoers.d/dodserver << 'EOF'
dodserver ALL=(ALL) NOPASSWD: /usr/bin/renice
dodserver ALL=(ALL) NOPASSWD: /usr/bin/chrt
EOF
chmod 440 /etc/sudoers.d/dodserver

# ============================================
# 15. Create chrt Auto-Apply Service
# ============================================
# This ensures real-time scheduling is applied to game servers
# even when LinuxGSM monitor restarts them after a crash.
log_info "Creating chrt auto-apply service..."

# Create the script that applies chrt to game servers
cat > /usr/local/bin/ktp-apply-chrt.sh << 'CHRTSCRIPT'
#!/bin/bash
# KTP Game Server Real-Time Scheduling
# Applies chrt -r 20 to all hlds_linux processes that don't already have it
#
# Run by: ktp-chrt.timer (every 30 seconds)

for pid in $(pgrep -f hlds_linux 2>/dev/null); do
    # Check current scheduling policy
    # chrt -p returns something like "pid X's current scheduling policy: SCHED_OTHER"
    # We want SCHED_RR (round-robin real-time)
    policy=$(chrt -p "$pid" 2>/dev/null | grep -o 'SCHED_[A-Z]*')

    if [ "$policy" != "SCHED_RR" ]; then
        if chrt -r -p 20 "$pid" 2>/dev/null; then
            logger -t ktp-chrt "Applied SCHED_RR priority 20 to hlds_linux PID $pid"
        fi
    fi
done
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

# Create systemd timer (runs every 30 seconds)
cat > /etc/systemd/system/ktp-chrt.timer << 'CHRTTIMER'
[Unit]
Description=Apply real-time scheduling to KTP game servers

[Timer]
OnBootSec=60
OnUnitActiveSec=30
AccuracySec=5

[Install]
WantedBy=timers.target
CHRTTIMER

# Enable and start the timer
systemctl daemon-reload
systemctl enable ktp-chrt.timer
systemctl start ktp-chrt.timer

log_info "chrt auto-apply timer enabled (runs every 30 seconds)"

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
echo ""
echo "Performance optimizations applied:"
echo "  - CPU governor: performance"
echo "  - C-states: ALL disabled (max_cstate=0)"
echo "  - NMI watchdog: disabled"
echo "  - UDP buffers: 25MB"
echo "  - Dirty ratio: 5% (reduced I/O stutter)"
echo "  - netdev_budget: 600 (packet processing)"
echo "  - THP: madvise (disables khugepaged stalls)"
echo "  - THP defrag: never"
echo "  - KSM: disabled"
echo "  - Memory compaction: disabled"
echo "  - NIC offloading: disabled (GRO/LRO/TSO)"
echo "  - Conntrack bypass: game ports 27015-27019"
echo "  - File descriptors: 65535"
echo "  - Real-time scheduling: chrt -r 20 (auto-applied every 30s)"
echo "  - fail2ban: enabled"
echo ""
echo "IMPORTANT: Reboot required to activate lowlatency kernel!"
echo ""
echo "Next steps:"
echo "  1. Reboot to activate lowlatency kernel: sudo reboot"
echo "  2. Log in as $DODSERVER_USER: su - $DODSERVER_USER"
echo "  3. Run install-linuxgsm.sh to install game servers"
echo "  4. Run clone-ktp-stack.sh to deploy KTP binaries"
echo ""
echo "========================================"
