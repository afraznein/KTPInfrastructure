#!/bin/bash
# One-shot kernel reboot: 6.8.0-31-generic -> 6.8.0-138-generic.
# Aborts and retries tomorrow if anyone is playing -- a reboot here stops HLTV
# recording, stats ingest and AC uploads, so "nobody is on" is the precondition.
set -uo pipefail
LOG=/var/log/ktp-kernel-reboot.log
ts(){ TZ=America/New_York date '+%Y-%m-%d %H:%M:%S %Z'; }
say(){ echo "[$(ts)] $*" >>"$LOG"; }
. /etc/ktp/discord-relay.conf 2>/dev/null || true
CH="${ALERT_CHANNEL:-1497957091107668070}"
post(){ # $1 title  $2 desc  $3 color
  local p; p=$(jq -n --arg ch "$CH" --arg t "$1" --arg d "$2" --argjson c "$3" \
    --arg f "ktp-kernel-reboot @ $(ts)" \
    '{channelId:$ch,embeds:[{title:$t,description:$d,color:$c,footer:{text:$f}}]}')
  curl -sS -o /dev/null -X POST "${RELAY_URL:-}" -H "X-Relay-Auth: ${AUTH_SECRET:-}" \
       -H 'Content-Type: application/json' -d "$p" || true; }

FRAGS=$(mysql -N -B -e "select count(*) from hlstatsx.hlstats_Events_Frags where eventTime >= now() - interval 20 minute" 2>/dev/null || echo ERR)
DEMOS=$(find /home/hltvserver -name '*.dem' -mmin -15 2>/dev/null | wc -l)
say "activity check: frags_20m=$FRAGS demos_15m=$DEMOS"

if [ "$FRAGS" = "ERR" ]; then
  say "ABORT: could not query hlstatsx -- refusing to reboot on an unknown state"
  post "KTP data server reboot ABORTED" "Could not read hlstatsx to check for live play. **Not rebooting.** Will retry tomorrow 02:00 ET." 15548997; exit 0
fi
if [ "$FRAGS" -gt 0 ] || [ "$DEMOS" -gt 0 ]; then
  say "ABORT: activity present (frags=$FRAGS demos=$DEMOS) -- retrying tomorrow"
  post "KTP data server reboot deferred" "People are playing (frags/20m: **$FRAGS**, demos written/15m: **$DEMOS**). **Not rebooting.** Automatic retry tomorrow 02:00 ET." 16776960; exit 0
fi

say "idle confirmed -- disabling timer and rebooting into $(grep -o 'vmlinuz-[0-9][^ ]*' /boot/grub/grub.cfg | head -1)"
systemctl disable --now ktp-kernel-reboot.timer >>"$LOG" 2>&1
systemctl enable ktp-post-reboot-verify.service >>"$LOG" 2>&1
post "KTP data server rebooting now" "Idle confirmed (0 frags, 0 demos). Rebooting to take **6.8.0-138-generic** (from 6.8.0-31). A verification report follows in ~3 minutes." 5763719
sleep 5
systemctl reboot
