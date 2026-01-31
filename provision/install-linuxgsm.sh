#!/bin/bash
# KTP LinuxGSM Installation Script
# Installs LinuxGSM and creates 5 DoD server instances
#
# Usage: ./install-linuxgsm.sh <SERVER_IP>
#
# Run as: dodserver user
#
# This script:
# 1. Downloads and installs LinuxGSM
# 2. Installs Day of Defeat via SteamCMD
# 3. Creates 5 server instances (ports 27015-27019)
# 4. Configures each instance with correct IP and ports

set -e

# ============================================
# Configuration
# ============================================
if [ -z "$1" ]; then
    echo "Usage: $0 <SERVER_IP>"
    echo "Example: $0 192.168.1.100"
    exit 1
fi

SERVER_IP="$1"
BASE_PORT=27015
NUM_INSTANCES=5
DEFAULT_MAP="dod_anzio"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

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
if [ "$EUID" -eq 0 ]; then
    log_error "Do not run this script as root. Run as 'dodserver' user."
    exit 1
fi

if [ "$(whoami)" != "dodserver" ]; then
    log_warn "This script should run as 'dodserver' user"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    [[ ! $REPLY =~ ^[Yy]$ ]] && exit 1
fi

echo "========================================"
echo "KTP LinuxGSM Installation"
echo "========================================"
echo "Server IP: $SERVER_IP"
echo "Instances: $NUM_INSTANCES (ports $BASE_PORT-$((BASE_PORT + NUM_INSTANCES - 1)))"
echo ""

# ============================================
# 1. Install First Instance (dod-27015)
# ============================================
FIRST_DIR="$HOME/dod-$BASE_PORT"

if [ -d "$FIRST_DIR" ]; then
    log_warn "Directory $FIRST_DIR already exists"
    read -p "Continue with existing installation? (y/n) " -n 1 -r
    echo
    [[ ! $REPLY =~ ^[Yy]$ ]] && exit 1
else
    log_info "Creating first instance at $FIRST_DIR..."

    mkdir -p "$FIRST_DIR"
    cd "$FIRST_DIR"

    # Download LinuxGSM
    log_info "Downloading LinuxGSM..."
    wget -O linuxgsm.sh https://linuxgsm.sh
    chmod +x linuxgsm.sh

    # Install DoD server
    log_info "Installing LinuxGSM DoD server..."
    ./linuxgsm.sh dodserver

    # Install game files (this downloads from Steam)
    log_info "Installing Day of Defeat via SteamCMD (this may take a while)..."
    ./dodserver auto-install

    log_info "First instance installed at $FIRST_DIR"
fi

# ============================================
# 2. Configure First Instance
# ============================================
log_info "Configuring first instance..."

# Create common.cfg
mkdir -p "$FIRST_DIR/lgsm/config-lgsm/dodserver"
cat > "$FIRST_DIR/lgsm/config-lgsm/dodserver/common.cfg" << EOF
# KTP Common Configuration
# Shared by all server instances

# Game settings
gamename="Day of Defeat"
gameworld="dod"
appid="30"
servercfg="dodserver.cfg"
defaultmap="$DEFAULT_MAP"
maxplayers="13"

# Performance
pingboost="2"
EOF

# Create instance-specific config
cat > "$FIRST_DIR/lgsm/config-lgsm/dodserver/dodserver.cfg" << EOF
# KTP Server Instance 1 Configuration

# Network
port="$BASE_PORT"
clientport="$((BASE_PORT - 10))"
ip="$SERVER_IP"

# Startup parameters
startparameters="-game dod -strictportbind +ip \${ip} -port \${port} +clientport \${clientport} +map \${defaultmap} +servercfgfile \${servercfg} -maxplayers 13 -pingboost 2"
EOF

log_info "First instance configured"

# ============================================
# 3. Clone Additional Instances
# ============================================
for i in $(seq 2 $NUM_INSTANCES); do
    PORT=$((BASE_PORT + i - 1))
    INSTANCE_DIR="$HOME/dod-$PORT"
    EXEC_NAME="dodserver$i"

    if [ -d "$INSTANCE_DIR" ]; then
        log_warn "Instance $INSTANCE_DIR already exists, skipping"
        continue
    fi

    log_info "Creating instance $i at $INSTANCE_DIR (port $PORT)..."

    # Copy from first instance
    cp -r "$FIRST_DIR" "$INSTANCE_DIR"

    # Rename executable
    mv "$INSTANCE_DIR/dodserver" "$INSTANCE_DIR/$EXEC_NAME"

    # Create instance-specific config
    # CRITICAL: Config must be in dodserver/ folder, NOT dodserver$i/
    cat > "$INSTANCE_DIR/lgsm/config-lgsm/dodserver/$EXEC_NAME.cfg" << EOF
# KTP Server Instance $i Configuration

# Network
port="$PORT"
clientport="$((PORT - 10))"
ip="$SERVER_IP"

# Startup parameters
startparameters="-game dod -strictportbind +ip \${ip} -port \${port} +clientport \${clientport} +map \${defaultmap} +servercfgfile \${servercfg} -maxplayers 13 -pingboost 2"
EOF

    log_info "Instance $i created (port $PORT)"
done

# ============================================
# 4. Create Management Scripts
# ============================================
log_info "Creating management scripts..."

# restart-all-servers.sh
cat > "$HOME/restart-all-servers.sh" << 'EOF'
#!/bin/bash
# Restart all KTP game server instances
# WARNING: This will disconnect all players!

set -e

echo "========================================"
echo "KTP Server Restart"
echo "========================================"
echo ""

# Stop all servers
echo "Stopping servers..."
for i in 1 2 3 4 5; do
    port=$((27014 + i))
    name="dodserver"
    [ $i -gt 1 ] && name="dodserver$i"

    echo "  Stopping $name (port $port)..."
    ~/dod-$port/$name stop 2>/dev/null || true
done

# Wait for clean shutdown
echo "Waiting for shutdown..."
sleep 5

# Start all servers
echo "Starting servers..."
for i in 1 2 3 4 5; do
    port=$((27014 + i))
    name="dodserver"
    [ $i -gt 1 ] && name="dodserver$i"

    echo "  Starting $name (port $port)..."
    ~/dod-$port/$name start
    sleep 2
done

# Verify
echo ""
echo "Verifying servers..."
sleep 5

running=0
for i in 1 2 3 4 5; do
    port=$((27014 + i))
    if pgrep -f "hlds_linux.*-port $port" > /dev/null; then
        echo "  Port $port: RUNNING"
        ((running++))
    else
        echo "  Port $port: NOT RUNNING"
    fi
done

echo ""
echo "$running of 5 servers running"
echo "========================================"
EOF
chmod +x "$HOME/restart-all-servers.sh"

# status.sh
cat > "$HOME/status.sh" << 'EOF'
#!/bin/bash
# Check status of all KTP game servers

echo "KTP Server Status"
echo "================="
echo ""

for i in 1 2 3 4 5; do
    port=$((27014 + i))
    name="dodserver"
    [ $i -gt 1 ] && name="dodserver$i"

    pid=$(pgrep -f "hlds_linux.*-port $port" 2>/dev/null || true)

    if [ -n "$pid" ]; then
        uptime=$(ps -o etime= -p $pid 2>/dev/null | tr -d ' ')
        echo "Port $port: RUNNING (PID: $pid, Uptime: $uptime)"
    else
        echo "Port $port: STOPPED"
    fi
done
EOF
chmod +x "$HOME/status.sh"

log_info "Management scripts created"

# ============================================
# 5. Set Up Cron Jobs
# ============================================
log_info "Setting up cron jobs..."

# Create crontab entries
(crontab -l 2>/dev/null || true; cat << 'EOF'
# KTP Server Monitor - check every minute
* * * * * ~/dod-27015/dodserver monitor > /dev/null 2>&1
* * * * * ~/dod-27016/dodserver2 monitor > /dev/null 2>&1
* * * * * ~/dod-27017/dodserver3 monitor > /dev/null 2>&1
* * * * * ~/dod-27018/dodserver4 monitor > /dev/null 2>&1
* * * * * ~/dod-27019/dodserver5 monitor > /dev/null 2>&1
EOF
) | crontab -

log_info "Cron jobs configured"

# ============================================
# Summary
# ============================================
echo ""
echo "========================================"
echo "LinuxGSM Installation Complete!"
echo "========================================"
echo ""
echo "Instances created:"
for i in $(seq 1 $NUM_INSTANCES); do
    PORT=$((BASE_PORT + i - 1))
    echo "  ~/dod-$PORT (port $PORT)"
done
echo ""
echo "Management scripts:"
echo "  ~/restart-all-servers.sh - Restart all servers"
echo "  ~/status.sh - Check server status"
echo ""
echo "Next steps:"
echo "  1. Run clone-ktp-stack.sh to deploy KTP binaries"
echo "  2. Start servers: ~/restart-all-servers.sh"
echo ""
echo "========================================"
