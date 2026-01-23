#!/bin/bash
# KTP HLTV Scheduled Restart Script
# Restarts all HLTV instances and sends Discord notification
#
# Location: /usr/local/bin/hltv-restart-all.sh (on data server)
# Cron:  0 3,11 * * * /usr/local/bin/hltv-restart-all.sh >> /var/log/hltv-restart.log 2>&1

# ============================================================================
# Configuration
# ============================================================================
source /etc/ktp/discord-relay.conf

# Discord embed colors (matching KTPMatchHandler)
COLOR_GREEN=65280       # 0x00FF00 - Success
COLOR_ORANGE=16750848   # 0xFFA500 - Partial success
COLOR_RED=16711680      # 0xFF0000 - Failure

# KTP emoji
KTP_EMOJI="<:ktp:1105490705188659272>"

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

for port in $(seq 27020 27044); do
    if systemctl restart hltv@$port 2>/dev/null; then
        ((SUCCESS++))
    else
        ((FAILED++))
        FAILED_PORTS="$FAILED_PORTS $port"
    fi
done

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
