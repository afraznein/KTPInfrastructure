#!/bin/bash
# lan-deploy.sh — single-config-driven KTP LAN deployment orchestrator.
#
# Reads lan-deploy.conf (default ./lan-deploy.conf, or path passed as arg),
# then runs each provision script in order with the right flags/env.
# Phases are individually idempotent — re-running after a partial failure
# is safe.
#
# Usage:
#   sudo ./lan-deploy.sh [config-file]
#   sudo YES=1 ./lan-deploy.sh   # skip the "Proceed?" prompt
#
# Pre-requisites the operator must handle before running:
#   - Fresh Ubuntu 22.04 or 24.04 host with internet access (LinuxGSM
#     bootstrap requires SteamCMD to fetch DoD game files).
#   - KTP artifacts pre-staged at ARTIFACTS_PATH (see lan-deploy.conf).
#   - HLTV binaries: this script does NOT install them. After it finishes,
#     copy them to /home/hltvserver/hlds/ and run `su - hltvserver -c './hltv-ctl.sh start'`.
#   - (Optional) Game files at /var/www/fastdl/dod/ for FastDL.

set -eu -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF=${1:-./lan-deploy.conf}

if [ "$EUID" -ne 0 ]; then
    echo "ERROR: must run as root (provisioning modifies system state)" >&2
    exit 1
fi

if [ ! -f "$CONF" ]; then
    echo "ERROR: config not found: $CONF" >&2
    echo "       cp $SCRIPT_DIR/lan-deploy.conf.example ./lan-deploy.conf" >&2
    echo "       edit it, then re-run." >&2
    exit 1
fi

# shellcheck disable=SC1090
source "$CONF"

# Validate required keys
missing=()
for var in LAN_IP ARTIFACTS_PATH LIBSTEAM_API_PATH; do
    [ -z "${!var:-}" ] && missing+=("$var")
done
if [ ${#missing[@]} -gt 0 ]; then
    echo "ERROR: required keys missing/empty in $CONF: ${missing[*]}" >&2
    exit 1
fi
[ -d "$ARTIFACTS_PATH" ]      || { echo "ERROR: ARTIFACTS_PATH not a directory: $ARTIFACTS_PATH" >&2; exit 1; }
[ -f "$LIBSTEAM_API_PATH" ]   || { echo "ERROR: LIBSTEAM_API_PATH not a file: $LIBSTEAM_API_PATH" >&2; exit 1; }
if [ -n "${HLTV_BINARIES_PATH:-}" ]; then
    [ -d "$HLTV_BINARIES_PATH" ]              || { echo "ERROR: HLTV_BINARIES_PATH not a directory: $HLTV_BINARIES_PATH" >&2; exit 1; }
    [ -f "$HLTV_BINARIES_PATH/hlds_linux" ]   || { echo "ERROR: HLTV_BINARIES_PATH lacks hlds_linux: $HLTV_BINARIES_PATH" >&2; exit 1; }
fi
if [ -n "${HLSTATSX_SOURCE_PATH:-}" ]; then
    [ -d "$HLSTATSX_SOURCE_PATH" ]                       || { echo "ERROR: HLSTATSX_SOURCE_PATH not a directory: $HLSTATSX_SOURCE_PATH" >&2; exit 1; }
    [ -f "$HLSTATSX_SOURCE_PATH/scripts/hlstats.pl" ]    || { echo "ERROR: HLSTATSX_SOURCE_PATH lacks scripts/hlstats.pl: $HLSTATSX_SOURCE_PATH" >&2; exit 1; }
    [ -f "$HLSTATSX_SOURCE_PATH/sql/install.sql" ]       || { echo "ERROR: HLSTATSX_SOURCE_PATH lacks sql/install.sql (use scripts/package-hlstatsx-bundle.sh)" >&2; exit 1; }
fi
if [ -n "${FASTDL_FILES_PATH:-}" ]; then
    [ -d "$FASTDL_FILES_PATH" ] || { echo "ERROR: FASTDL_FILES_PATH not a directory: $FASTDL_FILES_PATH" >&2; exit 1; }
fi

# Defaults for everything else (matches lan-deploy.conf.example)
TIMEZONE="${TIMEZONE:-America/New_York}"
SERVER_NAME_PREFIX="${SERVER_NAME_PREFIX:-KTP LAN}"
SV_PASSWORD="${SV_PASSWORD:-ktplan}"
NUM_INSTANCES="${NUM_INSTANCES:-5}"
BASE_PORT="${BASE_PORT:-27015}"
HLTV_BASE_PORT="${HLTV_BASE_PORT:-27020}"
ENABLE_DATASERVER="${ENABLE_DATASERVER:-true}"
ENABLE_NETDATA="${ENABLE_NETDATA:-false}"

cat <<SUMMARY
========================================
KTP LAN Deployment Plan
========================================
Host:                  $(hostname -s) (binding to $LAN_IP)
Timezone:              $TIMEZONE
Game servers:          $NUM_INSTANCES instances on ports $BASE_PORT-$((BASE_PORT + NUM_INSTANCES - 1))
HLTV ports:            $HLTV_BASE_PORT-$((HLTV_BASE_PORT + NUM_INSTANCES - 1))
Server name prefix:    $SERVER_NAME_PREFIX
Join password:         $SV_PASSWORD
Artifacts:             $ARTIFACTS_PATH
libsteam_api.so:       $LIBSTEAM_API_PATH
HLTV binaries:         ${HLTV_BINARIES_PATH:-(unset — manual copy required after install)}
HLStatsX bundle:       ${HLSTATSX_SOURCE_PATH:-(unset — HLStatsX left manual)}
FastDL files:          ${FASTDL_FILES_PATH:-(unset — manual copy to /var/www/fastdl/dod/)}

Co-located dataserver: $ENABLE_DATASERVER
Netdata:               $ENABLE_NETDATA
Discord relay:         $([ -n "${DISCORD_RELAY_URL:-}" ] && echo enabled || echo disabled)
Discord fleet-health:  $([ -n "${DISCORD_WEBHOOK_FLEET_HEALTH:-}" ] && echo enabled || echo disabled)
========================================
SUMMARY

if [ "${YES:-0}" != "1" ]; then
    read -r -p "Proceed? [y/N] " confirm
    case "$confirm" in
        y|Y|yes|YES) ;;
        *) echo "Aborted."; exit 0 ;;
    esac
fi

log_phase() {
    echo
    echo "======================================================================"
    echo "  $1"
    echo "======================================================================"
}

# ----------------------------------------------------------------------------
# Phase 1: provision-gameserver.sh — host hardening, kernel, sysctls, services
# ----------------------------------------------------------------------------
log_phase "Phase 1: host hardening (provision-gameserver.sh)"
PROV_FLAGS=(-y --num-servers "$NUM_INSTANCES")
[ "$ENABLE_NETDATA" != "true" ] && PROV_FLAGS+=(--no-netdata)
# Co-located HLTV is set up by Phase 4 (provision-lan-dataserver.sh), not by
# the gameserver script's --with-hltv flag, so we omit --with-hltv here.
TIMEZONE="$TIMEZONE" bash "$SCRIPT_DIR/provision-gameserver.sh" "${PROV_FLAGS[@]}"

# ----------------------------------------------------------------------------
# Phase 2: install-linuxgsm.sh — LinuxGSM bootstrap + 5 DoD instances
# ----------------------------------------------------------------------------
log_phase "Phase 2: LinuxGSM bootstrap (install-linuxgsm.sh)"
if [ -d "/home/dodserver/dod-${BASE_PORT}/serverfiles/dod" ]; then
    echo "LinuxGSM already installed at /home/dodserver/dod-${BASE_PORT} — skipping."
else
    su -l dodserver -c "YES=1 bash $SCRIPT_DIR/install-linuxgsm.sh $LAN_IP"
fi

# ----------------------------------------------------------------------------
# Phase 3: clone-ktp-stack.sh — deploy KTP stack on top of LinuxGSM
# ----------------------------------------------------------------------------
log_phase "Phase 3: KTP stack deployment (clone-ktp-stack.sh)"
CLONE_FLAGS=(
    --ip "$LAN_IP"
    --instances "$NUM_INSTANCES"
    --base-port "$BASE_PORT"
    --hltv-base-port "$HLTV_BASE_PORT"
    --libsteam-api "$LIBSTEAM_API_PATH"
    --server-name "$SERVER_NAME_PREFIX"
    --sv-password "$SV_PASSWORD"
    --data-server-ip "$LAN_IP"
)
[ -n "${DISCORD_RELAY_URL:-}" ]    && CLONE_FLAGS+=(--relay-url "$DISCORD_RELAY_URL")
[ -n "${DISCORD_RELAY_SECRET:-}" ] && CLONE_FLAGS+=(--relay-secret "$DISCORD_RELAY_SECRET")
# Quote args safely when crossing the su boundary.
CLONE_CMD=$(printf '%q ' bash "$SCRIPT_DIR/clone-ktp-stack.sh" "$ARTIFACTS_PATH" "${CLONE_FLAGS[@]}")
su -l dodserver -c "$CLONE_CMD"

# ----------------------------------------------------------------------------
# Phase 4 (optional): provision-lan-dataserver.sh — MySQL + HLTV + FastDL
# ----------------------------------------------------------------------------
if [ "$ENABLE_DATASERVER" = "true" ]; then
    log_phase "Phase 4: co-located dataserver (provision-lan-dataserver.sh)"
    YES=1 \
    TIMEZONE="$TIMEZONE" \
    MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD:-}" \
    HLSTATSX_DB_PASSWORD="${HLSTATSX_DB_PASSWORD:-}" \
    HLTV_ADMIN_PASSWORD="${HLTV_ADMIN_PASSWORD:-}" \
    HLTV_PROXY_PASSWORD="${HLTV_PROXY_PASSWORD:-}" \
    HLTV_BASE_PORT="$HLTV_BASE_PORT" \
    NUM_HLTV_INSTANCES="$NUM_INSTANCES" \
    HLTV_BINARIES_PATH="${HLTV_BINARIES_PATH:-}" \
    HLSTATSX_SOURCE_PATH="${HLSTATSX_SOURCE_PATH:-}" \
    FASTDL_FILES_PATH="${FASTDL_FILES_PATH:-}" \
        bash "$SCRIPT_DIR/provision-lan-dataserver.sh"
else
    log_phase "Phase 4: skipped (ENABLE_DATASERVER=false — dataserver lives elsewhere)"
fi

# ----------------------------------------------------------------------------
# Phase 5: seed /etc/ktp/fleet-health.conf with LAN-specific values
# ----------------------------------------------------------------------------
log_phase "Phase 5: /etc/ktp/fleet-health.conf"
mkdir -p /etc/ktp
cat > /etc/ktp/fleet-health.conf <<FH
# Generated by lan-deploy.sh on $(date -Iseconds)
WEBHOOK_URL="${DISCORD_WEBHOOK_FLEET_HEALTH:-}"
MENTION_USER_ID="${DISCORD_MENTION_USER_ID:-}"
BASE_PORT=$BASE_PORT
NUM_INSTANCES=$NUM_INSTANCES
LOCATION="${SERVER_NAME_PREFIX}"
FH
chown root:dodserver /etc/ktp/fleet-health.conf
chmod 640 /etc/ktp/fleet-health.conf
if [ -z "${DISCORD_WEBHOOK_FLEET_HEALTH:-}" ]; then
    echo "WEBHOOK_URL is empty — fleet-health runs in silent monitoring mode."
fi

# ----------------------------------------------------------------------------
echo
echo "========================================"
echo "LAN deployment complete!"
echo "========================================"
echo
echo "Status:"
echo "  - ${NUM_INSTANCES} game server instances staged at ~/dod-* (port ${BASE_PORT}+)"
echo "  - Scheduled restart cron installed (3 AM local time daily)"
echo "  - ktp-fleet-health.sh cron installed (every minute)"
if [ "$ENABLE_DATASERVER" = "true" ]; then
    echo "  - Dataserver credentials: /root/ktp-dataserver-credentials.txt"
fi
echo
echo "Next steps (manual — this script does NOT do them):"
step=1
printf "  %d. Verify game servers:    su - dodserver -c '~/restart-all-servers.sh && ~/status.sh'\n" $step
if [ "$ENABLE_DATASERVER" = "true" ]; then
    if [ -z "${HLTV_BINARIES_PATH:-}" ]; then
        step=$((step + 1))
        printf "  %d. Copy HLTV binaries:     /home/hltvserver/hlds/ (HLTV_BINARIES_PATH was unset)\n" $step
        printf "                              then 'su - hltvserver -c ./hltv-ctl.sh start'\n"
    else
        step=$((step + 1))
        printf "  %d. Start HLTV:             su - hltvserver -c './hltv-ctl.sh start'  (binaries already staged)\n" $step
    fi
    if [ -z "${HLSTATSX_SOURCE_PATH:-}" ]; then
        step=$((step + 1))
        printf "  %d. HLStatsX setup:         see /opt/hlstatsx/INSTALL.txt (HLSTATSX_SOURCE_PATH was unset)\n" $step
    else
        printf "                              HLStatsX is running on UDP 27500 (hlstatsx.service)\n"
    fi
    if [ -z "${FASTDL_FILES_PATH:-}" ]; then
        step=$((step + 1))
        printf "  %d. FastDL files:           copy assets to /var/www/fastdl/dod/ (FASTDL_FILES_PATH was unset)\n" $step
    fi
fi
echo
