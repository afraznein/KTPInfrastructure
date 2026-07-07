#!/bin/bash
# ktp-fleet-health.sh — per-host fleet alerter, runs every minute via cron.
#
# Fires a Discord webhook alert when `pgrep -c hlds_linux` drops below the
# expected instance count for N consecutive minutes. Single alert per state
# transition (one "DEGRADED" post on decline, one "RECOVERED" post on return).
# Silent when healthy. Designed to catch any scenario that takes instances
# offline — not just the specific bug that caused the 2026-04-24 outage.
#
# CONFIG SOURCES (loaded in order; later overrides earlier):
#   1. Script defaults (below) — empty webhook means "monitor silently".
#   2. /etc/ktp/fleet-health.conf — system-wide config (root-owned, dodserver-readable).
#   3. ~/.ktp-fleet-health/config.sh — per-host overrides.
#
# CONFIG KEYS (all optional; sensible defaults below):
#   EXPECTED=N             — instance count. Defaults to NUM_INSTANCES.
#   BASE_PORT=27015        — first game port; enumerate up to NUM_INSTANCES.
#   NUM_INSTANCES=5        — used for both EXPECTED and port enumeration.
#   THRESHOLD_MINUTES=3    — debounce window before firing DEGRADED alert.
#   WEBHOOK_URL=""         — Discord webhook. Empty = local-only monitoring.
#   MENTION_USER_ID=""     — Discord user to @-mention. Empty = no ping.
#   LOCATION=""            — override the hostname-derived location code.
#
# STATE (~/.ktp-fleet-health/state):
#   CONSECUTIVE_BAD=N      — minutes consecutively below expected
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
SYSTEM_CONFIG=/etc/ktp/fleet-health.conf
USER_CONFIG=$STATE_DIR/config.sh
HOSTNAME_SHORT=$(hostname -s 2>/dev/null || hostname)

mkdir -p "$STATE_DIR"

# Defaults — overridable via either config file.
BASE_PORT=27015
NUM_INSTANCES=5
EXPECTED=""                # auto-derives from NUM_INSTANCES if unset after config load
THRESHOLD_MINUTES=3
WEBHOOK_URL=""             # empty = silent monitoring (no Discord posts)
MENTION_USER_ID=""
LOCATION=""

# Load configs (system first, then per-host)
[ -r "$SYSTEM_CONFIG" ] && source "$SYSTEM_CONFIG"
[ -r "$USER_CONFIG"   ] && source "$USER_CONFIG"

# Derive EXPECTED if config didn't set it explicitly.
[ -z "$EXPECTED" ] && EXPECTED=$NUM_INSTANCES

# Resolve LOCATION if config didn't override. Known KTP hosts map to short
# codes for tidier alert titles; everything else falls back to hostname.
if [ -z "$LOCATION" ]; then
    case "$HOSTNAME_SHORT" in
        neinatl*|neinatlanta)    LOCATION="ATL" ;;
        neindallas|neindal*)     LOCATION="DAL" ;;
        neindenver|neinden*)     LOCATION="DEN" ;;
        neinnewyork|neinny*)     LOCATION="NY"  ;;
        neinchicago|neinchi*)    LOCATION="CHI" ;;
        *)                       LOCATION="$HOSTNAME_SHORT" ;;
    esac
fi

# Count running instances. procps pgrep -c prints "0" AND exits 1 when nothing
# matches, so `|| echo 0` INSIDE the substitution captured "0\n0" — the integer
# compare below then errored (swallowed by the cron redirect) and took the
# else-branch, resetting the debounce every minute: a TOTAL outage (0/5) never
# alerted while partial outages worked. `|| true` outside the substitution
# keeps pgrep's own "0" and absorbs the exit-1 for set -e.
RUNNING=$(pgrep -c hlds_linux 2>/dev/null) || true
[ -n "$RUNNING" ] || RUNNING=0

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
    # No webhook configured: monitor-only mode. Skip the network call entirely
    # rather than emitting a curl error that nobody will see.
    [ -z "$WEBHOOK_URL" ] && return 0
    local safe_title safe_desc
    safe_title=$(json_escape "$title")
    safe_desc=$(json_escape "$desc")
    local content=""
    local allowed_mentions='"allowed_mentions":{"parse":[]}'
    if [ -n "$MENTION_USER_ID" ]; then
        content="\"content\":\"<@${MENTION_USER_ID}>\","
        allowed_mentions="\"allowed_mentions\":{\"users\":[\"${MENTION_USER_ID}\"]}"
    fi
    local payload
    payload=$(printf '{%s"embeds":[{"title":"%s","description":"%s","color":%s}],%s}' \
        "$content" "$safe_title" "$safe_desc" "$color" "$allowed_mentions")
    curl -s -m 10 -X POST "$WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d "$payload" >/dev/null 2>&1 || true
}

# Enumerate which ports look down (cosmetic, for the alert body).
# Range derives from BASE_PORT + NUM_INSTANCES so LAN/custom deployments work.
down_ports() {
    local out="" port
    for ((i=0; i<NUM_INSTANCES; i++)); do
        port=$((BASE_PORT + i))
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
    # Format the ports-down line. If enumeration returned nothing but the counter
    # says we're under expected (weird state — e.g. all processes running but count
    # mismatch from some other cause), say so explicitly instead of "unknown".
    if [ -n "$PORTS_DOWN" ]; then
        PORTS_LINE="**Missing:** ${PORTS_DOWN// /, }"
    else
        PORTS_LINE="**Missing:** (no port missing from enumeration — investigate count source mismatch)"
    fi
    send_alert \
        "🚨 ${LOCATION} DEGRADED — ${RUNNING}/${EXPECTED} hlds_linux" \
        "Below expected for **${CONSECUTIVE_BAD} min**.
${PORTS_LINE}" \
        15158332
    ALERT_STATE=unhealthy
elif [ "$RUNNING" -eq "$EXPECTED" ] && [ "$ALERT_STATE" = "unhealthy" ]; then
    send_alert \
        "✅ ${LOCATION} recovered — ${RUNNING}/${EXPECTED} hlds_linux" \
        "Back to expected instance count. Outage window: previous alert → now." \
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
