#!/usr/bin/env bash
# lan-change-ip.sh — retarget the whole LAN stack to a new bind IP, fast.
#
# The venue-day tool. A full `lan-deploy.sh` re-run CANNOT change the IP on a
# live box: clone-ktp-stack refuses to run while any hlds_linux is up, and a
# re-run's Phase 1 re-installs the LinuxGSM monitor cron, which revives the
# servers before Phase 3 — a catch-22. So instead of re-deploying, this script
# rewrites only the IP-bearing config values in place, updates the stats DB, and
# restarts the servers. No binaries touched, keys untouched.
#
# Usage (as root on the all-in-one LAN box):
#   sudo ./lan-change-ip.sh <new-ip> [--dry-run]
#
# It reads the CURRENT ip from lan-deploy.conf (LAN_IP) and replaces that exact
# string everywhere it appears in the stack's configs. Idempotent.

set -eu -o pipefail

NEW_IP=""; DRY=0; FORCE=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --force)   FORCE=1 ;;
    -*)        echo "unknown option: $a" >&2; exit 1 ;;
    *)         NEW_IP="$a" ;;
  esac
done

RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GRN}[INFO]${NC} $1"; }
warn() { echo -e "${YLW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1" >&2; }

[ "$EUID" -eq 0 ] || { err "must run as root"; exit 1; }
[ -n "$NEW_IP" ]  || { err "usage: sudo $0 <new-ip> [--dry-run]"; exit 1; }
# basic IPv4 sanity
echo "$NEW_IP" | grep -qE '^([0-9]{1,3}\.){3}[0-9]{1,3}$' || { err "'$NEW_IP' is not a valid IPv4"; exit 1; }

# Refuse to point servers at an IP that isn't on a local interface: hlds crashes
# on the bind failure (SIGSEGV + coredump), not a clean exit — a typo would take
# the whole fleet down. --force overrides (e.g. the IP is about to be assigned).
# Dry-run skips the check so you can preview from anywhere.
if [ "$DRY" = 0 ] && [ "$FORCE" = 0 ]; then
    if ! ip -o -4 addr show 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | grep -qx "$NEW_IP"; then
        err "$NEW_IP is not on any local interface — hlds would crash on the bind."
        err "Assign it first (DHCP/static) then re-run, or pass --force if it's coming up."
        err "Local IPs now: $(ip -o -4 addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | tr '\n' ' ')"
        exit 1
    fi
fi

CONF=${LAN_DEPLOY_CONF:-/opt/ktp/KTPInfrastructure/provision/lan-deploy.conf}
[ -f "$CONF" ] || { err "lan-deploy.conf not found at $CONF (set LAN_DEPLOY_CONF)"; exit 1; }
OLD_IP=$(grep -E '^LAN_IP=' "$CONF" | head -1 | cut -d= -f2 | tr -d '"' | tr -d "'")
[ -n "$OLD_IP" ] || { err "could not read current LAN_IP from $CONF"; exit 1; }

log "Retargeting the LAN stack:  ${OLD_IP}  ->  ${NEW_IP}"
[ "$OLD_IP" = "$NEW_IP" ] && { warn "old == new; nothing to do."; exit 0; }
[ "$DRY" = 1 ] && warn "DRY RUN — no changes will be written."

# Config trees that may carry the game/bind IP. We grep for the exact OLD_IP so
# we never touch the machine's routable/internet IP or anything unrelated.
TREES=(
  /home/dodserver/dod-*/serverfiles/dod/dodserver.cfg
  /home/dodserver/dod-*/lgsm/config-lgsm/dodserver/dodserver*.cfg
  /home/dodserver/dod-*/serverfiles/dod/addons/ktpamx/configs/hltv_recorder.ini
  /home/hltvserver/hlds/configs/hltv-*.cfg
  /home/hltvserver/generate-hltv-configs.sh
  /srv/ktpdata/warmup/serverfiles/dod/dodserver.cfg
  /srv/ktpdata/warmup/lgsm/config-lgsm/dodserver/dodserver*.cfg
  "$CONF"
)

log "Files containing ${OLD_IP}:"
CHANGED=0
for pat in "${TREES[@]}"; do
  for f in $pat; do
    [ -f "$f" ] || continue
    n=$(grep -c "$OLD_IP" "$f" 2>/dev/null) || n=0
    [ "${n:-0}" -gt 0 ] || continue
    echo "    $f  ($n)"
    if [ "$DRY" = 0 ]; then
      sed -i "s/${OLD_IP}/${NEW_IP}/g" "$f"
      CHANGED=$((CHANGED + 1))
    fi
  done
done
log "Config files rewritten: $CHANGED"

# Stats DB: hlstats_Servers.address (root uses auth_socket -> plain `mysql`).
if command -v mysql >/dev/null 2>&1; then
  ROWS=$(mysql -N hlstatsx -e "SELECT COUNT(*) FROM hlstats_Servers WHERE address='${OLD_IP}'" 2>/dev/null || echo 0)
  log "hlstats_Servers rows on ${OLD_IP}: ${ROWS}"
  if [ "$DRY" = 0 ] && [ "${ROWS:-0}" -gt 0 ]; then
    mysql hlstatsx -e "UPDATE hlstats_Servers SET address='${NEW_IP}' WHERE address='${OLD_IP}'"
    log "hlstats_Servers updated -> ${NEW_IP}"
  fi
fi

if [ "$DRY" = 1 ]; then
  warn "DRY RUN complete — re-run without --dry-run to apply, then restart servers."
  exit 0
fi

# Restart to bind the new IP. Competitive via LinuxGSM, warmup, HLTV via systemd.
log "Restarting competitive servers..."
su - dodserver -c '~/restart-all-servers.sh' 2>&1 | tail -3 || warn "restart-all-servers returned non-zero"
if [ -x /srv/ktpdata/warmup/dodserver ]; then
  log "Restarting warmup..."
  su - dodserver -c '/srv/ktpdata/warmup/dodserver stop; /srv/ktpdata/warmup/dodserver start' 2>&1 | tail -2 || true
fi
log "Restarting HLTV proxies..."
systemctl restart hltv@27020 hltv@27021 hltv@27022 hltv@27023 hltv@27024 2>/dev/null || warn "hltv restart issue"

echo
log "Done. Verify:"
echo "    ss -ulnp | grep -E ':270(1[5-9]|2[0-4]|50)'      # servers bound to ${NEW_IP}"
echo "    <a client should join the game servers on ${NEW_IP}>"
echo "    (HLTV reconnects automatically with its stored serverpassword)"
