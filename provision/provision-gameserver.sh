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
# 9. CPU performance: governor=performance, C-states C3/C6 disabled
# 10. File descriptor limits (65535)
# 11. Installs fail2ban for SSH protection

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

if ! grep -q "Ubuntu 22.04" /etc/os-release 2>/dev/null; then
    log_warn "This script is designed for Ubuntu 22.04"
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
    libcurl4:i386

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

# Create rc.local for persistence
cat > /etc/rc.local << 'RCEOF'
#!/bin/bash
# KTP Game Server Performance - applied at boot

# Lock CPU to max frequency (performance governor)
for gov in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    echo performance > "$gov" 2>/dev/null
done

# Disable ALL C-states for lowest latency
for cpu in /sys/devices/system/cpu/cpu*/cpuidle; do
    for state in $cpu/state*/disable; do
        echo 1 > "$state" 2>/dev/null
    done
done

# NIC Performance Tuning (if baremetal with ethtool)
IFACE=$(ip route | grep default | awk '{print $5}' | head -1)
if [ -n "$IFACE" ] && command -v ethtool &>/dev/null; then
    # Increase ring buffers to max (4096) to handle burst traffic
    ethtool -G $IFACE rx 4096 tx 4096 2>/dev/null
    # Lower interrupt coalescing for lower latency
    ethtool -C $IFACE rx-usecs 1 2>/dev/null
fi

exit 0
RCEOF
chmod +x /etc/rc.local

# Enable rc-local service
systemctl enable rc-local 2>/dev/null || true

# Add C-state limit to GRUB for full persistence
if [ -f /etc/default/grub.d/gth.cfg ]; then
    # GTHost provider config
    if ! grep -q "intel_idle.max_cstate" /etc/default/grub.d/gth.cfg; then
        sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT="\(.*\)"/GRUB_CMDLINE_LINUX_DEFAULT="\1 intel_idle.max_cstate=1 processor.max_cstate=1"/' /etc/default/grub.d/gth.cfg
        update-grub
    fi
elif ! grep -q "intel_idle.max_cstate" /etc/default/grub; then
    sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT="\(.*\)"/GRUB_CMDLINE_LINUX_DEFAULT="\1 intel_idle.max_cstate=1 processor.max_cstate=1"/' /etc/default/grub
    update-grub
fi

log_info "CPU governor set to performance, deep C-states disabled"

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
echo "  - C-states C3/C6: disabled"
echo "  - NMI watchdog: disabled"
echo "  - UDP buffers: 25MB"
echo "  - File descriptors: 65535"
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
