#!/usr/bin/env bash
# KTP crashreporter — install on a single game host as root.
#
# Idempotent: re-running upgrades the script + service file in place,
# refreshes deps, and restarts the service. Config file is preserved
# unless --force-config is passed.
#
# Usage:
#   sudo ./install.sh                         # auto-detect region, prompt for relay creds
#   sudo ./install.sh --region ATL            # skip auto-detect
#   sudo ./install.sh --force-config          # rewrite /etc/ktp/crashreporter.conf
#   sudo RELAY_URL=... RELAY_SECRET=... ./install.sh   # non-interactive

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: must run as root" >&2
    exit 1
fi

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
FORCE_CONFIG=0
EXPLICIT_REGION=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --region) EXPLICIT_REGION="$2"; shift 2 ;;
        --force-config) FORCE_CONFIG=1; shift ;;
        *) echo "unknown arg: $1" >&2; exit 1 ;;
    esac
done

# ----- Detect region from primary IP -----------------------------------------
detect_region() {
    local ip
    ip=$(hostname -I | awk '{print $1}')
    case "$ip" in
        74.91.121.9)     echo "ATL" ;;
        74.91.126.55)    echo "DAL" ;;
        66.163.114.109)  echo "DEN" ;;
        74.91.123.64)    echo "NY"  ;;
        172.238.176.101) echo "CHI" ;;
        *) echo "" ;;
    esac
}

REGION="${EXPLICIT_REGION:-$(detect_region)}"
if [[ -z "$REGION" ]]; then
    echo "ERROR: could not auto-detect region; pass --region ATL|DAL|DEN|NY|CHI" >&2
    exit 1
fi
echo "[*] region: $REGION"

# ----- Dependencies ----------------------------------------------------------
echo "[*] installing apt deps (gdb, inotify-tools, python3-requests)…"
DEBIAN_FRONTEND=noninteractive apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    gdb inotify-tools python3-requests >/dev/null

# ----- Files -----------------------------------------------------------------
echo "[*] installing /usr/local/bin/ktp-report-core"
install -o root -g root -m 0755 "$REPO_DIR/report_core.py" /usr/local/bin/ktp-report-core

echo "[*] installing /etc/systemd/system/ktp-crashreporter.service"
install -o root -g root -m 0644 "$REPO_DIR/ktp-crashreporter.service" \
    /etc/systemd/system/ktp-crashreporter.service

mkdir -p /etc/ktp
chmod 0755 /etc/ktp

# ----- Config (preserve if exists, unless --force-config) --------------------
CONF=/etc/ktp/crashreporter.conf
if [[ -f "$CONF" && $FORCE_CONFIG -eq 0 ]]; then
    echo "[*] config exists at $CONF; leaving in place (re-run with --force-config to rewrite)"
else
    : "${RELAY_URL:=}"
    : "${RELAY_SECRET:=}"
    : "${CRASHES_CHANNEL_ID:=1497957091107668070}"

    if [[ -z "$RELAY_URL" ]]; then read -rp "Discord Relay URL (full POST URL, ending in /reply): " RELAY_URL; fi
    if [[ -z "$RELAY_SECRET" ]]; then read -rsp "Discord Relay secret: " RELAY_SECRET; echo; fi

    # The plugin discord.ini already gives us the full POST URL (ends in /reply).
    # Daemon uses RELAY_URL as-is. If a base URL was passed, append /reply for
    # convenience.
    case "$RELAY_URL" in
        */reply|*/reply/) ;;  # already correct
        */) RELAY_URL="${RELAY_URL}reply" ;;
        *)  RELAY_URL="${RELAY_URL}/reply" ;;
    esac

    cat > "$CONF" <<EOF
# KTP crashreporter — installed by install.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
RELAY_URL="$RELAY_URL"
RELAY_SECRET="$RELAY_SECRET"
CRASHES_CHANNEL_ID="$CRASHES_CHANNEL_ID"
KTP_REGION="$REGION"
EOF
    chown root:dodserver "$CONF"
    chmod 0640 "$CONF"
    echo "[*] wrote $CONF (mode 0640 root:dodserver)"
fi

# ----- Service ---------------------------------------------------------------
systemctl daemon-reload
systemctl enable --now ktp-crashreporter.service

echo
echo "[OK] crashreporter installed."
systemctl --no-pager --lines=5 status ktp-crashreporter.service || true
echo
echo "Verify with:    journalctl -u ktp-crashreporter -f"
echo "Test trigger:   sudo -u dodserver kill -SEGV \$(pgrep -f 'hlds_linux.*-port 27015' | head -1)"
echo "                (only do this on a non-production instance!)"
