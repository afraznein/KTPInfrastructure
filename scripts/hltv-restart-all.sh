#!/bin/bash
# KTP HLTV Scheduled Restart Script
# Restarts all HLTV instances and sends Discord notification
#
# Location: /usr/local/bin/hltv-restart-all.sh (on data server)
# Runs via the `hltv-restart.timer` SYSTEMD TIMER (03:00 + 11:00 ET), NOT
# cron — soak-verify greps `journalctl -u hltv-restart`, so redeploying this
# as a cron job (the pre-2026 pattern this header used to document) would
# silently break that check. Log: /var/log/hltv-restart.log

# ============================================================================
# Configuration
# ============================================================================
source /etc/ktp/discord-relay.conf

# Discord embed colors (matching KTPMatchHandler)
COLOR_GREEN=65280       # 0x00FF00 - Success
COLOR_ORANGE=16750848   # 0xFFA500 - Partial success
COLOR_RED=16711680      # 0xFF0000 - Failure

# KTP emoji
KTP_EMOJI="<:KTP:1002382703020212245>"

# Server name for footer
SERVER_NAME="KTP - HLTV"

# ============================================================================
# Restart Logic
# ============================================================================
TIMESTAMP=$(TZ='America/New_York' date '+%Y-%m-%d %H:%M:%S EST')
LOG_PREFIX="[$TIMESTAMP]"

echo "$LOG_PREFIX Starting HLTV scheduled restart..."

SUCCESS=0
FAILED=0
FAILED_PORTS=""

RESTARTED_PORTS=""
for port in $(seq 27020 27043); do  # 27044 (chi5) disabled 2026-04-10
    if systemctl restart hltv@$port 2>/dev/null; then
        RESTARTED_PORTS="$RESTARTED_PORTS $port"
    else
        ((FAILED++))
        FAILED_PORTS="$FAILED_PORTS $port"
        echo "$LOG_PREFIX hltv@$port restart command failed"
    fi
done

# systemctl restart returns success once the main process starts — it does NOT
# confirm the process stays up. Give a crash-looper (bad hltv.cfg, port conflict,
# corrupt cache) a moment to fail, then verify actual state, so a dead instance
# isn't counted green. The hourly health cron is otherwise the only backstop,
# leaving up to ~an hour of silent non-recording on that port.
if [ -n "$RESTARTED_PORTS" ]; then
    sleep 5
    for port in $RESTARTED_PORTS; do
        if systemctl is-active --quiet hltv@$port; then
            ((SUCCESS++))
        else
            ((FAILED++))
            FAILED_PORTS="$FAILED_PORTS $port"
            echo "$LOG_PREFIX hltv@$port restarted but is not active (crash-loop?)"
        fi
    done
fi

echo "$LOG_PREFIX $SUCCESS succeeded, $FAILED failed"
[ -n "$FAILED_PORTS" ] && echo "$LOG_PREFIX Failed ports:$FAILED_PORTS"

# ============================================================================
# Discord Notification
# ============================================================================
FOOTER_TIMESTAMP=$(TZ='America/New_York' date '+%m/%d/%Y %I:%M %p EST')
TOTAL=$((SUCCESS + FAILED))

if [ $FAILED -eq 0 ]; then
    TITLE="$KTP_EMOJI HLTV Restart Complete"
    DESCRIPTION="All $SUCCESS HLTV instances restarted successfully."
    COLOR=$COLOR_GREEN
elif [ $SUCCESS -gt 0 ]; then
    TITLE="$KTP_EMOJI HLTV Restart - Partial"
    DESCRIPTION="$SUCCESS/$TOTAL instances restarted.\\n**Failed ports:**$FAILED_PORTS"
    COLOR=$COLOR_ORANGE
else
    TITLE="$KTP_EMOJI HLTV Restart Failed"
    DESCRIPTION="All instances failed to restart!\\n**Failed ports:**$FAILED_PORTS"
    COLOR=$COLOR_RED
fi

# Function to send Discord embed
send_discord_embed() {
    local channel_id="$1"
    if [ -z "$channel_id" ]; then
        return
    fi

    local payload=$(cat <<EOF
{
  "channelId": "$channel_id",
  "embeds": [{
    "title": "$TITLE",
    "description": "$DESCRIPTION",
    "color": $COLOR,
    "footer": {
      "text": "$SERVER_NAME - $FOOTER_TIMESTAMP"
    }
  }]
}
EOF
)

    curl -s -X POST "$RELAY_URL" \
        -H "X-Relay-Auth: $AUTH_SECRET" \
        -H "Content-Type: application/json" \
        -d "$payload"
    echo ""
}

# Send to both Discord channels
echo "$LOG_PREFIX Sending Discord notifications..."
send_discord_embed "$CHANNEL_HLTV_STATUS"
send_discord_embed "$CHANNEL_HLTV_STATUS_EXTERNAL"

echo "$LOG_PREFIX HLTV scheduled restart complete."
