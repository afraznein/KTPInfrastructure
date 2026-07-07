#!/bin/bash
# install-teamspeak.sh — install the TeamSpeak 3 voice server for a KTP LAN event.
#
# LAN-only step (the cloud fleet uses no voice server). Installs TS3 as its own
# system user + systemd unit, pinned to the housekeeping CPU cores so it never
# competes with the isolated game-server cores. Run as root on the all-in-one
# LAN box AFTER provision-gameserver.sh (which sets up isolcpus + the layout).
#
# Usage:
#   sudo ./install-teamspeak.sh [server-tarball.tar.bz2]
#
# If no tarball is given it looks in the usual download spots. Idempotent:
# re-running upgrades the binaries in place and preserves the SQLite DB
# (ts3server.sqlitedb) so the virtual server, channels, and admin keys survive.
#
# Slots: the stock server allows 32. A LAN for 72 players needs TeamSpeak's free
# non-profit 512-slot licence — drop licensekey.dat into $TS_DIR and restart.

set -eu -o pipefail

TS_USER="teamspeak"
TS_DIR="/opt/teamspeak"
# Housekeeping cores: physical 0,1 + their HT siblings 8,9 on the W-2245 (8C/16T).
# Game servers own the isolated cores 2-7; HLTV + TeamSpeak + OS live here.
# Guarded below: CPUAffinity naming nonexistent CPUs fails the unit on smaller
# boxes, so pins outside 0..nproc-1 are dropped (empty result = no pinning).
TS_CPUS="${TS_CPUS:-0 1 8 9}"
NCPU=$(nproc)
TS_CPUS_VALID=""
for c in $TS_CPUS; do
    if [ "$c" -lt "$NCPU" ]; then
        TS_CPUS_VALID="${TS_CPUS_VALID:+$TS_CPUS_VALID }$c"
    fi
done
if [ "$TS_CPUS_VALID" != "$TS_CPUS" ]; then
    echo "[WARN] TS_CPUS '$TS_CPUS' exceeds this box's $NCPU CPUs — using '${TS_CPUS_VALID:-none}'"
fi
TS_CPUS="$TS_CPUS_VALID"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; }

[ "$EUID" -eq 0 ] || { err "must run as root"; exit 1; }

# Locate the server tarball.
TARBALL="${1:-}"
if [ -z "$TARBALL" ]; then
    for d in /home/*/Downloads /downloads /root/Downloads /tmp; do
        f=$(ls "$d"/teamspeak3-server_linux_amd64-*.tar.bz2 2>/dev/null | sort -V | tail -1 || true)
        [ -n "$f" ] && { TARBALL="$f"; break; }
    done
fi
[ -n "$TARBALL" ] && [ -f "$TARBALL" ] || { err "TeamSpeak server tarball not found (pass it as arg 1)"; exit 1; }
log "Using tarball: $TARBALL"

# Dedicated system user.
if ! id "$TS_USER" &>/dev/null; then
    useradd --system --create-home --home-dir "$TS_DIR" --shell /usr/sbin/nologin "$TS_USER"
    log "Created system user $TS_USER ($TS_DIR)"
else
    mkdir -p "$TS_DIR"
fi

# Extract to a temp dir then sync binaries in (preserve any existing DB/config).
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
tar -xjf "$TARBALL" -C "$TMP"
SRC=$(find "$TMP" -maxdepth 2 -name ts3server -type f -printf '%h\n' | head -1)
[ -n "$SRC" ] || { err "ts3server binary not found inside tarball"; exit 1; }
cp -rf "$SRC"/. "$TS_DIR"/
touch "$TS_DIR/.ts3server_license_accepted"
chown -R "$TS_USER":"$TS_USER" "$TS_DIR"
log "Installed TeamSpeak binaries to $TS_DIR"

# systemd unit — foreground via the minimal runscript (sets LD_LIBRARY_PATH).
cat > /etc/systemd/system/ts3server.service <<UNIT
[Unit]
Description=TeamSpeak 3 Server (KTP LAN)
After=network.target

[Service]
User=$TS_USER
WorkingDirectory=$TS_DIR
ExecStart=$TS_DIR/ts3server_minimal_runscript.sh license_accepted=1
# Pin to housekeeping cores; the isolated cores 2-7 belong to the game servers.
CPUAffinity=$TS_CPUS
Restart=always
RestartSec=5
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable ts3server >/dev/null 2>&1 || true
systemctl restart ts3server
log "ts3server.service enabled + started (CPUAffinity=$TS_CPUS)"

# Firewall.
if command -v ufw >/dev/null 2>&1; then
    ufw allow 9987/udp  comment "TeamSpeak voice"        >/dev/null 2>&1 || true
    ufw allow 30033/tcp comment "TeamSpeak file transfer" >/dev/null 2>&1 || true
    ufw allow 10011/tcp comment "TeamSpeak ServerQuery"   >/dev/null 2>&1 || true
    log "UFW: opened 9987/udp, 30033/tcp, 10011/tcp"
fi

# First-run admin token + ServerQuery admin password are printed to the log only
# on the very first start (when the DB is created). Surface + persist them.
sleep 3
CREDS=/root/ktp-teamspeak-credentials.txt
{
    echo "KTP LAN TeamSpeak — generated $(date -Iseconds)"
    echo "Install dir: $TS_DIR   Service: ts3server.service   CPUs: $TS_CPUS"
    echo
    grep -hriE "token=|serveradmin|ServerQuery|loginname|password=" "$TS_DIR"/logs/ 2>/dev/null | tail -20 || true
} > "$CREDS"
chmod 600 "$CREDS"

echo
log "TeamSpeak install complete."
warn "Admin token + ServerQuery password (first-run only) saved to $CREDS"
warn "Slots default to 32. For 72 players, add the free non-profit 512-slot"
warn "licensekey.dat to $TS_DIR and 'systemctl restart ts3server'."
