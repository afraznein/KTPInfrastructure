#!/bin/bash
# Runs once after the kernel reboot, reports the outcome, then disables itself.
set -uo pipefail
LOG=/var/log/ktp-kernel-reboot.log
ts(){ TZ=America/New_York date '+%Y-%m-%d %H:%M:%S %Z'; }
. /etc/ktp/discord-relay.conf 2>/dev/null || true
CH="${ALERT_CHANNEL:-1497957091107668070}"
sleep 120   # let services settle
K=$(uname -r)
SVC=""; BAD=0
for s in mysql nginx ktp-ac-api ktp-file-distributor hltv-api hlstatsx hltv-demo-renamer fail2ban auditd vsftpd; do
  st=$(systemctl is-active "$s" 2>/dev/null); SVC="$SVC$s=$st "
  [ "$st" = "active" ] || BAD=$((BAD+1))
done
HLTV=$(systemctl list-units 'hltv@*' --state=active --no-legend 2>/dev/null | wc -l)
[ "$HLTV" -ge 24 ] || BAD=$((BAD+1))
FAILED=$(systemctl --failed --no-legend | wc -l)
OK=$([ "$K" = "6.8.0-138-generic" ] && echo yes || echo NO)
[ "$OK" = "yes" ] || BAD=$((BAD+1))
DESC=$(printf 'Kernel: **%s** (expected 6.8.0-138-generic: %s)\nHLTV proxies active: **%s/24**\nFailed units: **%s**\n%s' "$K" "$OK" "$HLTV" "$FAILED" "$SVC")
COLOR=5763719; [ "$BAD" -gt 0 ] && COLOR=15548997
p=$(jq -n --arg ch "$CH" --arg t "KTP data server post-reboot report" --arg d "$DESC" --argjson c "$COLOR" \
  --arg f "ktp-post-reboot-verify @ $(ts)" '{channelId:$ch,embeds:[{title:$t,description:$d,color:$c,footer:{text:$f}}]}')
curl -sS -o /dev/null -X POST "${RELAY_URL:-}" -H "X-Relay-Auth: ${AUTH_SECRET:-}" -H 'Content-Type: application/json' -d "$p" || true
echo "[$(ts)] post-reboot: kernel=$K bad=$BAD hltv=$HLTV failed=$FAILED" >>"$LOG"
systemctl disable ktp-post-reboot-verify.service >/dev/null 2>&1
