#!/usr/bin/env bash
#
# Assert that every plugin a runtime profile loads is actually present as a
# compiled .amxx in a given directory.
#
# Usage: verify-plugin-manifest.sh [--sources <root>] <plugins-dir> <plugins.ini> ...
#
# A plugin listed in plugins.ini but missing from the build is invisible until
# boot, where KTPAMXX reports it as `bad load` under a TRUNCATED name. On the
# shared Tier 1 gate that reads as "the change under test is broken" for every
# consumer, including repos we do not own.
#
# --sources also fails a plugin whose .sma cannot be found under <root>.
# build/plugins/Dockerfile prints `SKIP: ... not found` and returns 0 for an
# absent source, so an un-checked-out plugin repo builds a green image that
# ships one plugin short.

set -uo pipefail

SOURCES_ROOT=""
if [ "${1:-}" = "--sources" ]; then
    SOURCES_ROOT="${2:-}"
    shift 2 || true
fi

PLUGINS_DIR="${1:-}"
shift || true

if [ -z "$PLUGINS_DIR" ] || [ "$#" -eq 0 ]; then
    echo "usage: $0 [--sources <root>] <plugins-dir> <plugins.ini> [<plugins.ini> ...]" >&2
    exit 2
fi

if [ ! -d "$PLUGINS_DIR" ]; then
    echo "ERROR: plugins dir does not exist: $PLUGINS_DIR" >&2
    exit 1
fi

if [ -n "$SOURCES_ROOT" ] && [ ! -d "$SOURCES_ROOT" ]; then
    echo "ERROR: sources root does not exist: $SOURCES_ROOT" >&2
    exit 1
fi

missing=()
sourceless=()
manifests_seen=0

# Every plugin the builder compiles is `<name>.sma` -> `<name>.amxx`, so the
# manifest entry alone locates the source; the dir mapping lives in the
# Dockerfile and is deliberately not duplicated here.
#
# Indexed in ONE walk rather than one per entry: the same 11 plugins appear in
# all three profiles, and a per-entry find of the project root measured 34s a
# lookup on a network drive. Depth-capped and pruned for the same reason —
# sources sit at <root>/<repo>/<name>.sma or <root>/KTPAMXX/plugins/[dod/].
SOURCE_INDEX=""
if [ -n "$SOURCES_ROOT" ]; then
    SOURCE_INDEX="$(find "$SOURCES_ROOT" -maxdepth 4 \
        \( -name .git -o -name node_modules -o -name artifacts \) -prune -o \
        -type f -name '*.sma' -exec basename {} \; 2>/dev/null)"
    if [ -z "$SOURCE_INDEX" ]; then
        echo "ERROR: no .sma found anywhere under $SOURCES_ROOT — wrong root, not a clean tree" >&2
        exit 1
    fi
fi

has_source() {
    printf '%s\n' "$SOURCE_INDEX" | grep -qxF "${1%.amxx}.sma"
}

for manifest in "$@"; do
    if [ ! -f "$manifest" ]; then
        echo "ERROR: manifest not found: $manifest" >&2
        exit 1
    fi

    profile="$(basename "$(dirname "$manifest")")/$(basename "$manifest")"
    entries=0

    while IFS= read -r raw || [ -n "$raw" ]; do
        line="${raw//$'\r'/}"
        line="${line%%;*}"
        line="${line#"${line%%[![:space:]]*}"}"
        plugin="${line%%[[:space:]]*}"
        case "$plugin" in
            *.amxx) ;;
            *) continue ;;
        esac

        entries=$((entries + 1))
        if [ ! -f "$PLUGINS_DIR/$plugin" ]; then
            missing+=("$profile -> $plugin")
        fi
        if [ -n "$SOURCES_ROOT" ] && ! has_source "$plugin"; then
            sourceless+=("$profile -> $plugin (no ${plugin%.amxx}.sma under $SOURCES_ROOT)")
        fi
    done < "$manifest"

    # A zero here means the parse or the path is wrong, not that the profile
    # is clean — without this the whole check passes vacuously.
    if [ "$entries" -eq 0 ]; then
        echo "ERROR: $manifest parsed to ZERO plugin entries — parser or path is wrong" >&2
        exit 1
    fi

    echo "  $profile: $entries entries checked"
    manifests_seen=$((manifests_seen + 1))
done

if [ "$manifests_seen" -eq 0 ]; then
    echo "ERROR: no manifests were checked" >&2
    exit 1
fi

rc=0

if [ "${#missing[@]}" -gt 0 ]; then
    echo "" >&2
    echo "ERROR: plugins.ini loads plugins that were not built:" >&2
    for m in "${missing[@]}"; do
        echo "  - $m" >&2
    done
    echo "" >&2
    echo "Present in $PLUGINS_DIR:" >&2
    ls -1 "$PLUGINS_DIR" >&2 || true
    rc=1
fi

if [ "${#sourceless[@]}" -gt 0 ]; then
    echo "" >&2
    echo "ERROR: plugins.ini loads plugins whose source is absent:" >&2
    for s in "${sourceless[@]}"; do
        echo "  - $s" >&2
    done
    echo "" >&2
    echo "The builder SKIPs a missing source and still exits 0, so this would" >&2
    echo "otherwise publish an image one plugin short." >&2
    rc=1
fi

[ "$rc" -eq 0 ] || exit "$rc"

if [ -n "$SOURCES_ROOT" ]; then
    echo "OK: every plugins.ini entry is present in $PLUGINS_DIR and has a source under $SOURCES_ROOT"
else
    echo "OK: every plugins.ini entry is present in $PLUGINS_DIR"
fi
