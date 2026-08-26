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

# Git Bash / MSYS mangles container-internal paths in docker argv (see
# scripts/docker-nopathconv.sh for the full story). Route docker through the
# wrapper via the extension point the upstream builder already exposes, rather
# than changing the environment for the whole script — `git -C /d/Git/...`
# needs the conversion that docker must not have.
#
# Upstream's answer is "run from a real Linux shell"; this box has no WSL
# distro but Docker Desktop, so the wrapper is what makes the lane usable here.
case "$(uname -s 2>/dev/null || echo unknown)" in
    MINGW*|MSYS*)
        export LANEB_DOCKER="${LANEB_DOCKER:-$REPO_ROOT/scripts/docker-nopathconv.sh}"
        ;;
esac

# Our own docker calls need the same treatment as the builder's.
DOCKER="${LANEB_DOCKER:-docker}"
LANEB_DIR="${LANEB_DIR:-$REPO_ROOT/local/lane-b}"
BOT_PLUGIN_DIR="${BOT_PLUGIN_DIR:-$REPO_ROOT/local/plugins-bots}"
PROJECT_ROOT="${KTP_PROJECT_ROOT:-$(cd "$REPO_ROOT/.." && pwd)}"

KTPAMXX_DIR="$PROJECT_ROOT/KTPAMXX"
MATCHHANDLER_DIR="$PROJECT_ROOT/KTPMatchHandler"
CORE_SO="$LANEB_DIR/ktpamx_i386.so"
CORE_SHA_FILE="$LANEB_DIR/KTPAMXX_SOURCE_SHA"

die() { echo "ERROR: $*" >&2; exit 1; }

# The KTPAMXX commit the installed core was built from, as a bare SHA.
#
# Two files can carry it and only one is always present:
#   ktpamx_i386.so.sha   "<sha>-<recipe_hash>", written by build_ktpamx_laneb.sh
#                        on success -- EVERY producer path writes this one
#   KTPAMXX_SOURCE_SHA   bare sha, written by cmd_build_core below -- only the
#                        `make local-bots-amxx` path writes it
#
# Prefer the bare file, fall back to the stamp's first field, so a core built by
# running build_ktpamx_laneb.sh directly still gets the skew warnings instead of
# silently skipping them.
core_source_sha() {
    if [ -f "$CORE_SHA_FILE" ]; then
        cat "$CORE_SHA_FILE"
    elif [ -f "$CORE_SO.sha" ]; then
        cut -d- -f1 < "$CORE_SO.sha"
    fi
}

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
    #
    # KTPMatchHandler's own compile.sh is not used here, but NOT because it
    # hardcodes a path -- it honours $KTPAMXX_ROOT and falls back to ../KTPAMXX
    # (compile.sh:57-62). The reason is that it runs amxxpc directly, and amxxpc
    # is a 32-bit Linux binary: there is nothing to run it on a Windows host, and
    # it needs the Lane B checkout's compiler rather than whatever tree it finds.
    #
    # So this reproduces its recipe step for step in a container -- same
    # temp-tree layout, same CRLF strip, same build_info.inc, same amxxpc argv
    # including the trailing KTP_TEST_MODE=1 positional. Keep the two in step.
    #
    # Compiler comes from the Lane B checkout, so the plugin is built by the
    # SAME KTPAMXX source as the core it will run against.
    local laneb_checkout="${LANEB_WORK:-$HOME/ktp}/KTPAMXX-laneb"
    local scripting="$laneb_checkout/obj-linux/packages/base/addons/ktpamx/scripting"
    [ -f "$scripting/amxxpc" ] || die "no amxxpc at $scripting
       run 'make local-bots-amxx' first — it builds the compiler as a side
       effect of building the core, from the same source"

    local sha dirty="" build_time
    sha="$(git -C "$MATCHHANDLER_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
    if [ "$sha" != "unknown" ] && [ -n "$(git -C "$MATCHHANDLER_DIR" status --porcelain)" ]; then
        dirty="-dirty"
    fi
    build_time="$(date -u +%Y-%m-%dT%H:%MZ)"

    echo "[bots] compiling KTPMatchHandler ${sha}${dirty} with KTP_TEST_MODE=1"
    "$DOCKER" run --rm \
        -v "$scripting:/ktpamx/scripting:ro" \
        -v "$laneb_checkout/plugins/include:/ktpamx/include:ro" \
        -v "$MATCHHANDLER_DIR:/src:ro" \
        -v "$BOT_PLUGIN_DIR:/out" \
        -e KTP_BUILD_SHA="${sha}${dirty}" \
        -e KTP_BUILD_TIME="$build_time" \
        ktp-amxx-builder:laneb bash -c '
            set -e
            rm -rf /tmp/ktpbuild && mkdir -p /tmp/ktpbuild
            cd /tmp/ktpbuild
            cp /ktpamx/scripting/amxxpc /ktpamx/scripting/amxxpc32.so .
            cp -r /ktpamx/include ./include
            chmod +x amxxpc
            sed "s/\r$//" /src/KTPMatchHandler.sma > KTPMatchHandler.sma
            for inc in /src/*.inc; do
                [ -f "$inc" ] && sed "s/\r$//" "$inc" > "$(basename "$inc")"
            done
            printf "#define KTP_BUILD_SHA \"%s\"\n#define KTP_BUILD_TIME \"%s\"\n" \
                "$KTP_BUILD_SHA" "$KTP_BUILD_TIME" > include/build_info.inc

            # Compile BOTH ways and compare code size.
            #
            # This is the only cheap way to prove the define actually took. An
            # .amxx is a compressed XXMA container, so grepping the artifact for
            # "amx_ktp_testmatch" finds nothing whether the flag worked or not
            # -- no string in any .amxx is greppable, not even "amxmodx". And
            # amxxpc exits 0 on failure, so the exit code proves nothing either.
            #
            # Same source, one extra -D: if KTP_TEST_MODE were ignored the two
            # code sizes would be identical. amxxpc runs in about a second, so
            # the second compile is free.
            ./amxxpc KTPMatchHandler.sma -i./include -i. -obase.amxx > base.log 2>&1
            ./amxxpc KTPMatchHandler.sma -i./include -i. -oKTPMatchHandler.amxx KTP_TEST_MODE=1 > test.log 2>&1
            cat test.log
            # || true: under set -e a non-matching grep exits 1 and kills the
            # script HERE, before the explanatory branch below ever runs -- so
            # the failure this check exists to explain would surface as a bare
            # non-zero exit.
            base_code=$(grep -oE "Code size:[[:space:]]+[0-9]+" base.log | grep -oE "[0-9]+" || true)
            test_code=$(grep -oE "Code size:[[:space:]]+[0-9]+" test.log | grep -oE "[0-9]+" || true)
            echo "[bots] code size: base=${base_code} test-mode=${test_code}"
            test -s KTPMatchHandler.amxx
            if [ -z "$base_code" ] || [ -z "$test_code" ] || [ "$test_code" -le "$base_code" ]; then
                echo "KTP_TEST_MODE did not take: test-mode build is not larger" >&2
                echo "than the plain build, so amx_ktp_testmatch is absent and" >&2
                echo ".testmatch would fail at runtime with Unknown command." >&2
                exit 1
            fi
            cp KTPMatchHandler.amxx /out/
        '

    local built="$BOT_PLUGIN_DIR/KTPMatchHandler.amxx"
    [ -s "$built" ] || die "no KTPMatchHandler.amxx produced"

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

    # The core has to match the ENGINE, not just KTPAMXX HEAD.
    #
    # ktpamx asserts a minimum ReHLDS API at load and REFUSES if the engine is
    # older: "[KTP AMX] FATAL: ReHLDS API rejected (need >= 3.16) ... stage
    # engine+core+reapi+dodx together." When that fires, AMXX loads no plugins
    # at all -- so the HUD receives nothing while the server looks completely
    # healthy and `status` still lists bots. Same silent shape as a bot-blind
    # core, different cause, and it is why this is checked and not assumed.
    #
    # The base image is built from artifacts/<VERSION>/, engine and ktpamx
    # together, so the artifacts' own ktpamx SHA is the right thing to compare
    # the core against: equal means they came out of one staging.
    # VERSION, not latest: the Makefile builds images from artifacts/$(VERSION)
    # and publish-latest OVERLAYS without deleting, so latest can name a different
    # staging than the image actually came from -- and this guard would then
    # compare against a core nobody is running.
    local art_sha_file="$REPO_ROOT/artifacts/${ARTIFACTS_VERSION:-${VERSION:-latest}}/ktpamx/SOURCE_SHA"
    local core_sha art_sha
    core_sha="$(core_source_sha)"
    if [ -n "$core_sha" ] && [ -f "$art_sha_file" ]; then
        art_sha="$(cat "$art_sha_file")"
        if [ "$core_sha" != "$art_sha" ]; then
            echo ""
            echo "WARNING: bot core and the base image come from different stagings"
            echo "  bot core:   $core_sha"
            echo "  artifacts:  $art_sha"
            echo "  If the engine is the older of the two, ktpamx will reject it at"
            echo "  load and NO AMXX plugin will run -- the server still boots and"
            echo "  still accepts bots, so this looks like a working stack."
            echo "  Fix: 'make build' (stages engine+core together), then"
            echo "       'make local-build' and 'make local-bots-amxx'."
            echo ""
        fi
    fi

    # Same shape as the existing check-artifacts warning, and the same honest
    # scope: it answers "were these built from the same commit", nothing about
    # the fleet. Neither local server tracks the fleet.
    local bot_sha current_sha
    bot_sha="$(core_source_sha)"
    if [ -n "$bot_sha" ] && [ -d "$KTPAMXX_DIR/.git" ]; then
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
