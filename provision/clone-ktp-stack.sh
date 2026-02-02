#!/bin/bash
# KTP Stack Deployment Script
# Deploys KTP binaries on top of existing LinuxGSM installation
#
# Usage: ./clone-ktp-stack.sh <ARTIFACTS_PATH> [OPTIONS]
#
# ARTIFACTS_PATH can be:
#   - Local directory: /path/to/artifacts/20260127
#   - HTTP URL: https://example.com/ktp-artifacts-20260127.tar.gz
#
# OPTIONS:
#   --dod-base <path>     Base DoD files tarball (REQUIRED for full deployment)
#                         Contains: maps, WADs, configs, models, sprites, sounds, mapcycle, motd
#                         Create with: scripts/package-dod-base.sh
#   --hostname <name>     Cluster hostname (e.g., "atlanta", "dallas", "denver")
#   --server-name <name>  Server display name prefix (default: "KTP DoD")
#   --ip <address>        Server IP address (configures LinuxGSM startparameters)
#   --instances <num>     Number of instances (default: 5)
#   --base-port <port>    Starting port number (default: 27015)
#   --libsteam-api <path> Path to KTP libsteam_api.so (76KB version)
#   --hltv-base-port <port> HLTV base port for this cluster (default: auto based on hostname)
#
# Run as: dodserver user
#
# This script:
# 1. (Optional) Deploys base DoD files (maps, configs, models, etc.)
# 2. Deploys KTP engine (hlds_linux, engine_i486.so)
# 3. Deploys KTPAMXX (dlls/, modules/)
# 4. Deploys plugins
# 5. Creates extension configuration
# 6. Configures game server hostnames (servernamedefault.cfg)
# 7. Configures LinuxGSM instance settings
# 8. Deploys KTP libsteam_api.so
# 9. Applies LinuxGSM tmux session fix (prevents random restarts)
# 10. Cleans up modules.ini (removes GLIBC 2.38 dependent modules)
# 11. Configures hltv_recorder.ini with correct HLTV ports
# 12. Cleans up server.cfg hostname conflicts
# 13. Deploys scheduled restart script and cron

set -e

# ============================================
# Parse Arguments
# ============================================
show_usage() {
    echo "Usage: $0 <ARTIFACTS_PATH> [OPTIONS]"
    echo ""
    echo "ARTIFACTS_PATH can be:"
    echo "  - Local directory: /path/to/artifacts/20260127"
    echo "  - HTTP URL: https://example.com/ktp-artifacts.tar.gz"
    echo ""
    echo "OPTIONS:"
    echo "  --dod-base <path>       Base DoD files (local tarball or HTTP URL)"
    echo "  --hostname <name>       Cluster hostname (e.g., 'atlanta', 'dallas')"
    echo "  --server-name <name>    Server display name prefix (default: 'KTP')"
    echo "  --ip <address>          Server IP address (required for proper monitoring)"
    echo "  --instances <num>       Number of instances (default: 5)"
    echo "  --base-port <port>      Starting port number (default: 27015)"
    echo "  --libsteam-api <path>   Path to KTP libsteam_api.so (76KB version)"
    echo "  --hltv-base-port <port> HLTV base port (default: auto based on hostname)"
    echo ""
    echo "Examples:"
    echo "  $0 /path/to/artifacts --hostname atlanta --ip 74.91.112.182"
    echo "  $0 /path/to/artifacts --hostname dallas --ip 74.91.114.195 --libsteam-api /path/to/libsteam_api.so"
    exit 1
}

if [ -z "$1" ] || [[ "$1" == --* ]]; then
    show_usage
fi

ARTIFACTS_SOURCE="$1"
shift

# Defaults
DOD_BASE_SOURCE=""
CLUSTER_HOSTNAME=""
SERVER_NAME_PREFIX=""
SERVER_NAME_EXPLICIT=false
SERVER_IP=""
NUM_INSTANCES=5
BASE_PORT=27015
LIBSTEAM_API_PATH=""

# Parse optional arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dod-base)
            DOD_BASE_SOURCE="$2"
            shift 2
            ;;
        --hostname)
            CLUSTER_HOSTNAME="$2"
            shift 2
            ;;
        --server-name)
            SERVER_NAME_PREFIX="$2"
            SERVER_NAME_EXPLICIT=true
            shift 2
            ;;
        --ip)
            SERVER_IP="$2"
            shift 2
            ;;
        --instances)
            NUM_INSTANCES="$2"
            shift 2
            ;;
        --base-port)
            BASE_PORT="$2"
            shift 2
            ;;
        --libsteam-api)
            LIBSTEAM_API_PATH="$2"
            shift 2
            ;;
        --hltv-base-port)
            HLTV_BASE_PORT="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            show_usage
            ;;
    esac
done

# Determine HLTV base port if not explicitly provided
# Atlanta: 27020-27024, Dallas: 27025-27029, Denver: 27030-27034
if [ -z "$HLTV_BASE_PORT" ]; then
    case "$CLUSTER_HOSTNAME" in
        atlanta) HLTV_BASE_PORT=27020 ;;
        dallas)  HLTV_BASE_PORT=27025 ;;
        denver)  HLTV_BASE_PORT=27030 ;;
        *)       HLTV_BASE_PORT="" ;;  # Unknown cluster, will skip HLTV config
    esac
fi

# Build server name prefix if not explicitly provided
if [ "$SERVER_NAME_EXPLICIT" = false ]; then
    if [ -n "$CLUSTER_HOSTNAME" ]; then
        # Capitalize first letter of hostname
        DISPLAY_HOSTNAME="$(echo "${CLUSTER_HOSTNAME:0:1}" | tr '[:lower:]' '[:upper:]')${CLUSTER_HOSTNAME:1}"
        SERVER_NAME_PREFIX="KTP ${DISPLAY_HOSTNAME}"
    else
        SERVER_NAME_PREFIX="KTP"
    fi
fi

# Temp directory for extraction
TEMP_DIR="/tmp/ktp-deploy-$$"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

cleanup() {
    rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

# ============================================
# Pre-flight Checks
# ============================================
if [ "$EUID" -eq 0 ]; then
    log_error "Do not run this script as root. Run as 'dodserver' user."
    exit 1
fi

# Check first instance exists
if [ ! -d "$HOME/dod-$BASE_PORT/serverfiles" ]; then
    log_error "LinuxGSM not installed. Run install-linuxgsm.sh first."
    exit 1
fi

echo "========================================"
echo "KTP Stack Deployment"
echo "========================================"
echo "Source: $ARTIFACTS_SOURCE"
echo "Instances: $NUM_INSTANCES"
echo "Base Port: $BASE_PORT"
if [ -n "$CLUSTER_HOSTNAME" ]; then
    echo "Hostname: $CLUSTER_HOSTNAME"
fi
if [ -n "$SERVER_IP" ]; then
    echo "Server IP: $SERVER_IP"
fi
echo "Server Name: $SERVER_NAME_PREFIX"
if [ -n "$LIBSTEAM_API_PATH" ]; then
    echo "libsteam_api.so: $LIBSTEAM_API_PATH"
fi
echo ""

# ============================================
# 1. Prepare Artifacts
# ============================================
mkdir -p "$TEMP_DIR"

if [[ "$ARTIFACTS_SOURCE" == http* ]]; then
    # Download from URL
    log_info "Downloading artifacts..."
    ARCHIVE_FILE="$TEMP_DIR/artifacts.tar.gz"
    wget -q -O "$ARCHIVE_FILE" "$ARTIFACTS_SOURCE"

    log_info "Extracting artifacts..."
    tar -xzf "$ARCHIVE_FILE" -C "$TEMP_DIR"

    # Find extracted directory
    ARTIFACTS_DIR=$(find "$TEMP_DIR" -maxdepth 1 -type d ! -name "$(basename "$TEMP_DIR")" | head -1)
    if [ -z "$ARTIFACTS_DIR" ]; then
        ARTIFACTS_DIR="$TEMP_DIR"
    fi
else
    # Local path
    if [ ! -d "$ARTIFACTS_SOURCE" ]; then
        log_error "Artifacts directory not found: $ARTIFACTS_SOURCE"
        exit 1
    fi
    ARTIFACTS_DIR="$ARTIFACTS_SOURCE"
fi

# Verify required files
log_info "Verifying artifacts..."

REQUIRED_FILES=(
    "engine/hlds_linux"
    "engine/engine_i486.so"
    "ktpamx/dlls/ktpamx_i386.so"
    "ktpamx/modules/dodx_ktp_i386.so"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$ARTIFACTS_DIR/$file" ]; then
        log_error "Missing required file: $file"
        exit 1
    fi
done

log_info "Artifacts verified"

# ============================================
# 2. Create Backups
# ============================================
BACKUP_DIR="$HOME/backups/$(date +%Y%m%d_%H%M%S)"
log_info "Creating backups in $BACKUP_DIR..."
mkdir -p "$BACKUP_DIR"

for i in $(seq 1 $NUM_INSTANCES); do
    PORT=$((BASE_PORT + i - 1))
    INSTANCE_DIR="$HOME/dod-$PORT"
    SERVERFILES="$INSTANCE_DIR/serverfiles"

    if [ -f "$SERVERFILES/engine_i486.so" ]; then
        cp "$SERVERFILES/engine_i486.so" "$BACKUP_DIR/engine_i486.so.$PORT" 2>/dev/null || true
    fi
    if [ -d "$SERVERFILES/dod/addons/ktpamx" ]; then
        tar -czf "$BACKUP_DIR/ktpamx.$PORT.tar.gz" -C "$SERVERFILES/dod/addons" ktpamx 2>/dev/null || true
    fi
done

log_info "Backups created"

# ============================================
# 3. Deploy Base DoD Files (Optional)
# ============================================
if [ -n "$DOD_BASE_SOURCE" ]; then
    log_info "Deploying base DoD files..."

    DOD_BASE_TAR=""
    if [[ "$DOD_BASE_SOURCE" == http* ]]; then
        # Download from URL
        log_info "Downloading base DoD files..."
        DOD_BASE_TAR="$TEMP_DIR/dod-base.tar.gz"
        wget -q -O "$DOD_BASE_TAR" "$DOD_BASE_SOURCE"
    elif [ -f "$DOD_BASE_SOURCE" ]; then
        DOD_BASE_TAR="$DOD_BASE_SOURCE"
    else
        log_error "DoD base files not found: $DOD_BASE_SOURCE"
        exit 1
    fi

    for i in $(seq 1 $NUM_INSTANCES); do
        PORT=$((BASE_PORT + i - 1))
        INSTANCE_DIR="$HOME/dod-$PORT"
        SERVERFILES="$INSTANCE_DIR/serverfiles"

        log_info "  Extracting to instance $i (port $PORT)..."
        # Extract base files - the tarball contains a 'dod' folder
        tar -xzf "$DOD_BASE_TAR" -C "$SERVERFILES/"
    done

    log_info "Base DoD files deployed"
else
    log_warn "WARNING: No --dod-base specified!"
    log_warn "  Missing: maps, WADs, configs (ktp_*.cfg), models, sprites, sounds"
    log_warn "  Create tarball with: scripts/package-dod-base.sh"
    log_warn "  Then re-run with: --dod-base /path/to/dod-base-files.tar.gz"
fi

# ============================================
# 4. Deploy KTP Artifacts to All Instances
# ============================================
for i in $(seq 1 $NUM_INSTANCES); do
    PORT=$((BASE_PORT + i - 1))
    INSTANCE_DIR="$HOME/dod-$PORT"
    SERVERFILES="$INSTANCE_DIR/serverfiles"

    log_info "Deploying to instance $i (port $PORT)..."

    # Create directory structure
    mkdir -p "$SERVERFILES/dod/addons/ktpamx/dlls"
    mkdir -p "$SERVERFILES/dod/addons/ktpamx/modules"
    mkdir -p "$SERVERFILES/dod/addons/ktpamx/plugins"
    mkdir -p "$SERVERFILES/dod/addons/ktpamx/configs"
    mkdir -p "$SERVERFILES/dod/addons/ktpamx/logs"
    mkdir -p "$SERVERFILES/dod/addons/ktpamx/data"

    # Deploy engine
    cp "$ARTIFACTS_DIR/engine/hlds_linux" "$SERVERFILES/"
    cp "$ARTIFACTS_DIR/engine/engine_i486.so" "$SERVERFILES/"
    chmod +x "$SERVERFILES/hlds_linux"
    chmod +x "$SERVERFILES/engine_i486.so"
    echo "  -> Engine deployed"

    # Deploy KTPAMXX main binary
    cp "$ARTIFACTS_DIR/ktpamx/dlls/ktpamx_i386.so" "$SERVERFILES/dod/addons/ktpamx/dlls/"
    chmod +x "$SERVERFILES/dod/addons/ktpamx/dlls/ktpamx_i386.so"
    echo "  -> KTPAMXX binary deployed"

    # Deploy modules
    for module in "$ARTIFACTS_DIR/ktpamx/modules"/*.so; do
        if [ -f "$module" ]; then
            cp "$module" "$SERVERFILES/dod/addons/ktpamx/modules/"
            chmod +x "$SERVERFILES/dod/addons/ktpamx/modules/$(basename "$module")"
        fi
    done
    echo "  -> Modules deployed"

    # Deploy plugins
    for plugin in "$ARTIFACTS_DIR/plugins"/*.amxx; do
        if [ -f "$plugin" ]; then
            cp "$plugin" "$SERVERFILES/dod/addons/ktpamx/plugins/"
        fi
    done
    echo "  -> Plugins deployed"

    # Deploy data directory (gamedata, lang, GeoIP)
    if [ -d "$ARTIFACTS_DIR/ktpamx/data" ]; then
        cp -r "$ARTIFACTS_DIR/ktpamx/data/"* "$SERVERFILES/dod/addons/ktpamx/data/" 2>/dev/null || true
        echo "  -> Data files deployed"
    else
        log_warn "  -> No data directory in artifacts (gamedata/lang may be missing)"
    fi

    # Deploy configs from artifacts (if present)
    if [ -d "$ARTIFACTS_DIR/ktpamx/configs" ]; then
        cp -r "$ARTIFACTS_DIR/ktpamx/configs/"* "$SERVERFILES/dod/addons/ktpamx/configs/" 2>/dev/null || true
        echo "  -> Config files deployed"
    fi

    # Create extensions.ini for KTP-ReHLDS
    # Location: dod/addons/extensions.ini (not rehlds/)
    cat > "$SERVERFILES/dod/addons/extensions.ini" << 'EOF'
addons/ktpamx/dlls/ktpamx_i386.so
EOF
    echo "  -> extensions.ini created"

    # Deploy libsteam_api.so if provided
    if [ -n "$LIBSTEAM_API_PATH" ]; then
        if [ -f "$LIBSTEAM_API_PATH" ]; then
            cp "$LIBSTEAM_API_PATH" "$SERVERFILES/libsteam_api.so"
            chmod +x "$SERVERFILES/libsteam_api.so"
            echo "  -> libsteam_api.so deployed"
        else
            log_warn "  -> libsteam_api.so not found at: $LIBSTEAM_API_PATH"
        fi
    elif [ ! -f "$SERVERFILES/libsteam_api.so" ]; then
        log_warn "  -> libsteam_api.so needs manual deployment (use --libsteam-api)"
    fi
done

# ============================================
# 5. Create Default Configs (if not present from base)
# ============================================
log_info "Creating default configuration files..."

# Create modules.ini template
MODULES_INI=$(cat << 'EOF'
; KTPAMXX Module Configuration
; Loaded in order listed

; Core modules
fun_ktp_i386.so
engine_ktp_i386.so
fakemeta_ktp_i386.so

; KTP modules
reapi_ktp_i386.so
dodx_ktp_i386.so
amxxcurl_ktp_i386.so
EOF
)

# Create plugins.ini template
PLUGINS_INI=$(cat << 'EOF'
; KTPAMXX Plugin Configuration
; Loaded in order listed

; Core KTP plugins
KTPMatchHandler.amxx
ktp_cvar.amxx
ktp_file.amxx
KTPAdminAudit.amxx
KTPHLTVRecorder.amxx

; Optional plugins
KTPGrenadeLoadout.amxx
KTPGrenadeDamage.amxx
; KTPPracticeMode.amxx  ; Enable manually when needed
EOF
)

for i in $(seq 1 $NUM_INSTANCES); do
    PORT=$((BASE_PORT + i - 1))
    CONFIGS_DIR="$HOME/dod-$PORT/serverfiles/dod/addons/ktpamx/configs"

    # Only create if doesn't exist
    if [ ! -f "$CONFIGS_DIR/modules.ini" ]; then
        echo "$MODULES_INI" > "$CONFIGS_DIR/modules.ini"
    fi
    if [ ! -f "$CONFIGS_DIR/plugins.ini" ]; then
        echo "$PLUGINS_INI" > "$CONFIGS_DIR/plugins.ini"
    fi
done

log_info "Default configs created"

# ============================================
# 6. Configure Game Server Hostname (In-Game Name)
# ============================================
log_info "Configuring game server hostnames..."

for i in $(seq 1 $NUM_INSTANCES); do
    PORT=$((BASE_PORT + i - 1))
    SERVERFILES="$HOME/dod-$PORT/serverfiles"
    DOD_DIR="$SERVERFILES/dod"

    # Build display name: "KTP - Location N" (e.g., "KTP - Denver 1")
    if [ -n "$CLUSTER_HOSTNAME" ]; then
        DISPLAY_HOSTNAME="$(echo "${CLUSTER_HOSTNAME:0:1}" | tr '[:lower:]' '[:upper:]')${CLUSTER_HOSTNAME:1}"
        GAME_HOSTNAME="KTP - $DISPLAY_HOSTNAME $i"
    else
        GAME_HOSTNAME="KTP DoD Server $i"
    fi

    # Create configs directory if needed
    mkdir -p "$DOD_DIR/configs"

    # Create servernamedefault.cfg
    echo "hostname \"$GAME_HOSTNAME\"" > "$DOD_DIR/configs/servernamedefault.cfg"

    # Ensure dodserver.cfg has the exec line
    DODSERVER_CFG="$DOD_DIR/dodserver.cfg"
    if [ -f "$DODSERVER_CFG" ]; then
        if ! grep -q "servernamedefault" "$DODSERVER_CFG"; then
            # Add exec line after hostname line, or at the beginning if no hostname line
            if grep -q "^hostname" "$DODSERVER_CFG"; then
                sed -i '/^hostname/a exec configs/servernamedefault.cfg' "$DODSERVER_CFG"
            else
                # Prepend to file
                sed -i '1i hostname ""\nexec configs/servernamedefault.cfg' "$DODSERVER_CFG"
            fi
        fi
    else
        # Create minimal dodserver.cfg
        cat > "$DODSERVER_CFG" << 'DODCFG'
hostname ""
exec configs/servernamedefault.cfg
sv_region 0
DODCFG
    fi

    echo "  -> Instance $i: $GAME_HOSTNAME"
done

log_info "Game server hostnames configured"

# ============================================
# 7. Configure LinuxGSM Instance Settings
# ============================================
log_info "Configuring LinuxGSM instance settings..."

for i in $(seq 1 $NUM_INSTANCES); do
    PORT=$((BASE_PORT + i - 1))
    INSTANCE_DIR="$HOME/dod-$PORT"
    LGSM_CONFIG_DIR="$INSTANCE_DIR/lgsm/config-lgsm/dodserver"

    # Determine executable name
    if [ $i -eq 1 ]; then
        EXEC_NAME="dodserver"
    else
        EXEC_NAME="dodserver$i"
    fi

    # Create instance-specific config
    INSTANCE_CFG="$LGSM_CONFIG_DIR/$EXEC_NAME.cfg"

    # Build server name: "KTP - Branch #" (e.g., "KTP - Denver 1")
    # Must match the format in servernamedefault.cfg (section 6)
    if [ -n "$CLUSTER_HOSTNAME" ]; then
        DISPLAY_HOSTNAME="$(echo "${CLUSTER_HOSTNAME:0:1}" | tr '[:lower:]' '[:upper:]')${CLUSTER_HOSTNAME:1}"
        LGSM_SERVER_NAME="KTP - $DISPLAY_HOSTNAME $i"
    else
        LGSM_SERVER_NAME="KTP DoD Server $i"
    fi

    # Create/update LinuxGSM instance config
    mkdir -p "$LGSM_CONFIG_DIR"

    # Check if config exists
    if [ -f "$INSTANCE_CFG" ]; then
        # Update existing config - preserve port settings, update server name
        if grep -q "^servername=" "$INSTANCE_CFG"; then
            sed -i "s/^servername=.*/servername=\"$LGSM_SERVER_NAME\"/" "$INSTANCE_CFG"
        else
            echo "servername=\"$LGSM_SERVER_NAME\"" >> "$INSTANCE_CFG"
        fi
        # Update IP if provided
        if [ -n "$SERVER_IP" ]; then
            if grep -q "^ip=" "$INSTANCE_CFG"; then
                sed -i "s/^ip=.*/ip=\"$SERVER_IP\"/" "$INSTANCE_CFG"
            else
                echo "ip=\"$SERVER_IP\"" >> "$INSTANCE_CFG"
            fi
        fi
    else
        # Create new instance config
        cat > "$INSTANCE_CFG" << EOF
# LinuxGSM Instance Configuration
# Instance $i - Port $PORT

port="$PORT"
clientport="$((PORT - 10))"
servername="$LGSM_SERVER_NAME"
EOF
        # Add IP if provided (critical for proper LinuxGSM monitoring)
        if [ -n "$SERVER_IP" ]; then
            cat >> "$INSTANCE_CFG" << EOF
ip="$SERVER_IP"
EOF
        fi
        # Add cluster comment if provided
        if [ -n "$CLUSTER_HOSTNAME" ]; then
            cat >> "$INSTANCE_CFG" << EOF

# Cluster: $CLUSTER_HOSTNAME
EOF
        fi
    fi

    if [ -n "$SERVER_IP" ]; then
        echo "  -> Instance $i: $LGSM_SERVER_NAME (port $PORT, IP $SERVER_IP)"
    else
        echo "  -> Instance $i: $LGSM_SERVER_NAME (port $PORT)"
    fi
done

log_info "LinuxGSM instance settings configured"

# Create common.cfg with shared settings
COMMON_CFG="$HOME/dod-$BASE_PORT/lgsm/config-lgsm/dodserver/common.cfg"
if [ ! -f "$COMMON_CFG" ]; then
    log_info "Creating common.cfg..."
    cat > "$COMMON_CFG" << EOF
# LinuxGSM Common Configuration
# Shared settings for all DoD server instances

# Game settings
defaultmap="dod_caen"
maxplayers="13"

# Update settings
updateonstart="off"

# Backup settings
maxbackups="4"
maxbackupdays="30"
EOF
    if [ -n "$CLUSTER_HOSTNAME" ]; then
        cat >> "$COMMON_CFG" << EOF

# Cluster identification
# Hostname: $CLUSTER_HOSTNAME
EOF
    fi
fi

# ============================================
# 9. Apply LinuxGSM Tmux Session Fix
# ============================================
# LinuxGSM has a bug where "old type tmux session" detection uses substring
# matching that incorrectly matches NEW-style sessions, causing random restarts.
# This comments out lines 203-212 in command_monitor.sh for all instances.
# Note: This patch must be reapplied after any ./dodserver update-lgsm command.

log_info "Applying LinuxGSM tmux session fix..."

TMUX_FIX_APPLIED=0
for i in $(seq 1 $NUM_INSTANCES); do
    PORT=$((BASE_PORT + i - 1))

    if [ $i -eq 1 ]; then
        EXEC_NAME="dodserver"
    else
        EXEC_NAME="dodserver$i"
    fi

    MONITOR_SCRIPT="$HOME/dod-$PORT/lgsm/modules/command_monitor.sh"

    if [ -f "$MONITOR_SCRIPT" ]; then
        # Check if fix already applied
        if grep -q "KTP-DISABLED" "$MONITOR_SCRIPT" 2>/dev/null; then
            log_info "  Port $PORT: Fix already applied"
        else
            # Apply the fix - comment out lines 203-212
            sed -i '203,212s/^/# KTP-DISABLED: /' "$MONITOR_SCRIPT"
            if grep -q "KTP-DISABLED" "$MONITOR_SCRIPT" 2>/dev/null; then
                log_info "  Port $PORT: Fix applied successfully"
                TMUX_FIX_APPLIED=$((TMUX_FIX_APPLIED + 1))
            else
                log_warn "  Port $PORT: Fix may not have applied correctly"
            fi
        fi
    else
        log_warn "  Port $PORT: command_monitor.sh not found (LinuxGSM not installed?)"
    fi
done

if [ $TMUX_FIX_APPLIED -gt 0 ]; then
    log_info "Applied tmux fix to $TMUX_FIX_APPLIED instance(s)"
fi

# ============================================
# 10. Clean Up modules.ini (Remove GLIBC 2.38 Modules)
# ============================================
# Some modules require GLIBC 2.38+ but Ubuntu 22.04 has 2.35.
# These modules aren't used by KTP anyway, so we comment them out.
log_info "Cleaning up modules.ini (removing GLIBC 2.38 dependent modules)..."

GLIBC_MODULES="fun_ktp_i386.so engine_ktp_i386.so fakemeta_ktp_i386.so"

for i in $(seq 1 $NUM_INSTANCES); do
    PORT=$((BASE_PORT + i - 1))
    MODULES_INI="$HOME/dod-$PORT/serverfiles/dod/addons/ktpamx/configs/modules.ini"

    if [ -f "$MODULES_INI" ]; then
        for module in $GLIBC_MODULES; do
            # Comment out the module if it exists and isn't already commented
            if grep -q "^$module" "$MODULES_INI" 2>/dev/null; then
                sed -i "s|^$module|; $module ; DISABLED - requires GLIBC 2.38|" "$MODULES_INI"
            fi
        done
    fi
done
log_info "modules.ini cleaned up"

# ============================================
# 11. Configure hltv_recorder.ini with Correct HLTV Ports
# ============================================
# Each instance needs the correct HLTV port for its paired HLTV server.
# Atlanta: 27020-27024, Dallas: 27025-27029, Denver: 27030-27034

if [ -n "$HLTV_BASE_PORT" ]; then
    log_info "Configuring hltv_recorder.ini with HLTV ports starting at $HLTV_BASE_PORT..."

    for i in $(seq 1 $NUM_INSTANCES); do
        PORT=$((BASE_PORT + i - 1))
        HLTV_PORT=$((HLTV_BASE_PORT + i - 1))
        HLTV_INI="$HOME/dod-$PORT/serverfiles/dod/addons/ktpamx/configs/hltv_recorder.ini"

        if [ -f "$HLTV_INI" ]; then
            # Update hltv_port setting
            if grep -q "^hltv_port" "$HLTV_INI" 2>/dev/null; then
                sed -i "s|^hltv_port.*|hltv_port = $HLTV_PORT|" "$HLTV_INI"
            else
                echo "hltv_port = $HLTV_PORT" >> "$HLTV_INI"
            fi
            echo "  -> Instance $i (port $PORT): HLTV port $HLTV_PORT"
        else
            log_warn "  Port $PORT: hltv_recorder.ini not found"
        fi
    done
    log_info "hltv_recorder.ini configured"
else
    log_warn "HLTV base port not set - skipping hltv_recorder.ini configuration"
    log_warn "Use --hltv-base-port or --hostname to configure HLTV ports"
fi

# ============================================
# 12. Clean Up server.cfg Hostname Conflicts
# ============================================
# Base DoD files may have a hardcoded hostname that conflicts with servernamedefault.cfg.
# Comment out any hostname lines in server.cfg to let servernamedefault.cfg take precedence.

log_info "Cleaning up server.cfg hostname conflicts..."

for i in $(seq 1 $NUM_INSTANCES); do
    PORT=$((BASE_PORT + i - 1))
    SERVER_CFG="$HOME/dod-$PORT/serverfiles/dod/server.cfg"

    if [ -f "$SERVER_CFG" ]; then
        # Comment out any hostname lines (but not "exec...hostname" lines)
        if grep -q "^hostname " "$SERVER_CFG" 2>/dev/null; then
            sed -i 's|^hostname |// hostname |' "$SERVER_CFG"
            log_info "  Port $PORT: Commented out hostname in server.cfg"
        fi
    fi
done
log_info "server.cfg cleanup complete"

# ============================================
# 13. Deploy Scheduled Restart Script and Cron
# ============================================
log_info "Deploying scheduled restart script..."

RESTART_SCRIPT="$HOME/ktp-scheduled-restart.sh"
SCRIPT_DIR="$(dirname "$0")"
SCRIPT_SOURCE=""

# Look for ktp-scheduled-restart.sh in multiple locations
for check_path in \
    "$SCRIPT_DIR/ktp-scheduled-restart.sh" \
    "$SCRIPT_DIR/../scripts/ktp-scheduled-restart.sh" \
    "/tmp/ktp-scheduled-restart.sh"; do
    if [ -f "$check_path" ]; then
        SCRIPT_SOURCE="$check_path"
        break
    fi
done

# Check if script source exists
if [ -f "$SCRIPT_SOURCE" ]; then
    cp "$SCRIPT_SOURCE" "$RESTART_SCRIPT"
    chmod +x "$RESTART_SCRIPT"
    log_info "Deployed ktp-scheduled-restart.sh"
elif [ -f "$HOME/ktp-scheduled-restart.sh" ]; then
    log_info "ktp-scheduled-restart.sh already exists"
else
    # Create the script inline if source not found (full version with Discord)
    log_warn "ktp-scheduled-restart.sh source not found - creating from embedded template"
    cat > "$RESTART_SCRIPT" << 'RESTART_SCRIPT_CONTENT'
#!/bin/bash
# KTP Game Server Scheduled Restart Script
# Restarts all 5 DoD game servers and sends Discord notification
#
# Usage: ktp-scheduled-restart.sh
# Cron:  0 3 * * * /home/dodserver/ktp-scheduled-restart.sh >> /home/dodserver/log/scheduled-restart.log 2>&1

# ============================================================================
# Configuration
# ============================================================================
RELAY_URL="${DISCORD_RELAY_URL:-YOUR_RELAY_URL_HERE}/reply"
EDIT_URL="${DISCORD_RELAY_URL:-YOUR_RELAY_URL_HERE}/edit"
AUTH_SECRET="${DISCORD_RELAY_AUTH_SECRET:-YOUR_AUTH_SECRET_HERE}"

# Discord channels (same as HLTV status)
CHANNEL_KTP="1458222926586446059"          # KTP Discord
CHANNEL_EXTERNAL="1457951326666489996"     # 1.3 Discord

# Detect server location from IP
SERVER_IP=$(hostname -I | awk '{print $1}')
case "$SERVER_IP" in
    74.91.112.182|74.91.121.9) SERVER_NAME="KTP - Atlanta" ;;
    74.91.114.195) SERVER_NAME="KTP - Dallas" ;;
    66.163.114.109) SERVER_NAME="KTP - Denver" ;;
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

    local payload=$(cat <<EOFPAYLOAD
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
EOFPAYLOAD
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

    local payload=$(cat <<EOFPAYLOAD
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
EOFPAYLOAD
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

# ============================================================================
# Apply Real-Time Scheduling (reduces CPU steal impact)
# ============================================================================
log "Applying chrt -r 20 to all game servers..."
for pid in $(pgrep -f hlds_linux); do
    if sudo chrt -r -p 20 "$pid" 2>/dev/null; then
        log "Applied chrt -r 20 to PID $pid"
    fi
done

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
RESTART_SCRIPT_CONTENT
    chmod +x "$RESTART_SCRIPT"
    log_info "Created ktp-scheduled-restart.sh with Discord notifications"
fi

# Set up cron job for 3 AM ET daily
CRON_ENTRY="0 3 * * * $RESTART_SCRIPT >> $HOME/log/scheduled-restart.log 2>&1"

# Check if cron entry already exists
if crontab -l 2>/dev/null | grep -q "ktp-scheduled-restart"; then
    log_info "Cron job for scheduled restart already exists"
else
    # Add cron entry
    (crontab -l 2>/dev/null; echo "$CRON_ENTRY") | crontab -
    log_info "Added cron job: 3:00 AM daily restart"
fi

# Ensure log directory exists
mkdir -p "$HOME/log"

# ============================================
# Summary
# ============================================
echo ""
echo "========================================"
echo "KTP Stack Deployment Complete!"
echo "========================================"
echo ""
echo "Deployed to $NUM_INSTANCES instances (ports $BASE_PORT-$((BASE_PORT + NUM_INSTANCES - 1)))"
if [ -n "$CLUSTER_HOSTNAME" ]; then
    echo "Cluster: $CLUSTER_HOSTNAME"
fi
if [ -n "$HLTV_BASE_PORT" ]; then
    echo "HLTV ports: $HLTV_BASE_PORT-$((HLTV_BASE_PORT + NUM_INSTANCES - 1))"
fi
echo "Server names: KTP - ${CLUSTER_HOSTNAME:-DoD} 1-$NUM_INSTANCES"
if [ -n "$DOD_BASE_SOURCE" ]; then
    echo "Base DoD files: Included (maps, WADs, configs, models, sounds)"
else
    echo ""
    echo "*** WARNING: Base DoD files NOT deployed! ***"
    echo "    Missing: maps, WADs, dod/configs/*.cfg, models, sprites, sounds, mapcycle.txt, motd.txt"
    echo "    Create tarball: scripts/package-dod-base.sh"
    echo "    Re-run with: --dod-base /path/to/dod-base-files.tar.gz"
    echo ""
fi
echo "Scheduled restart: 3:00 AM daily (cron configured)"
echo "Backups in: $BACKUP_DIR"
echo ""
echo "Automated configurations applied:"
echo "  - Game hostnames (servernamedefault.cfg)"
echo "  - LinuxGSM instance configs (servername)"
echo "  - HLTV ports (hltv_recorder.ini)"
echo "  - modules.ini cleanup (GLIBC 2.38 modules disabled)"
echo "  - server.cfg hostname conflicts resolved"
echo "  - LinuxGSM tmux session fix applied"
echo "  - Scheduled restart cron job"
echo ""
echo "Manual steps required:"
STEP=1
if [ -z "$LIBSTEAM_API_PATH" ]; then
    echo "  $STEP. Deploy libsteam_api.so (KTP 76KB version) to each serverfiles/"
    echo "     Or re-run with: --libsteam-api /path/to/libsteam_api.so"
    STEP=$((STEP + 1))
fi
if [ -z "$SERVER_IP" ]; then
    echo "  $STEP. Set IP address in each instance config (ip=\"<SERVER_IP>\")"
    echo "     Or re-run with: --ip <SERVER_IP>"
    STEP=$((STEP + 1))
fi
echo "  $STEP. Review/update discord.ini (relay URL, auth secret, channel IDs)"
STEP=$((STEP + 1))
echo "  $STEP. On data server: Run setup-<cluster>-dataserver.sh or manually:"
echo "     - Add SSH key: ssh-copy-id -i /var/www/fastdl/.ssh/id_rsa.pub dodserver@<IP>"
echo "     - Update FileDistributor: /opt/ktp-file-distributor/servers.json"
echo "     - Configure HLTV instances for this cluster"
echo "     - Add to HLStatsX database"
STEP=$((STEP + 1))
echo "  $STEP. Test with: ~/ktp-scheduled-restart.sh"
echo ""
echo "LinuxGSM configs:"
echo "  Common: ~/dod-$BASE_PORT/lgsm/config-lgsm/dodserver/common.cfg"
echo "  Instance 1: ~/dod-$BASE_PORT/lgsm/config-lgsm/dodserver/dodserver.cfg"
echo ""
echo "Verify plugins load:"
echo "  tail -f ~/dod-$BASE_PORT/log/console/*.log | grep -i ktpamx"
echo ""
echo "========================================"
