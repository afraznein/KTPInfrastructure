#!/bin/bash
# KTP LAN Data Server Provisioning Script
# Sets up a local data server for LAN events with:
# - HLTV proxies (for spectating and recording)
# - HLTV API (for automated recording control)
# - MySQL + HLStatsX (for stats tracking)
# - FastDL (for client file downloads)
# - File Distributor (optional)
#
# Usage: sudo ./provision-lan-dataserver.sh
#
# Run on a separate machine from game servers, or a VM on the same host

set -e

# ============================================
# Configuration
# ============================================
TIMEZONE="America/New_York"
MYSQL_ROOT_PASSWORD="KTPLanRoot2026"
HLSTATSX_DB_PASSWORD="KTPLanStats2026"
HLTV_ADMIN_PASSWORD="ktplanhltvadmin"
HLTV_PROXY_PASSWORD="ktplanproxy"

# Number of HLTV instances (one per game server you want to record)
NUM_HLTV_INSTANCES=5
HLTV_BASE_PORT=27020

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
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root"
    exit 1
fi

echo "========================================"
echo "KTP LAN Data Server Provisioning"
echo "========================================"
echo ""
echo "This will set up:"
echo "  - $NUM_HLTV_INSTANCES HLTV instances (ports $HLTV_BASE_PORT-$((HLTV_BASE_PORT + NUM_HLTV_INSTANCES - 1)))"
echo "  - HLTV API (port 8087)"
echo "  - MySQL + HLStatsX"
echo "  - FastDL web server (port 80)"
echo ""
read -p "Continue? (y/n) " -n 1 -r
echo
[[ ! $REPLY =~ ^[Yy]$ ]] && exit 1

# ============================================
# 1. System Setup
# ============================================
log_info "Setting timezone to $TIMEZONE..."
timedatectl set-timezone "$TIMEZONE"
timedatectl set-local-rtc 0

log_info "Installing system packages..."
apt-get update
apt-get install -y \
    lib32gcc-s1 \
    lib32stdc++6 \
    lib32z1 \
    mysql-server \
    nginx \
    python3 \
    python3-pip \
    python3-venv \
    perl \
    libdbi-perl \
    libdbd-mysql-perl \
    libgeo-ip-perl \
    wget \
    curl \
    unzip \
    screen \
    tmux

# ============================================
# 2. Create hltvserver User
# ============================================
log_info "Creating hltvserver user..."
if ! id hltvserver &>/dev/null; then
    useradd -m -s /bin/bash hltvserver
fi

# ============================================
# 3. MySQL Setup
# ============================================
log_info "Configuring MySQL..."

# Secure MySQL installation
mysql -e "ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY '$MYSQL_ROOT_PASSWORD';"

# Create HLStatsX database and user
mysql -u root -p"$MYSQL_ROOT_PASSWORD" << EOF
CREATE DATABASE IF NOT EXISTS hlstatsx;
CREATE USER IF NOT EXISTS 'hlstatsx'@'localhost' IDENTIFIED BY '$HLSTATSX_DB_PASSWORD';
GRANT ALL PRIVILEGES ON hlstatsx.* TO 'hlstatsx'@'localhost';
FLUSH PRIVILEGES;
EOF

log_info "MySQL configured. Database: hlstatsx, User: hlstatsx"

# ============================================
# 4. HLTV Setup
# ============================================
log_info "Setting up HLTV instances..."

HLTV_HOME="/home/hltvserver"
HLTV_DIR="$HLTV_HOME/hlds"

# Create HLTV directory structure
mkdir -p "$HLTV_DIR/dod"
mkdir -p "$HLTV_DIR/configs"
mkdir -p "$HLTV_DIR/demos"
chown -R hltvserver:hltvserver "$HLTV_HOME"

# Download HLTV binaries (you'll need to provide these)
log_warn "HLTV binaries need to be copied manually to $HLTV_DIR"
log_warn "Required files: hltv, hltv_i686.so, proxy.so"

# Create HLTV config generator
cat > "$HLTV_HOME/generate-hltv-configs.sh" << 'SCRIPT'
#!/bin/bash
# Generate HLTV config files for LAN event

HLTV_DIR="/home/hltvserver/hlds"
NUM_INSTANCES=${1:-5}
BASE_PORT=${2:-27020}
ADMIN_PASS=${3:-"ktplanhltvadmin"}
PROXY_PASS=${4:-"ktplanproxy"}

for i in $(seq 1 $NUM_INSTANCES); do
    PORT=$((BASE_PORT + i - 1))
    CONFIG="$HLTV_DIR/configs/hltv-$PORT.cfg"

    cat > "$CONFIG" << EOF
// HLTV Instance $i - Port $PORT
// LAN Event Configuration

hostname "KTP LAN HLTV $i"
port $PORT

// Admin access
adminpassword "$ADMIN_PASS"

// Proxy settings
proxypassword "$PROXY_PASS"
maxclients 32

// Recording
demodelay 30
demotimeout 60

// Performance
rate 20000
updaterate 20
cmdrate 40

// LAN optimized
sv_lan 1
EOF
    echo "Created: $CONFIG"
done
SCRIPT
chmod +x "$HLTV_HOME/generate-hltv-configs.sh"
chown hltvserver:hltvserver "$HLTV_HOME/generate-hltv-configs.sh"

# Generate default configs
su - hltvserver -c "./generate-hltv-configs.sh $NUM_HLTV_INSTANCES $HLTV_BASE_PORT '$HLTV_ADMIN_PASSWORD' '$HLTV_PROXY_PASSWORD'"

# Create HLTV control script
cat > "$HLTV_HOME/hltv-ctl.sh" << 'SCRIPT'
#!/bin/bash
# HLTV Control Script for LAN

HLTV_DIR="/home/hltvserver/hlds"
ACTION=$1
INSTANCE=$2

start_instance() {
    local port=$1
    local config="$HLTV_DIR/configs/hltv-$port.cfg"

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
            for cfg in $HLTV_DIR/configs/hltv-*.cfg; do
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
            for cfg in $HLTV_DIR/configs/hltv-*.cfg; do
                port=$(basename $cfg .cfg | cut -d- -f2)
                stop_instance $port
            done
        fi
        ;;
    status)
        for cfg in $HLTV_DIR/configs/hltv-*.cfg; do
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
SCRIPT
chmod +x "$HLTV_HOME/hltv-ctl.sh"
chown hltvserver:hltvserver "$HLTV_HOME/hltv-ctl.sh"

# ============================================
# 5. HLTV API Setup
# ============================================
log_info "Setting up HLTV API..."

# Create Python virtual environment
python3 -m venv "$HLTV_HOME/hltv-api-venv"
source "$HLTV_HOME/hltv-api-venv/bin/activate"
pip install flask gunicorn
deactivate

# Copy HLTV API script (assumes it exists in the infrastructure repo)
# For LAN, we'll create a simplified version
cat > "$HLTV_HOME/hltv-api.py" << 'SCRIPT'
#!/usr/bin/env python3
"""
KTP HLTV API - LAN Version
Simple HTTP API for controlling HLTV recording
"""

import os
import subprocess
from flask import Flask, request, jsonify

app = Flask(__name__)

# Configuration
API_KEY = os.environ.get('HLTV_API_KEY', 'lan-api-key')
HLTV_DIR = '/home/hltvserver/hlds'

def send_hltv_command(port, command):
    """Send command to HLTV via screen."""
    screen_name = f"hltv-{port}"
    try:
        subprocess.run(
            ['screen', '-S', screen_name, '-X', 'stuff', f'{command}\n'],
            check=True,
            timeout=5
        )
        return True
    except Exception as e:
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
SCRIPT
chmod +x "$HLTV_HOME/hltv-api.py"
chown hltvserver:hltvserver "$HLTV_HOME/hltv-api.py"

# Create systemd service for HLTV API
cat > /etc/systemd/system/hltv-api.service << EOF
[Unit]
Description=KTP HLTV API
After=network.target

[Service]
Type=simple
User=hltvserver
WorkingDirectory=/home/hltvserver
Environment="HLTV_API_KEY=lan-api-key"
ExecStart=/home/hltvserver/hltv-api-venv/bin/gunicorn -w 2 -b 0.0.0.0:8087 hltv-api:app
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable hltv-api

# ============================================
# 6. FastDL Setup (Nginx)
# ============================================
log_info "Setting up FastDL..."

FASTDL_DIR="/var/www/fastdl"
mkdir -p "$FASTDL_DIR"

# Nginx config for FastDL
cat > /etc/nginx/sites-available/fastdl << 'EOF'
server {
    listen 80 default_server;
    server_name _;

    root /var/www/fastdl;
    index index.html;

    # FastDL - game files
    location / {
        autoindex on;
        try_files $uri $uri/ =404;
    }

    # HLTV Demos
    location /demos {
        alias /home/hltvserver/hlds/demos;
        autoindex on;
    }
}
EOF

ln -sf /etc/nginx/sites-available/fastdl /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

nginx -t && systemctl restart nginx
systemctl enable nginx

log_info "FastDL configured on port 80"

# ============================================
# 7. HLStatsX Setup (Basic)
# ============================================
log_info "HLStatsX requires manual installation..."
log_warn "Download HLStatsX Community Edition and install to /opt/hlstatsx"
log_warn "Then import the SQL schema and configure hlstats.conf"

mkdir -p /opt/hlstatsx
cat > /opt/hlstatsx/INSTALL.txt << 'EOF'
HLStatsX Installation for LAN:

1. Download HLStatsX CE from: https://github.com/NomisCZ/hlstatsx-community-edition

2. Extract to /opt/hlstatsx/

3. Import SQL schema:
   mysql -u hlstatsx -p hlstatsx < /opt/hlstatsx/sql/install.sql

4. Configure /opt/hlstatsx/scripts/hlstats.conf:
   DBHost=localhost
   DBUsername=hlstatsx
   DBPassword=<password from this script>
   DBName=hlstatsx

5. Start daemon:
   cd /opt/hlstatsx/scripts
   ./run_hlstats start

6. Configure game servers to log to this server:
   log_address_add <DATA_SERVER_IP>:27500
EOF

# ============================================
# 8. Firewall
# ============================================
log_info "Configuring firewall..."

apt-get install -y ufw

ufw allow 22/tcp comment "SSH"
ufw allow 80/tcp comment "FastDL"
ufw allow 8087/tcp comment "HLTV API"
ufw allow 27020:27029/udp comment "HLTV"
ufw allow 27500/udp comment "HLStatsX"

ufw --force enable
ufw status

# ============================================
# Summary
# ============================================
echo ""
echo "========================================"
echo "LAN Data Server Provisioning Complete!"
echo "========================================"
echo ""
echo "Services configured:"
echo "  - HLTV: Ports $HLTV_BASE_PORT-$((HLTV_BASE_PORT + NUM_HLTV_INSTANCES - 1))"
echo "  - HLTV API: Port 8087 (key: lan-api-key)"
echo "  - FastDL: Port 80"
echo "  - MySQL: localhost (hlstatsx / $HLSTATSX_DB_PASSWORD)"
echo ""
echo "Credentials:"
echo "  - MySQL root: $MYSQL_ROOT_PASSWORD"
echo "  - MySQL hlstatsx: $HLSTATSX_DB_PASSWORD"
echo "  - HLTV admin: $HLTV_ADMIN_PASSWORD"
echo ""
echo "Manual steps required:"
echo "  1. Copy HLTV binaries to $HLTV_DIR"
echo "  2. Install HLStatsX (see /opt/hlstatsx/INSTALL.txt)"
echo "  3. Copy game files to $FASTDL_DIR for FastDL"
echo ""
echo "Start services:"
echo "  - HLTV: su - hltvserver -c './hltv-ctl.sh start'"
echo "  - HLTV API: systemctl start hltv-api"
echo ""
echo "========================================"
