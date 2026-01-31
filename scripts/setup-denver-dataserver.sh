#!/bin/bash
# Denver Data Server Integration Script
# Run this on the data server (74.91.112.242) as root
#
# This script:
# 1. Creates HLTV instances 27030-27034 for Denver
# 2. Adds Denver servers to FileDistributor
# 3. Adds Denver servers to HLStatsX database
# 4. Sets up SSH key access to Denver
#
# Usage: ./setup-denver-dataserver.sh

set -e

DENVER_IP="66.163.114.109"
DENVER_USER="dodserver"
DENVER_PASSWORD="ktp"
HLTV_BASE_PORT=27030  # Denver HLTV ports: 27030-27034

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo "========================================"
echo "Denver Data Server Integration"
echo "========================================"
echo ""

# ============================================
# 1. SSH Key Setup
# ============================================
log_info "Setting up SSH key access to Denver..."

SSH_KEY_PATH="/var/www/fastdl/.ssh/id_rsa"

if [ ! -f "$SSH_KEY_PATH" ]; then
    log_error "SSH key not found at $SSH_KEY_PATH"
    log_info "Creating new SSH key..."
    mkdir -p /var/www/fastdl/.ssh
    ssh-keygen -t rsa -b 4096 -f "$SSH_KEY_PATH" -N "" -C "ktp-file-distributor"
    chown -R www-data:www-data /var/www/fastdl/.ssh
fi

# Copy key to Denver
log_info "Copying SSH key to Denver (will prompt for password)..."
ssh-copy-id -i "${SSH_KEY_PATH}.pub" "${DENVER_USER}@${DENVER_IP}" || {
    log_warn "ssh-copy-id failed. Try manually:"
    echo "  cat ${SSH_KEY_PATH}.pub | ssh ${DENVER_USER}@${DENVER_IP} 'mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys'"
}

# Test connection
log_info "Testing SSH connection..."
if ssh -i "$SSH_KEY_PATH" -o BatchMode=yes -o ConnectTimeout=5 "${DENVER_USER}@${DENVER_IP}" "echo 'SSH OK'" 2>/dev/null; then
    log_info "SSH connection successful!"
else
    log_warn "SSH test failed. Key may not be set up correctly."
fi

# ============================================
# 2. HLTV Instances (27030-27034)
# ============================================
log_info "Creating HLTV instances for Denver..."

HLTV_HOME="/home/hltvserver"
HLTV_TEMPLATE="$HLTV_HOME/hltv-27020"  # Use Atlanta as template

if [ ! -d "$HLTV_TEMPLATE" ]; then
    log_error "HLTV template not found at $HLTV_TEMPLATE"
    log_info "Skipping HLTV setup - please configure manually"
else
    for i in 0 1 2 3 4; do
        HLTV_PORT=$((HLTV_BASE_PORT + i))
        GAME_PORT=$((27015 + i))
        HLTV_DIR="$HLTV_HOME/hltv-$HLTV_PORT"

        if [ -d "$HLTV_DIR" ]; then
            log_warn "HLTV instance $HLTV_PORT already exists, skipping"
            continue
        fi

        log_info "Creating HLTV instance $HLTV_PORT..."

        # Copy from template
        cp -r "$HLTV_TEMPLATE" "$HLTV_DIR"

        # Update hltv.cfg
        HLTV_CFG="$HLTV_DIR/hltv.cfg"
        if [ -f "$HLTV_CFG" ]; then
            sed -i "s/^port .*/port $HLTV_PORT/" "$HLTV_CFG"
            sed -i "s/^connect .*/connect $DENVER_IP:$GAME_PORT/" "$HLTV_CFG"
            sed -i "s/^name .*/name \"KTP HLTV - Denver $((i + 1))\"/" "$HLTV_CFG"
        fi

        # Create FIFO pipe directory
        mkdir -p "$HLTV_HOME/cmdpipes"

        # Create FIFO pipe for this instance
        PIPE_PATH="$HLTV_HOME/cmdpipes/hltv-$HLTV_PORT.pipe"
        if [ ! -p "$PIPE_PATH" ]; then
            mkfifo "$PIPE_PATH"
        fi

        chown -R hltvserver:hltvserver "$HLTV_DIR"
        chown hltvserver:hltvserver "$PIPE_PATH"

        log_info "  Created hltv-$HLTV_PORT -> Denver:$GAME_PORT"
    done

    # Enable systemd units
    log_info "Enabling HLTV systemd units..."
    for i in 0 1 2 3 4; do
        HLTV_PORT=$((HLTV_BASE_PORT + i))
        systemctl enable hltv@$HLTV_PORT 2>/dev/null || true
        systemctl start hltv@$HLTV_PORT 2>/dev/null || log_warn "Could not start hltv@$HLTV_PORT"
    done
fi

# ============================================
# 3. FileDistributor Configuration
# ============================================
log_info "Updating FileDistributor servers.json..."

SERVERS_JSON="/opt/ktp-file-distributor/servers.json"

if [ ! -f "$SERVERS_JSON" ]; then
    log_error "FileDistributor config not found at $SERVERS_JSON"
else
    # Check if Denver already in config
    if grep -q "$DENVER_IP" "$SERVERS_JSON"; then
        log_warn "Denver already in FileDistributor config"
    else
        # Backup current config
        cp "$SERVERS_JSON" "${SERVERS_JSON}.bak"

        # Add Denver entries
        # Using Python for JSON manipulation
        python3 << PYTHON_SCRIPT
import json

with open("$SERVERS_JSON", "r") as f:
    servers = json.load(f)

# Add Denver servers
for i in range(5):
    port = 27015 + i
    servers.append({
        "name": f"KTP - Denver {i + 1}",
        "host": "$DENVER_IP",
        "port": 22,
        "username": "$DENVER_USER",
        "privateKeyPath": "$SSH_KEY_PATH",
        "remoteBasePath": f"/home/$DENVER_USER/dod-{port}/serverfiles/dod",
        "enabled": True
    })

with open("$SERVERS_JSON", "w") as f:
    json.dump(servers, f, indent=2)

print(f"Added 5 Denver servers to FileDistributor config")
PYTHON_SCRIPT

        # Restart FileDistributor
        systemctl restart ktp-file-distributor 2>/dev/null || log_warn "Could not restart FileDistributor"
    fi
fi

# ============================================
# 4. HLStatsX Database
# ============================================
log_info "Adding Denver servers to HLStatsX database..."

MYSQL_USER="hlstatsx"
MYSQL_PASS="KTPStats2025!"
MYSQL_DB="hlstatsx"

# Check if servers already exist
EXISTING=$(mysql -u$MYSQL_USER -p$MYSQL_PASS $MYSQL_DB -N -e "SELECT COUNT(*) FROM hlstats_Servers WHERE address='$DENVER_IP'" 2>/dev/null || echo "0")

if [ "$EXISTING" -gt 0 ]; then
    log_warn "Denver servers already in HLStatsX database"
else
    log_info "Inserting Denver servers into HLStatsX..."

    for i in 0 1 2 3 4; do
        PORT=$((27015 + i))
        SERVER_NAME="KTP - Denver $((i + 1))"

        mysql -u$MYSQL_USER -p$MYSQL_PASS $MYSQL_DB << SQL
INSERT INTO hlstats_Servers (address, port, name, game, publicaddress, sortorder, act_players, act_map, kills, headshots, suicides, last_event)
VALUES ('$DENVER_IP', '$PORT', '$SERVER_NAME', 'dod', '$DENVER_IP:$PORT', $((20 + i)), 0, '', 0, 0, 0, NOW());
SQL
        log_info "  Added $SERVER_NAME ($DENVER_IP:$PORT)"
    done
fi

# ============================================
# Summary
# ============================================
echo ""
echo "========================================"
echo "Denver Data Server Integration Complete"
echo "========================================"
echo ""
echo "Completed:"
echo "  - SSH key access to Denver: $DENVER_IP"
echo "  - HLTV instances: 27030-27034"
echo "  - FileDistributor: Denver servers added"
echo "  - HLStatsX: Denver servers added"
echo ""
echo "Verify HLTV instances:"
echo "  systemctl status hltv@27030"
echo "  systemctl status hltv@27031"
echo "  ..."
echo ""
echo "Verify FileDistributor:"
echo "  journalctl -u ktp-file-distributor -f"
echo ""
echo "Verify HLStatsX:"
echo "  mysql -u$MYSQL_USER -p$MYSQL_PASS $MYSQL_DB -e \"SELECT name,address,port FROM hlstats_Servers WHERE address='$DENVER_IP'\""
echo ""
echo "========================================"
