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
# All values below are env-overridable so the LAN orchestrator (and other
# automation) can pass per-deployment values without editing the script.
# For passwords, unset/empty env -> auto-generate a random 32-char value.
# This guarantees fresh secrets per deployment even if the operator forgets
# to set them, and avoids the prior committed-default footgun.
TIMEZONE="${TIMEZONE:-America/New_York}"

gen_pw() { tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32; }

MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD:-$(gen_pw)}"
HLSTATSX_DB_PASSWORD="${HLSTATSX_DB_PASSWORD:-$(gen_pw)}"
HLTV_ADMIN_PASSWORD="${HLTV_ADMIN_PASSWORD:-$(gen_pw)}"
HLTV_PROXY_PASSWORD="${HLTV_PROXY_PASSWORD:-$(gen_pw)}"

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
# YES=1 skips the prompt — used by lan-deploy.sh orchestrator.
if [ "${YES:-0}" != "1" ]; then
    read -p "Continue? (y/n) " -n 1 -r
    echo
    [[ ! $REPLY =~ ^[Yy]$ ]] && exit 1
fi

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

# Stage HLTV binaries if a pre-staged directory is provided. The directory
# should mirror the destination /home/hltvserver/hlds/ layout — at minimum
# hlds_linux + the HLTV/HLDS .so libs + dod/ game data. The companion
# scripts/package-hltv-bundle.sh produces a clean tarball from an existing
# data-server install for transfer to the LAN box. Empty path = manual
# step (original behavior preserved for cloud deployments).
if [ -n "${HLTV_BINARIES_PATH:-}" ]; then
    if [ ! -d "$HLTV_BINARIES_PATH" ]; then
        log_error "HLTV_BINARIES_PATH set but not a directory: $HLTV_BINARIES_PATH"
        exit 1
    fi
    if [ ! -f "$HLTV_BINARIES_PATH/hlds_linux" ]; then
        log_error "HLTV_BINARIES_PATH does not contain hlds_linux: $HLTV_BINARIES_PATH"
        log_error "Expected a directory mirroring the production /home/hltvserver/hlds/ layout."
        log_error "See scripts/package-hltv-bundle.sh for producing the bundle."
        exit 1
    fi
    log_info "Staging HLTV binaries from $HLTV_BINARIES_PATH (this may take a minute)..."
    cp -r "$HLTV_BINARIES_PATH"/. "$HLTV_DIR/"
    chown -R hltvserver:hltvserver "$HLTV_HOME"
    log_info "HLTV binaries staged ($(du -sh "$HLTV_DIR" 2>/dev/null | awk '{print $1}'))"
else
    log_warn "HLTV_BINARIES_PATH not set — HLTV binaries must be copied manually to $HLTV_DIR"
    log_warn "Use scripts/package-hltv-bundle.sh on an existing data server to produce a tarball."
fi

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

# Stage FastDL game files if a pre-staged directory is provided. The
# directory contents are copied into /var/www/fastdl/dod/ (note: clients
# request URLs under dod/ because the engine appends the gamedir before
# asset paths — see CLAUDE.md FastDL section for the 2026-05-01 footgun).
# Empty path = manual copy after install (original behavior).
if [ -n "${FASTDL_FILES_PATH:-}" ]; then
    if [ ! -d "$FASTDL_FILES_PATH" ]; then
        log_error "FASTDL_FILES_PATH set but not a directory: $FASTDL_FILES_PATH"
        exit 1
    fi
    log_info "Staging FastDL files from $FASTDL_FILES_PATH..."
    mkdir -p "$FASTDL_DIR/dod"
    cp -r "$FASTDL_FILES_PATH"/. "$FASTDL_DIR/dod/"
    chown -R www-data:www-data "$FASTDL_DIR"
    log_info "FastDL files staged at $FASTDL_DIR/dod ($(du -sh "$FASTDL_DIR/dod" 2>/dev/null | awk '{print $1}'))"
else
    log_warn "FASTDL_FILES_PATH not set — copy game files to $FASTDL_DIR/dod/ manually."
    log_warn "Note: assets MUST be under the dod/ subdirectory (engine prepends gamedir to URLs)."
fi

# ============================================
# 7. HLStatsX Setup
# ============================================
# Two paths:
#  - HLSTATSX_SOURCE_PATH set:  install fully (deploy scripts/sql, import
#    schemas, write hlstats.conf with the generated DB password, enable
#    hlstatsx.service systemd unit). Produce the bundle with
#    scripts/package-hlstatsx-bundle.sh on a current data server.
#  - Unset: write INSTALL.txt with the manual recovery procedure (preserves
#    the original behavior for cloud invocations of this script).
mkdir -p /opt/hlstatsx

if [ -n "${HLSTATSX_SOURCE_PATH:-}" ]; then
    log_info "Installing HLStatsX from $HLSTATSX_SOURCE_PATH..."

    if [ ! -d "$HLSTATSX_SOURCE_PATH" ]; then
        log_error "HLSTATSX_SOURCE_PATH not a directory: $HLSTATSX_SOURCE_PATH"
        exit 1
    fi
    if [ ! -f "$HLSTATSX_SOURCE_PATH/scripts/hlstats.pl" ]; then
        log_error "HLSTATSX_SOURCE_PATH missing scripts/hlstats.pl"
        exit 1
    fi
    if [ ! -f "$HLSTATSX_SOURCE_PATH/sql/install.sql" ]; then
        log_error "HLSTATSX_SOURCE_PATH missing sql/install.sql (base schema)."
        log_error "Produce the bundle with scripts/package-hlstatsx-bundle.sh on a current data server."
        exit 1
    fi

    # Deploy scripts + sql
    mkdir -p /opt/hlstatsx/scripts /opt/hlstatsx/sql
    cp -r "$HLSTATSX_SOURCE_PATH/scripts/." /opt/hlstatsx/scripts/
    cp -r "$HLSTATSX_SOURCE_PATH/sql/." /opt/hlstatsx/sql/

    # Schema import. install.sql is the upstream HLStatsX base; ktp_schema.sql
    # + any migrate_*.sql are KTP additions on top. Skip if the canary
    # hlstats_Actions table already exists (idempotent re-run).
    SCHEMA_LOADED=$(mysql -u root -p"$MYSQL_ROOT_PASSWORD" hlstatsx -sN -e \
        "SHOW TABLES LIKE 'hlstats_Actions';" 2>/dev/null || true)
    if [ -z "$SCHEMA_LOADED" ]; then
        log_info "Importing base schema (install.sql)..."
        mysql -u root -p"$MYSQL_ROOT_PASSWORD" hlstatsx < /opt/hlstatsx/sql/install.sql

        if [ -f /opt/hlstatsx/sql/ktp_schema.sql ]; then
            log_info "Importing KTP schema additions (ktp_schema.sql)..."
            mysql -u root -p"$MYSQL_ROOT_PASSWORD" hlstatsx < /opt/hlstatsx/sql/ktp_schema.sql
        fi
        # Apply migrate_*.sql in lexicographic order (matches numbered prefix
        # convention: migrate_001_*, migrate_002_*, ...).
        for migration in /opt/hlstatsx/sql/migrate_*.sql; do
            [ -f "$migration" ] || continue
            log_info "  applying $(basename "$migration")"
            mysql -u root -p"$MYSQL_ROOT_PASSWORD" hlstatsx < "$migration"
        done
    else
        log_info "HLStatsX base schema already present — skipping import"
    fi

    # hlstats.conf — daemon reads this for DB connection params at startup.
    cat > /opt/hlstatsx/scripts/hlstats.conf <<HLSTATSCONF
# KTP HLStatsX Configuration (generated $(date -Iseconds))
DBHost "localhost"
DBUsername "hlstatsx"
DBPassword "$HLSTATSX_DB_PASSWORD"
DBName "hlstatsx"
BindIP ""
Port 27500
DebugLevel 1
EventQueueSize 10
CpanelHack 0
HLSTATSCONF
    chown root:root /opt/hlstatsx/scripts/hlstats.conf
    chmod 640 /opt/hlstatsx/scripts/hlstats.conf

    # systemd unit — matches the production hlstatsx.service on the data
    # server but without the ktp-systemd-alert OnFailure drop-in (LAN has no
    # Discord relay by default).
    cat > /etc/systemd/system/hlstatsx.service <<HLSTATSSVC
[Unit]
Description=KTP HLStatsX Daemon
After=mysql.service network.target

[Service]
Type=simple
WorkingDirectory=/opt/hlstatsx/scripts
ExecStart=/usr/bin/perl /opt/hlstatsx/scripts/hlstats.pl --db-host=localhost --db-name=hlstatsx --db-username=hlstatsx --db-password=$HLSTATSX_DB_PASSWORD --port=27500
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
HLSTATSSVC
    # Service file has the password baked into ExecStart args — same exposure
    # as the production setup; lock to root-only just in case.
    chmod 600 /etc/systemd/system/hlstatsx.service

    systemctl daemon-reload
    systemctl enable hlstatsx.service
    systemctl start hlstatsx.service
    log_info "HLStatsX installed and started (UDP port 27500)"
else
    log_warn "HLSTATSX_SOURCE_PATH not set — leaving HLStatsX setup manual."
    log_warn "Use scripts/package-hlstatsx-bundle.sh on an existing data server to produce a bundle."
    cat > /opt/hlstatsx/INSTALL.txt <<'EOF'
HLStatsX Installation for LAN (manual fallback):

This file is generated when HLSTATSX_SOURCE_PATH was not set during
provisioning. For automated install, set HLSTATSX_SOURCE_PATH and re-run.

Manual recovery:
  1. On a current data server, run:
     sudo scripts/package-hlstatsx-bundle.sh

  2. Transfer hlstatsx-bundle-YYYYMMDD.tar.gz to this host.

  3. Extract:
       mkdir -p /tmp/hlstatsx-staging
       tar -xzf hlstatsx-bundle-*.tar.gz -C /tmp/hlstatsx-staging

  4. Re-run with the path set:
       HLSTATSX_SOURCE_PATH=/tmp/hlstatsx-staging \
         bash provision-lan-dataserver.sh

     OR set HLSTATSX_SOURCE_PATH in lan-deploy.conf and re-run lan-deploy.sh.
     The script will import the base schema + KTP migrations, generate
     /opt/hlstatsx/scripts/hlstats.conf, and enable hlstatsx.service.
EOF
fi

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
# Persist credentials so the operator can retrieve them after the install
# (auto-generated random passwords would otherwise only exist in this stdout).
CREDS_FILE=/root/ktp-dataserver-credentials.txt
umask 077
cat > "$CREDS_FILE" <<CREDS
KTP LAN dataserver credentials (generated $(date -Iseconds))
MYSQL_ROOT_PASSWORD=$MYSQL_ROOT_PASSWORD
HLSTATSX_DB_PASSWORD=$HLSTATSX_DB_PASSWORD
HLTV_ADMIN_PASSWORD=$HLTV_ADMIN_PASSWORD
HLTV_PROXY_PASSWORD=$HLTV_PROXY_PASSWORD
CREDS
chmod 600 "$CREDS_FILE"

echo "Credentials:"
echo "  - MySQL root: $MYSQL_ROOT_PASSWORD"
echo "  - MySQL hlstatsx: $HLSTATSX_DB_PASSWORD"
echo "  - HLTV admin: $HLTV_ADMIN_PASSWORD"
echo "  - HLTV proxy: $HLTV_PROXY_PASSWORD"
echo ""
echo "Credentials saved to: $CREDS_FILE (root-only, mode 0600)"
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
