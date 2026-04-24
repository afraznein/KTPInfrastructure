#!/bin/bash
# ktp-fleet-health.sh — per-host fleet alerter, runs every minute via cron.
#
# Fires a Discord webhook alert when `pgrep -c hlds_linux` drops below the
# expected instance count for N consecutive minutes. Single alert per state
# transition (one "DEGRADED" post on decline, one "RECOVERED" post on return).
# Silent when healthy. Designed to catch any scenario that takes instances
# offline — not just the specific bug that caused the 2026-04-24 outage.
#
# DEFAULTS (overridable via ~/.ktp-fleet-health/config.sh):
#   EXPECTED=5          — 5 instances per baremetal. Chicago VPS sets 4.
#   THRESHOLD_MINUTES=3 — debounce: need 3 consecutive bad minutes before alert.
#   WEBHOOK_URL=…       — KTP Discord private / test channel.
#
# STATE (~/.ktp-fleet-health/state):
#   CONSECUTIVE_BAD=N   — minutes consecutively below expected
#   ALERT_STATE=healthy|unhealthy
#   LAST_RUN=epoch
#   LAST_RUNNING=N
#
# CRON:
#   * * * * * /home/dodserver/ktp-fleet-health.sh >/dev/null 2>&1

set -euo pipefail

HOME_DIR=${HOME:-/home/dodserver}
STATE_DIR=$HOME_DIR/.ktp-fleet-health
STATE_FILE=$STATE_DIR/state
CONFIG_FILE=$STATE_DIR/config.sh
HOSTNAME_SHORT=$(hostname -s 2>/dev/null || hostname)

mkdir -p "$STATE_DIR"

# Defaults — override via config.sh
EXPECTED=5
THRESHOLD_MINUTES=3
WEBHOOK_URL="https://discord.com/api/webhooks/1453179712862949528/0brgSCOTFzEoMnNuaCN4u1cf1COrkqpbq58XYbm-E0LzNlrCtpwt8b8iUroZVfY5nzDn"

# Load per-host overrides
[ -f "$CONFIG_FILE" ] && source "$CONFIG_FILE"

# Count running instances
RUNNING=$(pgrep -c hlds_linux 2>/dev/null || echo 0)

# Load state
CONSECUTIVE_BAD=0
ALERT_STATE=healthy
[ -f "$STATE_FILE" ] && source "$STATE_FILE"

# Update consecutive-bad counter
if [ "$RUNNING" -lt "$EXPECTED" ]; then
    CONSECUTIVE_BAD=$((CONSECUTIVE_BAD + 1))
else
    CONSECUTIVE_BAD=0
fi

# Minimal JSON-escape for embed description (handles only common chars)
json_escape() {
    local s=${1//\\/\\\\}
    s=${s//\"/\\\"}
    s=${s//$'\n'/\\n}
    printf '%s' "$s"
}

send_alert() {
    local title="$1"
    local desc="$2"
    local color="$3"
    local safe_title safe_desc
    safe_title=$(json_escape "$title")
    safe_desc=$(json_escape "$desc")
    local payload
    payload=$(printf '{"embeds":[{"title":"%s","description":"%s","color":%s}]}' \
        "$safe_title" "$safe_desc" "$color")
    curl -s -m 10 -X POST "$WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d "$payload" >/dev/null 2>&1 || true
}

# Enumerate which ports look down (cosmetic, for the alert body)
down_ports() {
    local out=""
    for port in 27015 27016 27017 27018 27019; do
        [ -d "$HOME_DIR/dod-$port" ] || continue
        if ! pgrep -f "hlds_linux.*-port $port" >/dev/null 2>&1; then
            out="${out}${port} "
        fi
    done
    printf '%s' "${out% }"
}

# State transitions
if [ "$CONSECUTIVE_BAD" -ge "$THRESHOLD_MINUTES" ] && [ "$ALERT_STATE" = "healthy" ]; then
    PORTS_DOWN=$(down_ports)
    send_alert \
        "🚨 Fleet Health: ${HOSTNAME_SHORT} DEGRADED" \
        "Running: ${RUNNING}/${EXPECTED} for ${CONSECUTIVE_BAD} consecutive minutes.
Ports down: ${PORTS_DOWN:-unknown}
Host: ${HOSTNAME_SHORT}" \
        15158332
    ALERT_STATE=unhealthy
elif [ "$RUNNING" -eq "$EXPECTED" ] && [ "$ALERT_STATE" = "unhealthy" ]; then
    send_alert \
        "✅ Fleet Health: ${HOSTNAME_SHORT} recovered" \
        "Running: ${RUNNING}/${EXPECTED}. Recovery confirmed.
Host: ${HOSTNAME_SHORT}" \
        3066993
    ALERT_STATE=healthy
fi

# Persist state
cat > "$STATE_FILE" <<EOF
CONSECUTIVE_BAD=$CONSECUTIVE_BAD
ALERT_STATE=$ALERT_STATE
LAST_RUN=$(date +%s)
LAST_RUNNING=$RUNNING
EOF
