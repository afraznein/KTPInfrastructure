#!/bin/bash
# KTP Data Server Health Check
#
# Monitors critical services + timers + HLTV instance coverage. Alerts to
# Discord ONLY on state transitions (service goes down → alert; service
# recovers → alert "restored"; persistent-down → silent, no chat spam).
#
# Schedule: hourly via /etc/cron.d/ktp-data-server-health. Issues here are
# background services whose failures aren't player-visible, so a 10-minute
# window felt like overkill.
#
# State file: /var/lib/ktp-data-server-health.json
# Log:        /var/log/ktp-data-server-health.log
# Discord:    sources /etc/ktp/discord-relay.conf (RELAY_URL + AUTH_SECRET)

set -euo pipefail

STATE_FILE=/var/lib/ktp-data-server-health.json
# #ktp-crashes — consolidated with perf-rollup (PERF_ALERT_CHANNEL in
# /etc/ktp/discord-relay.conf, same channel) per operator decision
# 2026-05-06. Health alerts are crash-class signals (services dying);
# routing them alongside crashes keeps the operational signal in one
# place. Reverses the May 3 "dedicated #ktp-data-server-health" split.
# Override via ALERT_CHANNEL env var if a different routing is needed.
ALERT_CHANNEL="${ALERT_CHANNEL:-1497957091107668070}"
# HLTV port range mirrors game ports: 27020=ATL1, 27021=ATL2, ... 27044=CHI5
HLTV_PORT_START=27020
HLTV_PORT_END=27044
# Intentionally excluded (e.g. hltv@27044 was disabled 2026-04-10 when the
# upstream Chicago 27019 game server was taken offline for the 4-server trial).
# Add a port here if the corresponding game server is disabled on purpose.
HLTV_EXCLUDED_PORTS=(27044)

# Critical services that must be active (systemctl is-active == "active")
CRITICAL_SERVICES=(
    mysql.service
    nginx.service
    hlstatsx.service
    hltv-api.service
    ktp-ac-api.service
    ktp-file-distributor.service
)

# Timers that must be enabled + scheduled
CRITICAL_TIMERS=(
    hltv-restart.timer
)

[ -f /etc/ktp/discord-relay.conf ] && source /etc/ktp/discord-relay.conf

ts() { date '+%Y-%m-%d %H:%M:%S'; }

# ---- Collect current "down" set ----
down=()

for svc in "${CRITICAL_SERVICES[@]}"; do
    state=$(systemctl is-active "$svc" 2>/dev/null || true)
    if [ "$state" != "active" ]; then
        down+=("$svc=$state")
    fi
done

for t in "${CRITICAL_TIMERS[@]}"; do
    state=$(systemctl is-active "$t" 2>/dev/null || true)
    enabled=$(systemctl is-enabled "$t" 2>/dev/null || true)
    if [ "$state" != "active" ] || [ "$enabled" != "enabled" ]; then
        down+=("$t=${state}/${enabled}")
    fi
done

# HLTV instance coverage — check each port in the expected set,
# skipping intentionally-excluded ones.
is_excluded() {
    local p="$1"
    for ex in "${HLTV_EXCLUDED_PORTS[@]}"; do
        [ "$ex" = "$p" ] && return 0
    done
    return 1
}
expected_hltv=0
active_hltv=0
missing_hltv=()
for p in $(seq "$HLTV_PORT_START" "$HLTV_PORT_END"); do
    if is_excluded "$p"; then continue; fi
    expected_hltv=$((expected_hltv + 1))
    state=$(systemctl is-active "hltv@$p" 2>/dev/null || true)
    if [ "$state" = "active" ]; then
        active_hltv=$((active_hltv + 1))
    else
        missing_hltv+=("hltv@$p=$state")
    fi
done
if [ "$active_hltv" -lt "$expected_hltv" ]; then
    down+=("hltv-instance-count=${active_hltv}/${expected_hltv}")
    # Also list which specific instance(s) are down so the alert is actionable
    for m in "${missing_hltv[@]}"; do
        down+=("$m")
    done
fi

# ---- Build sorted lists for set comparison ----
# curr.list: sorted, deduplicated set of currently-down items
# prev.list: same from the previous run's state file
TMP_CURR=$(mktemp) TMP_PREV=$(mktemp)
trap 'rm -f "$TMP_CURR" "$TMP_PREV" /tmp/ktp-health-resp.txt' EXIT

if [ ${#down[@]} -gt 0 ]; then
    printf '%s\n' "${down[@]}" | sort -u > "$TMP_CURR"
else
    : > "$TMP_CURR"
fi

if [ -f "$STATE_FILE" ]; then
    jq -r '.down[]?' < "$STATE_FILE" 2>/dev/null | sort -u > "$TMP_PREV"
else
    : > "$TMP_PREV"
fi

# ---- Compute transitions via comm ----
# comm -23: lines only in curr (new_down)
# comm -13: lines only in prev (recovered)
mapfile -t new_down < <(comm -23 "$TMP_CURR" "$TMP_PREV")
mapfile -t recovered < <(comm -13 "$TMP_CURR" "$TMP_PREV")

# ---- Save current state ----
mkdir -p "$(dirname "$STATE_FILE")"
if [ -s "$TMP_CURR" ]; then
    down_json=$(jq -R . < "$TMP_CURR" | jq -s .)
else
    down_json='[]'
fi
jq -n --argjson d "$down_json" --arg ts "$(ts)" \
    '{updated_at: $ts, down: $d}' > "$STATE_FILE"

# ---- Alert on transitions only ----
if [ ${#new_down[@]} -eq 0 ] && [ ${#recovered[@]} -eq 0 ]; then
    echo "[$(ts)] no transitions (currently down: ${#down[@]})"
    exit 0
fi

echo "[$(ts)] TRANSITIONS: new_down=${#new_down[@]} recovered=${#recovered[@]}"

# Build Discord embed body
desc=""
if [ ${#new_down[@]} -gt 0 ]; then
    desc+='⚠️ **Services down:**'$'\n'
    for x in "${new_down[@]}"; do
        desc+="• \`${x}\`"$'\n'
    done
fi
if [ ${#recovered[@]} -gt 0 ]; then
    [ -n "$desc" ] && desc+=$'\n'
    desc+='✅ **Recovered:**'$'\n'
    for x in "${recovered[@]}"; do
        desc+="• \`${x}\`"$'\n'
    done
fi

# Still-down services (persistent, informational footer)
if [ ${#down[@]} -gt 0 ]; then
    current_list=$(printf '%s\n' "${down[@]}" 2>/dev/null | grep -v '^$' | sort -u)
    if [ -n "$current_list" ]; then
        desc+=$'\n''_All currently down: '"$(echo "$current_list" | paste -sd, -)"'_'
    fi
fi

# KTP canonical colors — match perf-rollup, crashreporter, soak-verify, etc.
# Pre-1.5.24 used raw hex (65280 / 16711680) which rendered as pure green/red
# instead of the KTP brand colors. Aligning now so the data-server-health
# embeds visually match the rest of the alert flow.
KTP_GREEN=5763719
KTP_RED=15548997
color=$KTP_GREEN
[ ${#new_down[@]} -gt 0 ] && color=$KTP_RED

payload=$(jq -n \
    --arg ch "$ALERT_CHANNEL" \
    --arg title '<:ktp:1105490705188659272> KTP Data Server Health' \
    --arg desc "$desc" \
    --arg footer "ktp-data-server-health @ $(TZ=America/New_York date '+%Y-%m-%d %H:%M %Z')" \
    --argjson color "$color" \
    '{channelId: $ch, embeds: [{title: $title, description: $desc, color: $color, footer: {text: $footer}}]}')

http=$(curl -sS -o /tmp/ktp-health-resp.txt -w "%{http_code}" \
    -X POST "${RELAY_URL:-}" \
    -H "X-Relay-Auth: ${AUTH_SECRET:-}" \
    -H "Content-Type: application/json" \
    -d "$payload" 2>&1 || echo "000")
if [ "$http" != "200" ] && [ "$http" != "204" ]; then
    echo "[$(ts)] WARN: relay returned HTTP $http: $(cat /tmp/ktp-health-resp.txt 2>/dev/null | head -c 200)" >&2
else
    echo "[$(ts)] alert posted (HTTP $http)"
fi
