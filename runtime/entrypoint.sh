#!/bin/bash
# KTP Game Server Entrypoint
#
# 1. Copies config files from /config/ mount into KTPAMXX config paths
# 2. Copies additional plugins from /plugins/ mount
# 3. Launches hlds_linux with KTP-ReHLDS
#
# Environment variables:
#   MAP           - Starting map (default: dod_anzio)
#   MAXPLAYERS    - Max player slots (default: 13, matches production)
#   RCON_PASSWORD - RCON password (default: changeme)

set -e
set -o pipefail

HLDS_DIR=/opt/hlds
DOD_DIR=$HLDS_DIR/dod
KTPAMX_DIR=$DOD_DIR/addons/ktpamx

# --- Config files ---
# If /config/ is mounted, copy config files into place.
# This lets docker-compose mount a config profile (lan/, local/, online/)
# and have it applied at startup without baking configs into the image.
if [ -d /config ]; then
    # Install all .ini config files from /config into the KTPAMXX configs
    # directory. Includes the standard ones (modules.ini, plugins.ini,
    # discord.ini, hltv_recorder.ini) plus any plugin-specific configs
    # (ktp.ini, ktp_maps.ini, ktp_file.ini, grenade_loadout.ini, ac.ini)
    # that exist alongside. The glob is intentional — individual plugins
    # ship their own configs and we don't want to enumerate them here.
    for f in /config/*.ini; do
        [ -f "$f" ] || continue
        bn="$(basename "$f")"
        cp "$f" "$KTPAMX_DIR/configs/$bn"
        echo "[entrypoint] Installed config: $bn"
    done

    if [ -f /config/dodserver.cfg ]; then
        cp /config/dodserver.cfg "$DOD_DIR/dodserver.cfg"
        echo "[entrypoint] Installed dodserver.cfg"

        # Override hostname per-instance if SERVER_HOSTNAME env var set.
        # This lets multiple compose services share one cfg but identify distinctly
        # (HUD backend uses X-Server-Hostname to separate sources). Done via cfg
        # substitution rather than +hostname command-line because the cfg's
        # `hostname "..."` line is exec'd after +cmd args and would otherwise win.
        if [ -n "$SERVER_HOSTNAME" ]; then
            sed -i 's|^hostname .*$|hostname "'"$SERVER_HOSTNAME"'"|' "$DOD_DIR/dodserver.cfg"
            echo "[entrypoint] Overrode dodserver.cfg hostname: $SERVER_HOSTNAME"
        fi
    fi
fi

# --- Additional plugins ---
# Mount a directory of .amxx files at /plugins/ to add plugins
# beyond the standard KTP set (e.g., HUD Observer plugin during dev).
if [ -d /plugins ] && ls /plugins/*.amxx >/dev/null 2>&1; then
    cp /plugins/*.amxx "$KTPAMX_DIR/plugins/"
    echo "[entrypoint] Installed additional plugins:"
    ls /plugins/*.amxx | xargs -n1 basename | sed 's/^/  /'
fi

# --- Launch ---
# Ensure binaries are executable (Required for some Linux filesystems and Docker volume mounts)
chmod +x "$HLDS_DIR/hlds_linux" "$HLDS_DIR/engine_i486.so" 2>/dev/null || true
chmod +x "$KTPAMX_DIR/dlls/"*.so "$KTPAMX_DIR/modules/"*.so 2>/dev/null || true

export LD_LIBRARY_PATH="$HLDS_DIR:${LD_LIBRARY_PATH:-}"
cd "$HLDS_DIR"

# HLDS requires steam_appid.txt to initialize correctly in many environments
echo "90" > steam_appid.txt

MAP="${MAP:-dod_anzio}"
MAXPLAYERS="${MAXPLAYERS:-13}"
PORT="${PORT:-27015}"
CLIENTPORT="${CLIENTPORT:-27005}"
RCON_PASSWORD="${RCON_PASSWORD:-changeme}"
HLTV_PASSWORD="${HLTV_PASSWORD:-changeme}"

if [ ! -f "./hlds_linux" ]; then
    echo "[entrypoint] ERROR: hlds_linux not found in $(pwd)"
    ls -la
    exit 1
fi

if [ ! -f "./libsteam_api.so" ]; then
    echo "[entrypoint] WARNING: libsteam_api.so not found in $(pwd). ReHLDS may fail to load."
fi

if [ ! -d "$DOD_DIR" ]; then
    echo "[entrypoint] ERROR: Game directory $DOD_DIR not found. SteamCMD likely failed to download game data."
    exit 1
fi

if [ ! -d "$HLDS_DIR/valve" ]; then
    echo "[entrypoint] ERROR: Base game directory $HLDS_DIR/valve not found. HLDS requires Half-Life base files to boot."
    exit 1
fi

if [ ! -f "$DOD_DIR/maps/$MAP.bsp" ]; then
    echo "[entrypoint] ERROR: Map $MAP.bsp not found in $DOD_DIR/maps/"
    echo "[entrypoint] SteamCMD likely failed to download maps. Rebuild the image."
    exit 1
fi

echo "[entrypoint] Working directory: $(pwd)"
echo "[entrypoint] Binary dependencies:"
ldd ./hlds_linux | grep "not found" || true

echo "[entrypoint] Engine library resolution:"
# Show exactly which libsteam_api.so the engine is linking to
ldd ./engine_i486.so | grep -E "libsteam_api|not found" || true

# Debug Steam API symbols if 'nm' is available
if command -v nm >/dev/null 2>&1; then
    echo "[entrypoint] Checking libsteam_api.so for SteamGameServer_Init..."
    if ! nm -D ./libsteam_api.so | grep -q "SteamGameServer_Init"; then
        echo "[entrypoint] WARNING: Symbol SteamGameServer_Init NOT FOUND in ./libsteam_api.so!"
    fi
fi

echo "[entrypoint] KTP-ReHLDS starting: map=$MAP maxplayers=$MAXPLAYERS"
echo "[entrypoint] Extensions:"
if [ -f "$DOD_DIR/addons/extensions.ini" ]; then
    cat "$DOD_DIR/addons/extensions.ini" | sed 's/^/  /'
else
    echo "  (no extensions.ini)"
fi
echo "[entrypoint] Plugins:"
grep -vE '^($|;)' "$KTPAMX_DIR/configs/plugins.ini" 2>/dev/null | sed 's/^/  /' || echo "  (no active plugins)"

# Mirrors production LinuxGSM startparameters (install-linuxgsm.sh:136).
# +servercfgfile is required — dodserver.cfg is not the HLDS default (server.cfg).
exec "$HLDS_DIR/hlds_linux" -game dod \
    -strictportbind \
    -port "$PORT" \
    +clientport "$CLIENTPORT" \
    +map "$MAP" \
    +servercfgfile dodserver.cfg \
    -maxplayers "$MAXPLAYERS" \
    -pingboost 2 \
    "$@"
