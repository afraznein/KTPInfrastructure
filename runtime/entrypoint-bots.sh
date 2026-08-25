#!/bin/bash
# KTP local BOT server entrypoint — wraps runtime/entrypoint.sh.
#
# Does three things the ordinary entrypoint must not do, then hands over:
#
#   1. Shouts that this is NOT a production topology.
#   2. Installs the KTP_LANE_B_FAKECLIENTS ktpamx build, or REFUSES TO BOOT.
#   3. Asserts the split-layer topology actually survived the image build.
#
# ## Why (2) is fail-closed and not a warning
#
# In ReHLDS extension mode KTPAMXX has no code path that registers a fake
# client as a player: Connect() / PutInServer() / ++g_players_num never run for
# a bot. is_user_connected() is therefore false for every bot and every
# AMXX-level plugin is completely blind to them.
#
# The failure is SILENT and indistinguishable from a healthy server. `status`
# shows the bots (the engine sees them fine), the map plays, nothing errors —
# and no plugin emits anything. Upstream shipped an A/B differential that
# reported "no interference, 8/8" while AMXX was blind, because it compared
# module and plugin *loading* and never measured player visibility.
#
# A warning would be read past. This exits.
#
# See tests/e2e_stats/PHASE0_FINDINGS.md and KTPAMXX/AMBuildScript.

set -euo pipefail

LANEB_DIR=/opt/ktp-laneb
KTPAMX_DLL=/opt/hlds/dod/addons/ktpamx/dlls/ktpamx_i386.so
DODX_MOD=/opt/hlds/dod/addons/ktpamx/modules/dodx_ktp_i386.so

cat <<'BANNER'
================================================================================
  ██  KTP LOCAL BOT SERVER — NOT PRODUCTION TOPOLOGY  ██

  This server is deliberately DIFFERENT from the fleet:

    * Metamod-R is inserted as the game DLL, hosting new_bot
    * ktpamx is a KTP_LANE_B_FAKECLIENTS build, stamped NOT FOR PRODUCTION
      (it registers fake clients as players; no fleet binary does this)

  ktpamx still loads via addons/extensions.ini, as production does, so
  plugins run in extension mode — but `fakemeta` is reachable here and is
  NOT reachable on the fleet.

  => A fix verified ONLY here is not verified. Reproduce on a non-bot
     server before promoting anything.
================================================================================
BANNER

# --- (2) the patched core, or nothing ------------------------------------
if [ ! -f "$LANEB_DIR/ktpamx_i386.so" ]; then
    cat >&2 <<EOF

[entrypoint-bots] FATAL: no patched ktpamx at $LANEB_DIR/ktpamx_i386.so

Without a KTP_LANE_B_FAKECLIENTS build, AMXX cannot see bots at all. The
server would boot, accept bots, play a map, and emit NOTHING — a failure that
looks exactly like a working server. Refusing to boot instead.

Build it with:
    make local-bots-amxx

EOF
    exit 1
fi

install_laneb() {
    local src="$1" dest="$2" what="$3"
    if [ ! -f "$src" ]; then
        echo "[entrypoint-bots] FATAL: $what missing at $src" >&2
        echo "[entrypoint-bots] Take BOTH binaries from one build: a Lane B core" >&2
        echo "[entrypoint-bots] with a production DODX module sees bots but records" >&2
        echo "[entrypoint-bots] no bot weapon counters." >&2
        exit 1
    fi
    # Copy rather than bind-mount over the target: a read-only overmount makes
    # the base entrypoint's chmod fail, and copying keeps the image's own file
    # ownership.
    cp "$src" "$dest"
    chmod 0755 "$dest"
    echo "[entrypoint-bots] installed $what ($(stat -c%s "$dest") bytes)"
}

install_laneb "$LANEB_DIR/ktpamx_i386.so"   "$KTPAMX_DLL" "Lane B ktpamx core"
install_laneb "$LANEB_DIR/dodx_ktp_i386.so" "$DODX_MOD"   "Lane B dodx module"

if [ -f "$LANEB_DIR/ktpamx_i386.so.sha" ]; then
    echo "[entrypoint-bots] built from KTPAMXX $(cat "$LANEB_DIR/ktpamx_i386.so.sha")"
fi

# --- (3) topology assertions ---------------------------------------------
# Cheap, and they catch a botched image at boot instead of three hours into
# wondering why no bot ever spawns.
if ! grep -q 'metamod_i386.so' /opt/hlds/dod/liblist.gam; then
    echo "[entrypoint-bots] FATAL: liblist.gam does not point at Metamod." >&2
    echo "[entrypoint-bots] new_bot has nothing to load it; there will be no bots." >&2
    exit 1
fi

if ! grep -q 'ktpamx' /opt/hlds/dod/addons/extensions.ini; then
    echo "[entrypoint-bots] FATAL: extensions.ini no longer loads ktpamx." >&2
    echo "[entrypoint-bots] Extension mode is the one production property this" >&2
    echo "[entrypoint-bots] server keeps. Without it the run proves nothing." >&2
    exit 1
fi

# Strip comments before matching: plugins.ini's own header explains that ktpamx
# is deliberately absent, so a naive grep matches the explanation and fails a
# correct topology.
if grep -v '^[[:space:]]*;' /opt/hlds/dod/addons/metamod/plugins.ini | grep -q 'ktpamx'; then
    echo "[entrypoint-bots] FATAL: metamod plugins.ini lists ktpamx." >&2
    echo "[entrypoint-bots] ktpamx installs ReHLDS hookchains even when Metamod" >&2
    echo "[entrypoint-bots] loads it, so this topology segfaults during plugin" >&2
    echo "[entrypoint-bots] init. Metamod must host the BOT ONLY." >&2
    exit 1
fi

echo "[entrypoint-bots] topology OK: engine->extensions.ini->ktpamx, engine->metamod->new_bot"
echo "[entrypoint-bots] handing over to /entrypoint.sh"

exec bash /entrypoint.sh "$@"
