#!/bin/bash
# KTP Game Server Scheduled Restart Script
# Restarts all 5 DoD game servers and sends Discord notification
#
# Usage: ktp-scheduled-restart.sh
# Cron:  0 3 * * * /home/dodserver/ktp-scheduled-restart.sh >> /home/dodserver/log/scheduled-restart.log 2>&1

# ============================================================================
# Configuration
# ============================================================================
RELAY_URL="https://discord-relay-78814186981.us-central1.run.app/reply"
EDIT_URL="https://discord-relay-78814186981.us-central1.run.app/edit"
AUTH_SECRET="ff661895111b948c8d5b6d732a50bbfff58e93798b4d4ecf0fc0d12f6c4db18e"

# Discord channels (same as HLTV status)
CHANNEL_KTP="1458222926586446059"          # KTP Discord
CHANNEL_EXTERNAL="1457951326666489996"     # 1.3 Discord

# Detect server location from IP
SERVER_IP=$(hostname -I | awk '{print $1}')
case "$SERVER_IP" in
    74.91.112.125) SERVER_NAME="KTP - Atlanta" ;;
    74.91.114.178) SERVER_NAME="KTP - Dallas" ;;
    *) SERVER_NAME="KTP - Unknown ($SERVER_IP)" ;;
esac

# Discord embed colors (matching KTPMatchHandler)
COLOR_GREEN=65280       # 0x00FF00 - Success
COLOR_ORANGE=16750848   # 0xFFA500 - Partial success / In progress
COLOR_RED=16711680      # 0xFF0000 - Failure

# KTP emoji
KTP_EMOJI="<:ktp:1105490705188659272>"

# ============================================================================
# Helper Functions
# ============================================================================
log() {
    echo "[$(TZ='America/New_York' date '+%Y-%m-%d %H:%M:%S EST')] $1"
}

# Send Discord embed and capture message ID
send_discord_embed() {
    local channel_id="$1"
    local title="$2"
    local description="$3"
    local color="$4"
    local footer="$5"

    local payload=$(cat <<EOF
{
  "channelId": "$channel_id",
  "embeds": [{
    "title": "$title",
    "description": "$description",
    "color": $color,
    "footer": {
      "text": "$footer"
    }
  }]
}
EOF
)

    local response=$(curl -s -X POST "$RELAY_URL" \
        -H "X-Relay-Auth: $AUTH_SECRET" \
        -H "Content-Type: application/json" \
        -d "$payload")

    # Extract message ID from response
    echo "$response" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4
}

# Edit existing Discord embed
edit_discord_embed() {
    local channel_id="$1"
    local message_id="$2"
    local title="$3"
    local description="$4"
    local color="$5"
    local footer="$6"

    local payload=$(cat <<EOF
{
  "channelId": "$channel_id",
  "messageId": "$message_id",
  "embeds": [{
    "title": "$title",
    "description": "$description",
    "color": $color,
    "footer": {
      "text": "$footer"
    }
  }]
}
EOF
)

    curl -s -X POST "$EDIT_URL" \
        -H "X-Relay-Auth: $AUTH_SECRET" \
        -H "Content-Type: application/json" \
        -d "$payload" >/dev/null
}

# ============================================================================
# Pause Monitor Cron
# ============================================================================
log "Pausing monitor cron to prevent race condition..."
CRON_BACKUP=$(mktemp)
crontab -l > "$CRON_BACKUP" 2>/dev/null

# Remove monitor entries temporarily
crontab -l 2>/dev/null | grep -v 'dodserver.*monitor' | crontab -
log "Monitor cron paused"

# Ensure we restore cron even if script fails
restore_cron() {
    log "Restoring monitor cron..."
    crontab "$CRON_BACKUP"
    rm -f "$CRON_BACKUP"
    log "Monitor cron restored"
}
trap restore_cron EXIT

# ============================================================================
# Send Initial "Restarting" Message
# ============================================================================
log "Starting scheduled restart for $SERVER_NAME"
FOOTER_TIMESTAMP=$(TZ='America/New_York' date '+%m/%d/%Y %I:%M %p EST')

INIT_TITLE="$KTP_EMOJI Server Restart In Progress"
INIT_DESC="Stopping all game servers..."

log "Sending initial Discord notification..."
MSG_ID_KTP=$(send_discord_embed "$CHANNEL_KTP" "$INIT_TITLE" "$INIT_DESC" "$COLOR_ORANGE" "$SERVER_NAME - $FOOTER_TIMESTAMP")
MSG_ID_EXT=$(send_discord_embed "$CHANNEL_EXTERNAL" "$INIT_TITLE" "$INIT_DESC" "$COLOR_ORANGE" "$SERVER_NAME - $FOOTER_TIMESTAMP")
log "Message IDs: KTP=$MSG_ID_KTP, External=$MSG_ID_EXT"

# ============================================================================
# Stop All Servers (LinuxGSM graceful stop)
# ============================================================================
log "Stopping all servers via LinuxGSM..."

for port in 27015 27016 27017 27018 27019; do
    n=$((port - 27014))
    if [ $n -eq 1 ]; then
        SERVER_EXEC="dodserver"
    else
        SERVER_EXEC="dodserver$n"
    fi

    cd ~/dod-$port
    ./$SERVER_EXEC stop >/dev/null 2>&1 &
done

# Wait for stops to complete
log "Waiting for servers to stop..."
sleep 10

# Check if any still running
STILL_RUNNING=$(pgrep -c hlds_linux 2>/dev/null || echo "0")
STILL_RUNNING=${STILL_RUNNING//[^0-9]/}  # Strip non-numeric chars
if [ "${STILL_RUNNING:-0}" -gt 0 ]; then
    log "WARNING: $STILL_RUNNING servers still running after graceful stop, force killing..."
    pkill -9 hlds_run 2>/dev/null
    pkill -9 hlds_linux 2>/dev/null
    sleep 3
fi

log "All servers stopped"

# ============================================================================
# Start All Servers
# ============================================================================
log "Starting servers..."

for port in 27015 27016 27017 27018 27019; do
    n=$((port - 27014))
    if [ $n -eq 1 ]; then
        SERVER_EXEC="dodserver"
    else
        SERVER_EXEC="dodserver$n"
    fi

    cd ~/dod-$port
    if ./$SERVER_EXEC start >/dev/null 2>&1; then
        log "Started $SERVER_EXEC (port $port)"
    else
        log "FAILED to start $SERVER_EXEC (port $port)"
    fi
    sleep 3
done

# Verify servers are running
sleep 5
RUNNING=$(pgrep -c hlds_linux 2>/dev/null || echo "0")
RUNNING=${RUNNING//[^0-9]/}  # Strip non-numeric chars
RUNNING=${RUNNING:-0}
log "Verification: $RUNNING/5 servers running"

# Identify any failed ports
FAILED_PORTS=""
if [ "$RUNNING" -ne 5 ]; then
    for port in 27015 27016 27017 27018 27019; do
        if ! pgrep -f "\-port $port " >/dev/null 2>&1; then
            FAILED_PORTS="$FAILED_PORTS $port"
        fi
    done
fi

# ============================================================================
# Update Discord Message with Final Status
# ============================================================================
FOOTER_TIMESTAMP=$(TZ='America/New_York' date '+%m/%d/%Y %I:%M %p EST')

if [ "$RUNNING" -eq 5 ]; then
    FINAL_TITLE="$KTP_EMOJI Server Restart Complete"
    FINAL_DESC="All 5 game servers restarted successfully."
    FINAL_COLOR=$COLOR_GREEN
elif [ "$RUNNING" -gt 0 ]; then
    FINAL_TITLE="$KTP_EMOJI Server Restart - Partial"
    FINAL_DESC="$RUNNING/5 servers restarted.\\n**Failed ports:**$FAILED_PORTS"
    FINAL_COLOR=$COLOR_ORANGE
else
    FINAL_TITLE="$KTP_EMOJI Server Restart Failed"
    FINAL_DESC="All servers failed to restart!"
    FINAL_COLOR=$COLOR_RED
fi

log "Updating Discord messages with final status..."
if [ -n "$MSG_ID_KTP" ]; then
    edit_discord_embed "$CHANNEL_KTP" "$MSG_ID_KTP" "$FINAL_TITLE" "$FINAL_DESC" "$FINAL_COLOR" "$SERVER_NAME - $FOOTER_TIMESTAMP"
fi
if [ -n "$MSG_ID_EXT" ]; then
    edit_discord_embed "$CHANNEL_EXTERNAL" "$MSG_ID_EXT" "$FINAL_TITLE" "$FINAL_DESC" "$FINAL_COLOR" "$SERVER_NAME - $FOOTER_TIMESTAMP"
fi

log "Scheduled restart complete. $RUNNING/5 servers running."

# Cron will be restored by trap on EXIT
