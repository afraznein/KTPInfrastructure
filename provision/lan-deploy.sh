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

# Phase-3 preflight: clone-ktp-stack.sh is gitignored (it can carry embedded
# secrets), so a fresh clone has only the .example. Fail HERE, before Phases
# 1-2 mutate the host, instead of dying with bash 127 mid-deploy.
if [ ! -f "$SCRIPT_DIR/clone-ktp-stack.sh" ]; then
    echo "ERROR: $SCRIPT_DIR/clone-ktp-stack.sh not found (it is gitignored — fresh clones ship only the .example)." >&2
    echo "       cp '$SCRIPT_DIR/clone-ktp-stack.sh.example' '$SCRIPT_DIR/clone-ktp-stack.sh'" >&2
    echo "       Review it (flag-driven values are fine as-is for LAN), then re-run." >&2
    exit 1
fi
# Phases 2-3 run as dodserver via su — a repo cloned under /root is unreadable
# there and fails confusingly partway through. Check up front.
if ! su -l dodserver -c "test -r $(printf '%q' "$SCRIPT_DIR/clone-ktp-stack.sh")" 2>/dev/null; then
    if id dodserver &>/dev/null; then
        echo "ERROR: the dodserver user cannot read $SCRIPT_DIR (repo under /root?)." >&2
        echo "       Move/clone the repo somewhere world-readable (e.g. /opt/ktp) and re-run." >&2
        exit 1
    fi
    # dodserver doesn't exist yet (Phase 1 creates it) — check world-readability
    # of the path components instead so the post-Phase-1 su calls will work.
    case "$SCRIPT_DIR" in
        /root/*|/root)
            echo "ERROR: repo lives under /root — Phases 2-3 run as dodserver and cannot read it." >&2
            echo "       Move/clone the repo somewhere world-readable (e.g. /opt/ktp) and re-run." >&2
            exit 1 ;;
    esac
fi

# Defaults for everything else (matches lan-deploy.conf.example)
# gen_pw is pipefail-safe: a bounded head feeds tr, so tr exits on EOF instead
# of taking SIGPIPE when the tail head closes (under this script's
# `set -eu -o pipefail`, the naive `tr </dev/urandom | head -c 32` form dies
# with a silent exit 141 on EVERY default-config run). 512 random bytes yield
# ~300 alnum chars — comfortably ≥ the 32 we keep, and all writes fit one
# pipe buffer.
gen_pw() { head -c 512 /dev/urandom | tr -dc 'A-Za-z0-9' | head -c 32; }
TIMEZONE="${TIMEZONE:-America/New_York}"
SERVER_NAME_PREFIX="${SERVER_NAME_PREFIX:-KTP LAN}"
SV_PASSWORD="${SV_PASSWORD:-}"
# Secrets: never leave these at a well-known value. Resolution order:
# conf/env > previous run's credentials file > fresh generation. Sourcing the
# previous run's values keeps re-runs convergent — regenerating on a re-run
# would (a) record a dodserver password that was never applied (chpasswd only
# runs at user creation) while Phase 4's creds rewrite erases the record of
# the working one, and (b) churn the HLTV key out from under written inis.
CREDS_FILE=/root/ktp-dataserver-credentials.txt
if [ -f "$CREDS_FILE" ]; then
    while IFS='=' read -r k v; do
        v="${v%%  \#*}"   # strip the trailing "  # generated ..." comment form
        case "$k" in
            HLTV_API_KEY)
                if [ -z "${HLTV_API_KEY:-}" ]; then HLTV_API_KEY="$v"; fi ;;
            DODSERVER_PASSWORD)
                if [ -z "${DODSERVER_PASSWORD:-}" ]; then DODSERVER_PASSWORD="$v"; fi ;;
            RCON_PASSWORD)
                if [ -z "${RCON_PASSWORD:-}" ]; then RCON_PASSWORD="$v"; fi ;;
        esac
    done < "$CREDS_FILE"
fi
HLTV_API_KEY="${HLTV_API_KEY:-$(gen_pw)}"
DODSERVER_PASSWORD="${DODSERVER_PASSWORD:-$(gen_pw)}"
# RCON password for the game servers. Generated once and persisted so an onsite
# re-run (new LAN_IP) re-renders the cfgs with the SAME rcon rather than churning it.
RCON_PASSWORD="${RCON_PASSWORD:-$(gen_pw)}"
# SV_PASSWORD can't be generated — players have to type it — so it must be set
# explicitly. It previously defaulted to the literal "REDACTED" left behind by
# the history scrub, which deployed as a working join password and printed as
# "Join password: REDACTED" in the summary, reading like sanitized output.
case "${SV_PASSWORD}" in
    "" )
        # Empty is a deliberate "open server" config — no join password. clone-ktp-stack.sh
        # already treats an empty sv-password as open; competitive access is gated by the
        # .ktp match password, not sv_password.
        echo "NOTE: SV_PASSWORD empty — servers deploy OPEN (no join password)." ;;
    REDACTED|REDACTED_*|CHANGEME|changeme )
        echo "ERROR: SV_PASSWORD is still the placeholder '${SV_PASSWORD}'." >&2
        echo "Set a real value in lan-deploy.conf or the environment." >&2
        exit 1 ;;
    *[!A-Za-z0-9]* )
        echo "ERROR: SV_PASSWORD must be alphanumeric ([A-Za-z0-9])." >&2
        echo "It is typed by players and substituted into dodserver.cfg via sed —" >&2
        echo "a '&', '|', or '\\' would silently corrupt the password or break the deploy." >&2
        exit 1 ;;
esac
NUM_INSTANCES="${NUM_INSTANCES:-5}"
BASE_PORT="${BASE_PORT:-27015}"
# HLTV starts right after the last game port so it never collides with the game
# range. For 5 servers this is 27020 (unchanged); for 6 it becomes 27021.
HLTV_BASE_PORT="${HLTV_BASE_PORT:-$((BASE_PORT + NUM_INSTANCES))}"
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
Join password:         ${SV_PASSWORD:-(open — no join password)}
Artifacts:             $ARTIFACTS_PATH
libsteam_api.so:       $LIBSTEAM_API_PATH
HLTV binaries:         ${HLTV_BINARIES_PATH:-(unset — manual copy required after install)}
HLStatsX bundle:       ${HLSTATSX_SOURCE_PATH:-(unset — HLStatsX left manual)}
FastDL files:          ${FASTDL_FILES_PATH:-(unset — manual copy to /var/www/fastdl/dod/)}
DoD base content:      ${DOD_BASE_PATH:-(unset — STOCK maps only; custom KTP maps/overviews NOT deployed)}

Co-located dataserver: $ENABLE_DATASERVER
HLTV API key:          (set — plumbed to hltv-api + every hltv_recorder.ini; recorded in /root/ktp-dataserver-credentials.txt)
dodserver password:    (set — recorded in /root/ktp-dataserver-credentials.txt)
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
# Convenience files: an IP helper + a shortcut to this conf, so the onsite
# "set LAN_IP and re-apply" step is easy to find. Terminal helpers land in
# root's, dodserver's, and the GUI login user's home dirs; the clickable
# desktop launchers go to the GUI user's Desktop only. Called AFTER Phase 1 so
# the dodserver user exists.
# ----------------------------------------------------------------------------
install_convenience_files() {
    local ipsh="$SCRIPT_DIR/lan-show-ip.sh"
    local adminsh="$SCRIPT_DIR/lan-admin.sh"
    local conf="$SCRIPT_DIR/lan-deploy.conf"
    local u home spec sub rest name icon dfile
    # Desktop launcher specs: subcommand|Display Name|Icon. All admin actions run
    # via `taskset -c 0,1` so they stay on the housekeeping cores (cpu0/cpu1) and
    # never touch the isolated game cores (2-7). isolcpus already confines them;
    # the taskset makes it explicit and survives an isolation-config change.
    local launchers=(
        "menu|KTP LAN Admin|utilities-terminal"
        "details|Server Details (all)|network-server"
        "status|Live Status|utilities-system-monitor"
        "console|Attach Console|utilities-terminal"
        "restart|Restart Servers|view-refresh"
        "hltv|HLTV Status|camera-video"
        "warmup|Warmup Server|applications-games"
        "perf|Perf Monitor|utilities-system-monitor"
        "ip|Show LAN IP|network-wired"
        "changeip|Change LAN IP|network-transmit"
        "editconf|Edit LAN Config|text-editor"
    )
    # The GUI login user is the install-time desktop account (first UID-1000
    # user), NOT root/dodserver. getent MUST be set -e-safe: a missing user
    # exits 2 and pipefail would otherwise abort the whole deploy silently.
    local gui_user; gui_user=$(getent passwd 1000 | cut -d: -f1) || gui_user=""
    local users="root dodserver"
    [ -n "$gui_user" ] && [ "$gui_user" != root ] && [ "$gui_user" != dodserver ] && users="$users $gui_user"
    for u in $users; do
        home=$(getent passwd "$u" | cut -d: -f6) || home=""
        [ -n "$home" ] && [ -d "$home" ] || continue
        # Helpers in the home dir (headless-safe).
        [ -f "$ipsh" ]    && { install -m 755 "$ipsh" "$home/lan-show-ip.sh"; [ "$u" != root ] && chown "$u:$u" "$home/lan-show-ip.sh"; }
        [ -f "$adminsh" ] && { install -m 755 "$adminsh" "$home/lan-admin.sh"; [ "$u" != root ] && chown "$u:$u" "$home/lan-admin.sh"; }
        ln -sf "$conf" "$home/lan-deploy.conf"
        # Clickable desktop launchers only for the GUI login user (the one who
        # logs into GNOME); root/dodserver have no session. Create ~/Desktop —
        # a fresh GNOME that hasn't logged in yet may not have it.
        [ -n "$gui_user" ] && [ "$u" = "$gui_user" ] || continue
        mkdir -p "$home/Desktop"; chown "$u:$u" "$home/Desktop" 2>/dev/null
        ln -sf "$conf" "$home/Desktop/lan-deploy.conf"
        chown -h "$u:$u" "$home/Desktop/lan-deploy.conf" 2>/dev/null
        # lan-admin.sh must run AS dodserver — it reads dodserver's dod-* trees,
        # which useradd -m makes non-world-readable. If the GUI user IS dodserver,
        # run it directly; otherwise go through a NOPASSWD sudo -u dodserver.
        local exec_body
        if [ "$u" = dodserver ]; then
            exec_body="taskset -c 0,1 /home/dodserver/lan-admin.sh"
        else
            exec_body="taskset -c 0,1 sudo -u dodserver -H /home/dodserver/lan-admin.sh"
            local sudoers=/etc/sudoers.d/ktp-lan-admin
            echo "$u ALL=(dodserver) NOPASSWD: /home/dodserver/lan-admin.sh" > "$sudoers.tmp"
            if visudo -cf "$sudoers.tmp" >/dev/null 2>&1; then
                install -m 440 "$sudoers.tmp" "$sudoers"
            else
                log_warn "sudoers validation failed — desktop launchers will prompt for the dodserver password"
            fi
            rm -f "$sudoers.tmp"
        fi
        for spec in "${launchers[@]}"; do
            sub="${spec%%|*}"; rest="${spec#*|}"; name="${rest%|*}"; icon="${rest##*|}"
            dfile="$home/Desktop/ktp-${sub}.desktop"
            # changeip needs ROOT (edits configs across users + the stats DB +
            # restarts systemd units), so it runs AS the GUI user and sudo-prompts
            # for their password — NOT through the dodserver NOPASSWD shim the
            # read-only commands use.
            local sub_exec="$exec_body"
            [ "$sub" = changeip ] && sub_exec="taskset -c 0,1 $home/lan-admin.sh"
            {
                echo "[Desktop Entry]"
                echo "Type=Application"
                echo "Name=$name"
                echo "Comment=KTP LAN admin: $sub"
                echo "Exec=gnome-terminal -- $sub_exec $sub"
                echo "Icon=$icon"
                echo "Terminal=false"
                echo "Categories=System;"
            } > "$dfile"
            chmod +x "$dfile"; chown "$u:$u" "$dfile"
            # Mark trusted so GNOME launches it without the "untrusted" prompt.
            su -l "$u" -c "gio set '$dfile' metadata::trusted true" 2>/dev/null || true
        done
    done
}

# ----------------------------------------------------------------------------
# Phase 1: provision-gameserver.sh — host hardening, kernel, sysctls, services
# ----------------------------------------------------------------------------
log_phase "Phase 1: host hardening (provision-gameserver.sh)"
PROV_FLAGS=(-y --num-servers "$NUM_INSTANCES" --password "$DODSERVER_PASSWORD")
[ "$ENABLE_NETDATA" != "true" ] && PROV_FLAGS+=(--no-netdata)
# Co-located HLTV is set up by Phase 4 (provision-lan-dataserver.sh), not by
# the gameserver script's --with-hltv flag, so we omit --with-hltv here.
TIMEZONE="$TIMEZONE" bash "$SCRIPT_DIR/provision-gameserver.sh" "${PROV_FLAGS[@]}"

# dodserver + the GUI user now exist — drop in the convenience helpers/launchers.
install_convenience_files

# ----------------------------------------------------------------------------
# Phase 2: install-linuxgsm.sh — LinuxGSM bootstrap + NUM_INSTANCES DoD instances
# ----------------------------------------------------------------------------
log_phase "Phase 2: LinuxGSM bootstrap (install-linuxgsm.sh)"
if [ -d "/home/dodserver/dod-${BASE_PORT}/serverfiles/dod" ]; then
    echo "LinuxGSM already installed at /home/dodserver/dod-${BASE_PORT} — skipping."
else
    su -l dodserver -c "YES=1 NUM_INSTANCES=$NUM_INSTANCES bash $SCRIPT_DIR/install-linuxgsm.sh $LAN_IP"
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
    --hltv-api-key "$HLTV_API_KEY"
    --rcon-password "$RCON_PASSWORD"
    --server-cfg-template "$SCRIPT_DIR/../config/lan/dodserver.cfg.example"
    --plugins-ini "$SCRIPT_DIR/../config/lan/plugins.ini"
    --modules-ini "$SCRIPT_DIR/../config/lan/modules.ini"
    --discord-ini "$SCRIPT_DIR/../config/lan/discord.ini"
)
[ -n "${DOD_BASE_PATH:-}" ]        && CLONE_FLAGS+=(--dod-base "$DOD_BASE_PATH")
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
    HLTV_API_KEY="$HLTV_API_KEY" \
    HLTV_BASE_PORT="$HLTV_BASE_PORT" \
    NUM_HLTV_INSTANCES="$NUM_INSTANCES" \
    HLTV_BINARIES_PATH="${HLTV_BINARIES_PATH:-}" \
    HLSTATSX_SOURCE_PATH="${HLSTATSX_SOURCE_PATH:-}" \
    FASTDL_FILES_PATH="${FASTDL_FILES_PATH:-}" \
    GAME_SERVER_IP="$LAN_IP" \
    GAME_BASE_PORT="$BASE_PORT" \
    GAME_SV_PASSWORD="$SV_PASSWORD" \
    HLTV_NAME_PREFIX="$SERVER_NAME_PREFIX" \
        bash "$SCRIPT_DIR/provision-lan-dataserver.sh"
else
    log_phase "Phase 4: skipped (ENABLE_DATASERVER=false — dataserver lives elsewhere)"
    echo "NOTE: game instances were configured with the HLTV API key recorded in"
    echo "      /root/ktp-dataserver-credentials.txt (HLTV_API_KEY=...) — set the"
    echo "      SAME key on the remote dataserver's hltv-api service."
fi

# Record the orchestrator-level secrets. Phase 4 writes the dataserver
# credentials file (including HLTV_API_KEY via env); append what only this
# script knows. Appended AFTER Phase 4 so its end-of-run rewrite can't
# clobber these lines.
CREDS_FILE=/root/ktp-dataserver-credentials.txt
umask 077
touch "$CREDS_FILE"; chmod 600 "$CREDS_FILE"
{
    echo "# lan-deploy.sh $(date -Iseconds)"
    echo "DODSERVER_PASSWORD=$DODSERVER_PASSWORD"
    grep -q "^HLTV_API_KEY=" "$CREDS_FILE" || echo "HLTV_API_KEY=$HLTV_API_KEY"
    grep -q "^RCON_PASSWORD=" "$CREDS_FILE" || echo "RCON_PASSWORD=$RCON_PASSWORD"
} >> "$CREDS_FILE"

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
# Phase 6: validate-map-assets.sh sanity check — flag maps with crash-risk
# asset misses BEFORE anyone tries to load them in-game. Informational only:
# exit-1 from the validator is logged but doesn't fail the deploy, since the
# operator may have intentional test maps that haven't been fully sourced yet.
# ----------------------------------------------------------------------------
log_phase "Phase 6: map asset validation"
VALIDATE_SH="$SCRIPT_DIR/../scripts/validate-map-assets.sh"
if [ -x "$VALIDATE_SH" ]; then
    if "$VALIDATE_SH" --maps-dir "/home/dodserver/dod-${BASE_PORT}/serverfiles/dod" --quiet; then
        echo "All staged maps pass crash-risk asset validation."
    else
        echo
        echo "Some maps reference assets missing on disk (see FAIL list above)."
        echo "Quarantine the failing .bsp files (mv to *.bsp.broken) or source the"
        echo "missing assets before loading those maps in-game."
        echo "Not failing the deploy — operator decision per map."
    fi
else
    echo "validate-map-assets.sh not found at $VALIDATE_SH — skipping"
fi

# ----------------------------------------------------------------------------
echo
echo "========================================"
echo "LAN deployment complete!"
echo "========================================"
echo
echo "**********************************************************************"
echo "  REBOOT REQUIRED before the servers are event-ready."
echo "  Phase 1 installed the lowlatency kernel + CPU isolation; neither"
echo "  takes effect until a reboot. After rebooting, HARD-VERIFY:"
echo "    uname -r                              # must end in -lowlatency"
echo "    cat /proc/cmdline                     # must contain isolcpus=<list Phase 1 logged> (2,3,4,5,6,7 on a 4c/8t box)"
echo "    systemctl is-active ktp-chrt.timer    # active"
echo "  If uname shows a GENERIC kernel, the GRUB default didn't take — run:"
echo "    grub-set-default 'Advanced options for Ubuntu>Ubuntu, with Linux <ver>-lowlatency'"
echo "    update-grub && reboot"
echo "**********************************************************************"
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
printf "  %d. Reboot + verify the lowlatency kernel booted (see the box above)\n" $step
step=$((step + 1))
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
