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

# Bounded-producer form is pipefail-safe (tr exits on EOF instead of SIGPIPE).
# This script is currently `set -e` without pipefail, but lan-deploy.sh IS
# pipefail and got bitten by the naive form — keep both scripts on the safe one.
gen_pw() { head -c 512 /dev/urandom | tr -dc 'A-Za-z0-9' | head -c 32; }

# Re-run safety: a previous run's generated passwords are already APPLIED
# (MySQL root, HLTV cfgs), so regenerating fresh ones on a re-run with empty
# env would (a) fail the no-password root ALTER against an already-passworded
# MySQL and (b) overwrite the only record of the working values. Source the
# previous credentials file as defaults FIRST; env still wins over it.
CREDS_FILE=/root/ktp-dataserver-credentials.txt
if [ -f "$CREDS_FILE" ]; then
    while IFS='=' read -r k v; do
        case "$k" in
            MYSQL_ROOT_PASSWORD|HLSTATSX_DB_PASSWORD|HLTV_ADMIN_PASSWORD|HLTV_PROXY_PASSWORD|HLTV_API_KEY)
                # env (if set+nonempty) beats file; file beats fresh generation
                eval "current=\${$k:-}"
                [ -z "$current" ] && eval "$k=\$v"
                ;;
        esac
    done < "$CREDS_FILE"
fi

MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD:-$(gen_pw)}"
HLSTATSX_DB_PASSWORD="${HLSTATSX_DB_PASSWORD:-$(gen_pw)}"
HLTV_ADMIN_PASSWORD="${HLTV_ADMIN_PASSWORD:-$(gen_pw)}"
HLTV_PROXY_PASSWORD="${HLTV_PROXY_PASSWORD:-$(gen_pw)}"
# HLTV control API key — must match hltv_api_key in every game instance's
# hltv_recorder.ini (lan-deploy.sh plumbs the same value to both sides).
HLTV_API_KEY="${HLTV_API_KEY:-$(gen_pw)}"

# Number of HLTV instances (one per game server) + base port. Env-overridable so
# the LAN orchestrator can match the game-server count/ports — e.g. 6 servers on
# 27015-27020 need HLTV at 27021-27026, NOT the old 5/27020 default which both
# undercounts and collides with game port 27020.
NUM_HLTV_INSTANCES="${NUM_HLTV_INSTANCES:-5}"
HLTV_BASE_PORT="${HLTV_BASE_PORT:-27020}"

# Game-server pairing for the generated HLTV configs (KTPHLTVRecorder 1.7.0
# always-on architecture: each proxy autoconnects to its game server and
# records continuously). Empty GAME_SERVER_IP = configs are generated with
# the connect line commented (operator fills in later).
GAME_SERVER_IP="${GAME_SERVER_IP:-}"
GAME_BASE_PORT="${GAME_BASE_PORT:-27015}"
GAME_SV_PASSWORD="${GAME_SV_PASSWORD:-}"
HLTV_NAME_PREFIX="${HLTV_NAME_PREFIX:-KTP LAN}"

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

# Persist credentials NOW, before any DB/service work. The root MySQL password
# gets applied early (ALTER USER), so if a later step fails mid-run the operator
# would otherwise be locked out with no record of it. Written again at the end
# with the same values (idempotent); this early copy is the safety net.
umask 077
cat > "$CREDS_FILE" <<CREDS
KTP LAN dataserver credentials (generated $(date -Iseconds))
MYSQL_ROOT_PASSWORD=$MYSQL_ROOT_PASSWORD
HLSTATSX_DB_PASSWORD=$HLSTATSX_DB_PASSWORD
HLTV_ADMIN_PASSWORD=$HLTV_ADMIN_PASSWORD
HLTV_PROXY_PASSWORD=$HLTV_PROXY_PASSWORD
HLTV_API_KEY=$HLTV_API_KEY
CREDS
chmod 600 "$CREDS_FILE"

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
    libsyntax-keyword-try-perl \
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

# Use the server's default authentication plugin (caching_sha2_password on
# MySQL 8.x). It works for root over the local socket and for HLStatsX's Perl
# DBD::mysql over the unix socket (verified). We deliberately do NOT use
# mysql_native_password: 8.4 ships it DISABLED (and re-enabling it via my.cnf is
# unreliable), and 9.x removes it entirely. Default auth is portable across the
# cloud data server (8.0) and this LAN box (8.4).
# Fresh installs authenticate root via auth_socket, so this first ALTER runs as
# the OS root over the socket with no password; everything after uses -p.
mysql -e "ALTER USER 'root'@'localhost' IDENTIFIED BY '$MYSQL_ROOT_PASSWORD';"

# Create HLStatsX database and user. ALTER after CREATE makes a re-run reset the
# password to the current generated value (idempotent).
mysql -u root -p"$MYSQL_ROOT_PASSWORD" << EOF
CREATE DATABASE IF NOT EXISTS hlstatsx;
CREATE USER IF NOT EXISTS 'hlstatsx'@'localhost' IDENTIFIED BY '$HLSTATSX_DB_PASSWORD';
ALTER USER 'hlstatsx'@'localhost' IDENTIFIED BY '$HLSTATSX_DB_PASSWORD';
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

# Create HLTV config generator — KTPHLTVRecorder 1.7.0 always-on architecture
# (mirrors the production configs on the cloud data server): each proxy
# autoconnects to its paired game server and records CONTINUOUSLY via a
# `record auto_lanN` cfg line. The plugin never starts/stops recording — it
# only health-checks GET /hltv/<port>/state and drives /restart.
cat > "$HLTV_HOME/generate-hltv-configs.sh" << 'SCRIPT'
#!/bin/bash
# Generate KTPHLTVRecorder-1.7.0-style HLTV configs (always-on recording).
# Env-driven: NUM_INSTANCES BASE_PORT ADMIN_PASS PROXY_PASS
#             GAME_IP GAME_BASE_PORT GAME_SV_PASSWORD NAME_PREFIX
# Overwrites existing hltv-<port>.cfg — this generator is the source of truth.

HLTV_DIR="/home/hltvserver/hlds"
NUM_INSTANCES=${NUM_INSTANCES:-5}
BASE_PORT=${BASE_PORT:-27020}
ADMIN_PASS=${ADMIN_PASS:?ADMIN_PASS required}
PROXY_PASS=${PROXY_PASS:?PROXY_PASS required}
GAME_IP=${GAME_IP:-}
GAME_BASE_PORT=${GAME_BASE_PORT:-27015}
GAME_SV_PASSWORD=${GAME_SV_PASSWORD:-}
NAME_PREFIX=${NAME_PREFIX:-KTP LAN}

mkdir -p "$HLTV_DIR/configs"
for i in $(seq 1 "$NUM_INSTANCES"); do
    PORT=$((BASE_PORT + i - 1))
    GPORT=$((GAME_BASE_PORT + i - 1))
    CONFIG="$HLTV_DIR/configs/hltv-$PORT.cfg"

    if [ -n "$GAME_IP" ]; then
        CONNECT_BLOCK="serverpassword \"$GAME_SV_PASSWORD\"
connect \"$GAME_IP:$GPORT\""
    else
        CONNECT_BLOCK="// GAME_IP was unset at generation — fill in and restart:
// serverpassword \"<sv_password>\"
// connect \"<game_ip>:$GPORT\""
    fi

    cat > "$CONFIG" << EOF
// HLTV Instance $i (port $PORT) — KTPHLTVRecorder 1.7.0 always-on profile.
// Autoconnects to game port $GPORT and records continuously; demos accumulate
// as auto_lan${i}*.dem under the HLTV game dir. Regenerate with
// ~/generate-hltv-configs.sh (env-driven; overwrites this file).

name "$NAME_PREFIX $i - HLTV"
hostname "$NAME_PREFIX $i - HLTV"
port $PORT
maxclients 32
delay 60
rate 100000
adminpassword "$ADMIN_PASS"
proxypassword "$PROXY_PASS"
nomaster 1
autoretry 1

$CONNECT_BLOCK

// Always-on recording (KTPHLTVRecorder 1.7.0 architecture)
record auto_lan$i
EOF
    echo "Created: $CONFIG"
done
SCRIPT
chmod +x "$HLTV_HOME/generate-hltv-configs.sh"
chown hltvserver:hltvserver "$HLTV_HOME/generate-hltv-configs.sh"

# Clear any per-instance configs the binaries bundle dragged in from the source
# data server (it ships 25 prod hltv-*.cfg for 27020-27044). We regenerate the
# exact LAN set below; leaving the prod ones would start extra/duplicate proxies.
rm -f "$HLTV_DIR/configs"/hltv-*.cfg "$HLTV_DIR/configs"/hltv-*.cfg.bak

# Generate configs (env-driven; su -l resets env so pass explicitly, %q-quoted)
GEN_ENV=$(printf 'NUM_INSTANCES=%q BASE_PORT=%q ADMIN_PASS=%q PROXY_PASS=%q GAME_IP=%q GAME_BASE_PORT=%q GAME_SV_PASSWORD=%q NAME_PREFIX=%q' \
    "$NUM_HLTV_INSTANCES" "$HLTV_BASE_PORT" "$HLTV_ADMIN_PASSWORD" "$HLTV_PROXY_PASSWORD" \
    "$GAME_SERVER_IP" "$GAME_BASE_PORT" "$GAME_SV_PASSWORD" "$HLTV_NAME_PREFIX")
su - hltvserver -c "$GEN_ENV ./generate-hltv-configs.sh"
if [ -z "$GAME_SERVER_IP" ]; then
    log_warn "GAME_SERVER_IP unset — HLTV configs generated WITHOUT connect lines (proxies will idle)."
    log_warn "Fill in the connect/serverpassword lines in $HLTV_DIR/configs/hltv-*.cfg and restart."
fi

# HLTV runtime — SAME shape as the production data server: a systemd
# hltv@<port> template running hltv-wrapper.sh, which feeds a FIFO cmdpipe to
# HLTV stdin. This is load-bearing for the 1.7.0 plugin architecture: the
# API's GET /state scans `journalctl -u hltv@<port>` (needs systemd, not
# screen) and pokes the cmdpipe for a fresh status line. The pre-2026-07-07
# screen-based runtime could not support /state at all.
mkdir -p "$HLTV_HOME/cmdpipes"
chown hltvserver:hltvserver "$HLTV_HOME/cmdpipes"

cat > "$HLTV_HOME/hltv-wrapper.sh" << 'SCRIPT'
#!/bin/bash
# HLTV Wrapper Script - enables remote command input via FIFO pipe.
# Usage: hltv-wrapper.sh <port>   (invoked by hltv@<port>.service)

PORT=$1
PIPE="/home/hltvserver/cmdpipes/hltv-${PORT}.pipe"
HLTV="/home/hltvserver/hlds/hltv"
CONFIG="configs/hltv-${PORT}.cfg"

# A stale REGULAR file at the pipe path would make mkfifo fail and tail -f
# follow a plain file — commands would silently never reach HLTV.
if [ -e "$PIPE" ] && [ ! -p "$PIPE" ]; then rm -f "$PIPE"; fi
[ -p "$PIPE" ] || mkfifo "$PIPE"

# tail -f keeps the pipe open and feeds commands to HLTV stdin.
# Filter the RunFrame time-difference spam out of the journal.
exec tail -f "$PIPE" | exec "$HLTV" -game dod -port "$PORT" +exec "$CONFIG" 2>&1 | grep -v --line-buffered 'WARNING! System::RunFrame: system time difference'
SCRIPT
chmod +x "$HLTV_HOME/hltv-wrapper.sh"
chown hltvserver:hltvserver "$HLTV_HOME/hltv-wrapper.sh"

cat > /etc/systemd/system/hltv@.service << 'EOF'
[Unit]
Description=KTP HLTV Instance %i
After=network.target

[Service]
Type=simple
User=hltvserver
Group=hltvserver
WorkingDirectory=/home/hltvserver/hlds
Environment="LD_LIBRARY_PATH=/home/hltvserver/hlds"
ExecStart=/home/hltvserver/hltv-wrapper.sh %i
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload

# hltv-ctl.sh kept as the operator-facing control verb, now wrapping systemd
# (run as root — systemctl controls the units; journald owns the logs).
cat > "$HLTV_HOME/hltv-ctl.sh" << 'SCRIPT'
#!/bin/bash
# HLTV control for LAN — wraps the systemd hltv@<port> template.
# Run as root. Usage: hltv-ctl.sh {start|stop|restart|status} [port]

HLTV_DIR="/home/hltvserver/hlds"
ACTION=$1
INSTANCE=$2

if [ "$EUID" -ne 0 ]; then
    echo "hltv-ctl.sh wraps systemctl — run as root (sudo $0 $*)" >&2
    exit 1
fi

ports() {
    if [ -n "$INSTANCE" ]; then
        echo "$INSTANCE"
    else
        for cfg in "$HLTV_DIR"/configs/hltv-*.cfg; do
            [ -f "$cfg" ] || continue
            basename "$cfg" .cfg | cut -d- -f2
        done
    fi
}

case "$ACTION" in
    start|stop|restart)
        for port in $(ports); do
            systemctl "$ACTION" "hltv@$port"
            echo "$ACTION hltv@$port"
        done
        ;;
    status)
        for port in $(ports); do
            state=$(systemctl is-active "hltv@$port" 2>/dev/null)
            echo "Port $port: ${state:-unknown}"
        done
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status} [port]"
        exit 1
        ;;
esac
SCRIPT
chmod +x "$HLTV_HOME/hltv-ctl.sh"
chown hltvserver:hltvserver "$HLTV_HOME/hltv-ctl.sh"

# Enable + start the instances now when binaries are staged; otherwise just
# enable so they come up once the operator copies binaries in and starts them.
for i in $(seq 1 "$NUM_HLTV_INSTANCES"); do
    port=$((HLTV_BASE_PORT + i - 1))
    systemctl enable "hltv@$port" >/dev/null 2>&1 || true
    if [ -x "$HLTV_DIR/hltv" ]; then
        systemctl restart "hltv@$port"
        log_info "hltv@$port enabled + started"
    else
        log_warn "hltv@$port enabled but NOT started (no hltv binary at $HLTV_DIR/hltv yet)"
    fi
done

# ============================================
# 5. HLTV API Setup
# ============================================
# Ported from the production data server's hltv-api.py v2.2 (stdlib-only — no
# flask/gunicorn venv needed) with LAN parameterization. Serves exactly what
# KTPHLTVRecorder 1.7.0 calls: GET /hltv/<port>/state (X-Auth-Key auth,
# journalctl-backed recording state) + POST /hltv/<port>/restart
# (.hltvrestart) + POST /hltv/<port>/command (FIFO passthrough) + GET /health.
log_info "Setting up HLTV API (production v2.2 shape, stdlib)..."

cat > "$HLTV_HOME/hltv-api.py" << 'SCRIPT'
#!/usr/bin/env python3
"""
KTP HLTV Command API — LAN build, ported from production v2.2 (2026-07-07).
Same endpoints/auth the KTPHLTVRecorder 1.7.0 plugin expects:
  POST /hltv/<port>/command  - write command to the HLTV FIFO cmdpipe
  POST /hltv/<port>/restart  - systemctl restart hltv@<port>
  GET  /hltv/<port>/state    - recording state from journalctl (+status poke)
  GET  /health               - unauthenticated liveness

Auth: X-Auth-Key header. Key comes from $HLTV_API_KEY (systemd Environment=);
the process REFUSES to start with an empty key — an empty compare would
authenticate anonymous requests on a 0.0.0.0 bind.
Port range comes from $HLTV_PORT_MIN/$HLTV_PORT_MAX (LAN ports differ from
the production 27020-27044).
"""

import hmac
import os
import re
import sys
import json
import time
import subprocess
import socket
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

API_PORT = 8087
AUTH_KEY = os.environ.get("HLTV_API_KEY", "")
if not AUTH_KEY:
    sys.exit("HLTV_API_KEY is empty — refusing to start (would auth anonymous requests)")
PIPE_DIR = "/home/hltvserver/cmdpipes"
_PMIN = int(os.environ.get("HLTV_PORT_MIN", "27020"))
_PMAX = int(os.environ.get("HLTV_PORT_MAX", "27044"))
VALID_PORTS = range(_PMIN, _PMAX + 1)

# /state journal scan window + trigger poll (see production hltv-api.py v2.2
# for the forensic history: HLTV only prints "Recording to ... Length" in
# response to a `status` rcon, so /state pokes the cmdpipe then polls for
# the fresh line instead of sleeping a fixed amount).
STATE_JOURNAL_WINDOW = "5 minutes ago"
STATE_JOURNALCTL_TIMEOUT = 4
STATE_TRIGGER_POLL_SEC = 0.15
STATE_TRIGGER_MAX_WAIT = 1.5
STATE_TRIGGER_FRESH_SEC = 3

_RE_START_RECORDING = re.compile(r"Start recording to (?P<basename>.+?)\.dem\.")
_RE_ALREADY_RECORDING = re.compile(r"Already recording to (?P<basename>.+?)\.dem\.")
_RE_COMPLETED_DEMO = re.compile(r"Completed demo (?P<basename>.+?)\.dem\.")
_RE_RECORDING_LENGTH = re.compile(r"Recording to (?P<basename>.+?)\.dem, Length")
_RE_JOURNAL_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:?\d{2})\s+\S+\s+\S+:\s+(?P<msg>.*)$"
)


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        super().server_bind()


def _parse_iso(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")


def _service_active(port):
    try:
        result = subprocess.run(
            ["systemctl", "is-active", f"hltv@{port}.service"],
            capture_output=True, text=True, timeout=3,
        )
        return result.stdout.strip() == "active"
    except Exception:
        return False


def _trigger_status_rcon(port):
    pipe_path = f"{PIPE_DIR}/hltv-{port}.pipe"
    if not os.path.exists(pipe_path):
        return False
    try:
        fd = os.open(pipe_path, os.O_WRONLY | os.O_NONBLOCK)
        try:
            os.write(fd, b"status\n")
        finally:
            os.close(fd)
        return True
    except (BlockingIOError, OSError):
        return False


def _scan_journal(port):
    try:
        result = subprocess.run(
            ["journalctl", "-u", f"hltv@{port}.service",
             "--since", STATE_JOURNAL_WINDOW, "--no-pager", "-q",
             "--output=short-iso"],
            capture_output=True, text=True, timeout=STATE_JOURNALCTL_TIMEOUT,
        )
        lines = result.stdout.splitlines()
    except subprocess.TimeoutExpired:
        return {"recording": False, "basename": None, "process_running": True,
                "last_event": None, "already_recording_warning": False,
                "error": "journalctl timeout"}
    except Exception as e:
        return {"recording": False, "basename": None, "process_running": True,
                "last_event": None, "already_recording_warning": False,
                "error": str(e)}

    now = datetime.now(timezone.utc)
    for raw in reversed(lines):
        m = _RE_JOURNAL_LINE.match(raw)
        if not m:
            continue
        msg = m.group("msg")
        ts = m.group("ts")
        for kind, regex in (
            ("already_recording", _RE_ALREADY_RECORDING),
            ("start_recording", _RE_START_RECORDING),
            ("completed_demo", _RE_COMPLETED_DEMO),
            ("recording_length", _RE_RECORDING_LENGTH),
        ):
            mm = regex.search(msg)
            if not mm:
                continue
            try:
                age_sec = int((now - _parse_iso(ts)).total_seconds())
            except Exception:
                age_sec = -1
            basename = mm.groupdict().get("basename")
            recording = kind != "completed_demo"
            return {"recording": recording,
                    "basename": basename if recording else None,
                    "process_running": True,
                    "last_event": {"type": kind, "age_sec": age_sec},
                    "already_recording_warning": kind == "already_recording"}

    return {"recording": False, "basename": None, "process_running": True,
            "last_event": None, "already_recording_warning": False}


def _parse_state(port):
    if not _service_active(port):
        return {"recording": False, "basename": None, "process_running": False,
                "last_event": None, "already_recording_warning": False}

    _trigger_status_rcon(port)
    deadline = time.monotonic() + STATE_TRIGGER_MAX_WAIT
    state = _scan_journal(port)
    while True:
        if "error" in state:
            break
        ev = state["last_event"]
        if ev and 0 <= ev["age_sec"] <= STATE_TRIGGER_FRESH_SEC:
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(STATE_TRIGGER_POLL_SEC)
        state = _scan_journal(port)
    return state


class HLTVHandler(BaseHTTPRequestHandler):
    timeout = 10

    def log_message(self, format, *args):
        print(f"[HLTV-API] {args[0]}")

    def send_json(self, code, data):
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _check_auth(self):
        auth = self.headers.get("X-Auth-Key", "")
        # Timing-safe, bytes operands (str compare_digest raises TypeError on
        # a non-ASCII header a client could spam for per-request 500s).
        if not hmac.compare_digest(auth.encode("utf-8", "surrogateescape"),
                                   AUTH_KEY.encode("utf-8")):
            self.send_json(401, {"error": "Unauthorized"})
            return False
        return True

    def _parse_path(self):
        parts = self.path.strip("/").split("/")
        if len(parts) != 3 or parts[0] != "hltv":
            self.send_json(400, {"error": "Invalid path"})
            return None, None
        try:
            port = int(parts[1])
        except ValueError:
            self.send_json(400, {"error": "Invalid port number"})
            return None, None
        if port not in VALID_PORTS:
            self.send_json(400, {"error": f"Port must be {_PMIN}-{_PMAX}"})
            return None, None
        return port, parts[2]

    def do_POST(self):
        if not self._check_auth():
            return
        port, action = self._parse_path()
        if port is None:
            return
        if action == "command":
            self.handle_command(port)
        elif action == "restart":
            self.handle_restart(port)
        else:
            self.send_json(400, {"error": f"Unknown action: {action}"})

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"status": "ok"})
            return
        if not self._check_auth():
            return
        port, action = self._parse_path()
        if port is None:
            return
        if action == "state":
            self.handle_state(port)
        else:
            self.send_json(400, {"error": f"Unknown GET action: {action}"})

    def handle_command(self, port):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            self.send_json(400, {"error": "No command provided"})
            return
        body = self.rfile.read(length).decode("utf-8")
        try:
            data = json.loads(body)
            command = data.get("command", "").strip()
        except json.JSONDecodeError:
            command = body.strip()
        if not command:
            self.send_json(400, {"error": "Empty command"})
            return
        pipe_path = f"{PIPE_DIR}/hltv-{port}.pipe"
        if not os.path.exists(pipe_path):
            self.send_json(500, {"error": f"Pipe not found: {pipe_path}"})
            return
        try:
            fd = os.open(pipe_path, os.O_WRONLY | os.O_NONBLOCK)
            try:
                os.write(fd, (command + "\n").encode())
            finally:
                os.close(fd)
            self.send_json(200, {"success": True, "port": port, "command": command})
            print(f"[HLTV-API] Sent to {port}: {command}")
        except BlockingIOError:
            self.send_json(500, {"error": f"Pipe {port} not ready (no reader)"})
        except Exception as e:
            self.send_json(500, {"error": str(e)})

    def handle_restart(self, port):
        service_name = f"hltv@{port}"
        print(f"[HLTV-API] Restarting {service_name}...")
        try:
            result = subprocess.run(
                ["systemctl", "restart", service_name],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                self.send_json(200, {"success": True, "port": port,
                                     "message": f"HLTV {port} restarted successfully"})
            else:
                self.send_json(500, {"success": False, "port": port,
                                     "error": result.stderr.strip() or "Unknown error"})
        except subprocess.TimeoutExpired:
            self.send_json(500, {"error": "Restart timed out"})
        except Exception as e:
            self.send_json(500, {"error": str(e)})

    def handle_state(self, port):
        self.send_json(200, _parse_state(port))


if __name__ == "__main__":
    print(f"[HLTV-API] Starting on port {API_PORT} (threaded, LAN v2.2; ports {_PMIN}-{_PMAX})")
    server = ThreadingHTTPServer(("0.0.0.0", API_PORT), HLTVHandler)
    server.serve_forever()
SCRIPT
chmod +x "$HLTV_HOME/hltv-api.py"
chown hltvserver:hltvserver "$HLTV_HOME/hltv-api.py"

# systemd service. Runs as root: /restart calls systemctl and /state reads the
# hltv@ journals — same privilege model as the production hltv-api.service.
# The key is injected via Environment= (600-perm unit file, never a default).
HLTV_PORT_MAX=$((HLTV_BASE_PORT + NUM_HLTV_INSTANCES - 1))
cat > /etc/systemd/system/hltv-api.service << EOF
[Unit]
Description=KTP HLTV API (LAN)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/home/hltvserver
Environment="HLTV_API_KEY=$HLTV_API_KEY"
Environment="HLTV_PORT_MIN=$HLTV_BASE_PORT"
Environment="HLTV_PORT_MAX=$HLTV_PORT_MAX"
ExecStart=/usr/bin/python3 /home/hltvserver/hltv-api.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
chmod 600 /etc/systemd/system/hltv-api.service

systemctl daemon-reload
systemctl enable hltv-api
systemctl restart hltv-api

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

    # HLTV Demos — the 1.7.0 always-on recorder writes auto_lanN*.dem into the
    # HLTV game dir (no renamer/organizer at LAN), so serve that directly.
    # The listing includes game files too; demos are the auto_lan*.dem entries.
    location /demos {
        alias /home/hltvserver/hlds/dod;
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

    # The KTP schema + migrations are authored with MariaDB-only idempotency DDL
    # (ADD COLUMN/CREATE INDEX/ADD INDEX ... IF NOT EXISTS), which MySQL (both 8.0
    # on the cloud data server and 8.4 here) rejects with a 1064 syntax error.
    # Strip those IF NOT EXISTS clauses on import so the same bundle works against
    # MySQL. The base install.sql is upstream HLStatsX and already MySQL-clean, so
    # it imports verbatim. Fresh-DB-only (canary-gated), so non-idempotent DDL is
    # safe here.
    mysql_compat() {  # sed a MariaDB-flavored .sql to MySQL on stdout
        sed -E 's/ADD COLUMN IF NOT EXISTS/ADD COLUMN/Ig; s/CREATE INDEX IF NOT EXISTS/CREATE INDEX/Ig; s/ADD INDEX IF NOT EXISTS/ADD INDEX/Ig' "$1"
    }

    # Schema import. install.sql is the upstream HLStatsX base; ktp_schema.sql
    # + any migrate_*.sql are KTP additions on top. Skip if the canary
    # hlstats_Actions table already exists (idempotent re-run).
    SCHEMA_LOADED=$(mysql -u root -p"$MYSQL_ROOT_PASSWORD" hlstatsx -sN -e \
        "SHOW TABLES LIKE 'hlstats_Actions';" 2>/dev/null || true)
    if [ -z "$SCHEMA_LOADED" ]; then
        log_info "Importing base schema (install.sql)..."
        mysql -u root -p"$MYSQL_ROOT_PASSWORD" hlstatsx < /opt/hlstatsx/sql/install.sql

        # The KTP additions are optional on top of a working base HLStatsX. Don't
        # let a bug in one of them abort the whole dataserver provision (which
        # would skip the service/creds/firewall below) — warn and continue so
        # base stats still come up. Re-run after fixing to apply the rest.
        if [ -f /opt/hlstatsx/sql/ktp_schema.sql ]; then
            log_info "Importing KTP schema additions (ktp_schema.sql)..."
            mysql_compat /opt/hlstatsx/sql/ktp_schema.sql | mysql -u root -p"$MYSQL_ROOT_PASSWORD" hlstatsx \
                || log_warn "ktp_schema.sql import failed — base HLStatsX still configured; fix + re-import"
        fi
        # Apply migrate_*.sql in lexicographic order (matches numbered prefix
        # convention: migrate_001_*, migrate_002_*, ...).
        for migration in /opt/hlstatsx/sql/migrate_*.sql; do
            [ -f "$migration" ] || continue
            log_info "  applying $(basename "$migration")"
            mysql_compat "$migration" | mysql -u root -p"$MYSQL_ROOT_PASSWORD" hlstatsx \
                || log_warn "$(basename "$migration") failed — continuing"
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
# HLTV range derived from the actual instance layout (the old hardcoded
# 27020:27029 only matched the 5-instance default by luck).
ufw allow "$HLTV_BASE_PORT:$((HLTV_BASE_PORT + NUM_HLTV_INSTANCES - 1))/udp" comment "HLTV"
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
echo "  - HLTV: Ports $HLTV_BASE_PORT-$((HLTV_BASE_PORT + NUM_HLTV_INSTANCES - 1)) (systemd hltv@<port>, always-on recording)"
echo "  - HLTV API: Port 8087 (X-Auth-Key; key in the credentials file)"
echo "  - FastDL: Port 80 (demos browsable at /demos — auto_lan*.dem)"
echo "  - MySQL: localhost (hlstatsx / $HLSTATSX_DB_PASSWORD)"
echo ""
# Persist credentials so the operator can retrieve them after the install
# (auto-generated random passwords would otherwise only exist in this stdout).
umask 077
cat > "$CREDS_FILE" <<CREDS
KTP LAN dataserver credentials (generated $(date -Iseconds))
MYSQL_ROOT_PASSWORD=$MYSQL_ROOT_PASSWORD
HLSTATSX_DB_PASSWORD=$HLSTATSX_DB_PASSWORD
HLTV_ADMIN_PASSWORD=$HLTV_ADMIN_PASSWORD
HLTV_PROXY_PASSWORD=$HLTV_PROXY_PASSWORD
HLTV_API_KEY=$HLTV_API_KEY
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
echo "  - HLTV: /home/hltvserver/hltv-ctl.sh start   (as root — wraps systemd hltv@<port>)"
echo "  - HLTV API: systemctl start hltv-api   (already enabled + started)"
echo ""
echo "Demo retention note: always-on recording accumulates auto_lan*.dem in"
echo "/home/hltvserver/hlds/dod/ (~3 GB/day/instance under match load). NO"
echo "cleanup cron is installed on LAN — the production 6h auto-purge would"
echo "delete unrenamed demos, and there is no renamer here. Archive/clear"
echo "manually after the event."
echo ""
echo "========================================"
