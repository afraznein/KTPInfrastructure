#!/usr/bin/env bash
# Helpers for the local BOT game server (ktp-game-2).
#
# Lives here rather than inline in the Makefile because every one of these is a
# multi-line shell conditional, and Makefile recipes turn those into
# backslash-continuation soup that nobody can read or edit safely.
#
# Subcommands:
#   build-core       compile the KTP_LANE_B_FAKECLIENTS ktpamx + dodx
#   stage-plugins    KTP_TEST_MODE KTPMatchHandler + HUD plugin -> local/plugins-bots/
#   preflight        assert the core exists and warn on KTPAMXX drift
#   has-core         exit 0 if a patched core is present (quiet; for `if` tests)
#
# See build/bots/README.md for why any of this is necessary.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LANEB_DIR="${LANEB_DIR:-$REPO_ROOT/local/lane-b}"
BOT_PLUGIN_DIR="${BOT_PLUGIN_DIR:-$REPO_ROOT/local/plugins-bots}"
PROJECT_ROOT="${KTP_PROJECT_ROOT:-$(cd "$REPO_ROOT/.." && pwd)}"

KTPAMXX_DIR="$PROJECT_ROOT/KTPAMXX"
MATCHHANDLER_DIR="$PROJECT_ROOT/KTPMatchHandler"
CORE_SO="$LANEB_DIR/ktpamx_i386.so"
CORE_SHA_FILE="$LANEB_DIR/KTPAMXX_SOURCE_SHA"

die() { echo "ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------

cmd_has_core() {
    [ -f "$CORE_SO" ]
}

cmd_build_core() {
    [ -d "$KTPAMXX_DIR/.git" ] || die "KTPAMXX not found at $KTPAMXX_DIR"

    # `make build-amxx` bakes the WORKING TREE into ktp-game-1's image, while
    # build_ktpamx_laneb.sh clones and checks out a COMMITTED SHA for
    # ktp-game-2. A dirty tree therefore means the two servers silently run
    # different source -- which destroys the only thing game-1 is for.
    if [ -n "$(git -C "$KTPAMXX_DIR" status --porcelain)" ]; then
        cat >&2 <<'EOF'

ERROR: KTPAMXX working tree is dirty.

  'make build-amxx' bakes the WORKING TREE into ktp-game-1, but the bot core
  is built from a COMMITTED SHA. Building now would leave the two servers
  running different source, which defeats the point of keeping game-1 as a
  control.

  Commit or stash KTPAMXX first.

EOF
        exit 1
    fi

    local sha
    sha="$(git -C "$KTPAMXX_DIR" rev-parse HEAD)"
    mkdir -p "$LANEB_DIR"

    # Point the upstream builder at the LOCAL checkout at its current commit.
    # Its own defaults clone `preprod` from GitHub, which is exactly what would
    # inject version skew between game-1 and game-2.
    echo "[bots] building Lane B core from KTPAMXX ${sha:0:12} (local checkout)"
    LANEB_SRC="$KTPAMXX_DIR" \
    LANEB_REF="$sha" \
    LANEB_OUT="$CORE_SO" \
        bash "$REPO_ROOT/scripts/build_ktpamx_laneb.sh" "$@"

    # Gate on the artifact, never the exit code: the amxx build can exit 0
    # having compiled nothing when its base image is missing.
    [ -s "$CORE_SO" ] || die "no ktpamx_i386.so produced at $CORE_SO"
    [ -s "$LANEB_DIR/dodx_ktp_i386.so" ] || \
        die "no dodx_ktp_i386.so produced — a Lane B core with a production DODX
       module sees bots but records no bot weapon counters"

    echo "$sha" > "$CORE_SHA_FILE"
    echo ""
    echo "[bots] Lane B core in $LANEB_DIR (NOT FOR PRODUCTION)"
    ls -l "$CORE_SO" "$LANEB_DIR/dodx_ktp_i386.so" | sed 's/^/  /'
}

cmd_stage_plugins() {
    [ -d "$MATCHHANDLER_DIR" ] || die "KTPMatchHandler not found at $MATCHHANDLER_DIR"
    mkdir -p "$BOT_PLUGIN_DIR"

    # `.testmatch` is behind `#if defined KTP_TEST_MODE`. A production build
    # does not register the command at all, and the symptom is an unhelpful
    # "Unknown command".
    echo "[bots] building KTP_TEST_MODE KTPMatchHandler"
    ( cd "$MATCHHANDLER_DIR" && KTP_TEST_MODE=1 bash compile.sh )

    local built="$MATCHHANDLER_DIR/compiled/test/KTPMatchHandler.amxx"
    [ -f "$built" ] || die "expected test-mode build at $built"
    cp "$built" "$BOT_PLUGIN_DIR/"

    # The bot server gets its OWN plugin dir: the entrypoint copies
    # /plugins/*.amxx over the image's, so a test-mode KTPMatchHandler left in
    # the shared local/plugins/ would quietly change ktp-game-1 too.
    if [ -f "$REPO_ROOT/local/plugins/KTPHudObserver.amxx" ]; then
        cp "$REPO_ROOT/local/plugins/KTPHudObserver.amxx" "$BOT_PLUGIN_DIR/"
    else
        echo "[bots] NOTE: no local/plugins/KTPHudObserver.amxx — the overlay will have no source"
    fi

    echo ""
    echo "[bots] staged in local/plugins-bots/:"
    ls "$BOT_PLUGIN_DIR" | sed 's/^/  /'
}

cmd_preflight() {
    if ! cmd_has_core; then
        cat >&2 <<EOF

ERROR: no patched ktpamx at $CORE_SO

Without a KTP_LANE_B_FAKECLIENTS build, AMXX cannot see bots at all: the server
boots, accepts bots, plays a map and emits NOTHING — a failure that looks
exactly like a working server.

  make local-bots-amxx

EOF
        exit 1
    fi

    # Same shape as the existing check-artifacts warning, and the same honest
    # scope: it answers "were these built from the same commit", nothing about
    # the fleet. Neither local server tracks the fleet.
    if [ -f "$CORE_SHA_FILE" ] && [ -d "$KTPAMXX_DIR/.git" ]; then
        local bot_sha current_sha
        bot_sha="$(cat "$CORE_SHA_FILE")"
        current_sha="$(git -C "$KTPAMXX_DIR" rev-parse HEAD)"
        if [ "$bot_sha" != "$current_sha" ]; then
            echo ""
            echo "WARNING: bot server core is from a different KTPAMXX commit"
            echo "  bot core:  $bot_sha"
            echo "  current:   $current_sha"
            echo "  ktp-game-1 and ktp-game-2 will differ by more than the bot patch."
            echo "  run 'make local-bots-amxx' to resync"
            echo ""
        fi
    fi
}

case "${1:-}" in
    build-core)    shift; cmd_build_core "$@" ;;
    stage-plugins) shift; cmd_stage_plugins "$@" ;;
    preflight)     shift; cmd_preflight "$@" ;;
    has-core)      cmd_has_core ;;
    *)
        sed -n '2,15p' "${BASH_SOURCE[0]}"
        exit 2
        ;;
esac
