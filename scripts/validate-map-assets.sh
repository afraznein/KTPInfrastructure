#!/bin/bash
# validate-map-assets.sh — pre-flight check for missing map assets.
#
# Walks dod/maps/*.bsp and for each map, verifies referenced assets exist
# on disk. By default reports only CRASH-RISK misses (.mdl/.spr — the
# severity that took down ATL1 on 2026-05-11 with a missing
# bakery_counter3.mdl that Mod_LoadModel Sys_Error'd on). Pass --all to
# also include WARN-level misses (.wav silent fallback, .tga pink texture)
# — these are noisier and many "missing" entries are loaded from .pak/.wad
# archives we don't introspect.
#
# Source-of-truth precedence per map:
#   1. Sibling .res file (RESGen-generated, lists FastDL-served assets)
#   2. .bsp strings fallback (catches entries .res may have missed)
# Skybox tga references come from the .res; we deliberately do NOT
# derive them from the worldspawn "skyname" key (avoids the sky_<name>
# / sky_sky_<name> ambiguity when mappers prefix the value themselves).
#
# Usage:
#   validate-map-assets.sh                       # auto-detect, crash-risk only
#   validate-map-assets.sh --all                 # also include WARN-level
#   validate-map-assets.sh --maps-dir <path>     # explicit dod/ path
#   validate-map-assets.sh map1.bsp map2.bsp     # check specific bsps
#   validate-map-assets.sh --quiet               # only print FAIL/WARN lines
#
# Auto-detect order for $SERVERFILES/dod:
#   /home/dodserver/dod-27015/serverfiles/dod
#   ./dod
#
# Exit:
#   0 — no CRASH-RISK assets missing
#   1 — at least one CRASH-RISK asset missing (any map)
#   2 — usage error / can't find maps dir

set -u -o pipefail

QUIET=0
INCLUDE_WARN=0
SERVERFILES=""
SPECIFIC_BSPS=()

while [ $# -gt 0 ]; do
    case "$1" in
        --maps-dir)  SERVERFILES="$2"; shift 2 ;;
        --quiet|-q)  QUIET=1; shift ;;
        --all)       INCLUDE_WARN=1; shift ;;
        -h|--help)
            sed -n '/^# Usage/,/^# Exit/p' "$0" | sed 's/^# //;s/^#//'
            exit 0
            ;;
        --) shift; while [ $# -gt 0 ]; do SPECIFIC_BSPS+=("$1"); shift; done ;;
        -*) echo "ERROR: unknown option: $1" >&2; exit 2 ;;
        *)  SPECIFIC_BSPS+=("$1"); shift ;;
    esac
done

if [ -z "$SERVERFILES" ]; then
    for candidate in \
        /home/dodserver/dod-27015/serverfiles/dod \
        ./dod \
        "$(pwd)"
    do
        if [ -d "$candidate/maps" ]; then
            SERVERFILES="$candidate"
            break
        fi
    done
fi

if [ -z "$SERVERFILES" ] || [ ! -d "$SERVERFILES/maps" ]; then
    echo "ERROR: couldn't find dod/maps/ directory. Pass --maps-dir <path>." >&2
    exit 2
fi

if [ ${#SPECIFIC_BSPS[@]} -gt 0 ]; then
    BSPS=("${SPECIFIC_BSPS[@]}")
else
    mapfile -t BSPS < <(find "$SERVERFILES/maps" -maxdepth 1 -name '*.bsp' -type f | sort)
fi

[ ${#BSPS[@]} -eq 0 ] && { echo "No .bsp files found in $SERVERFILES/maps"; exit 0; }

[ $QUIET -eq 0 ] && echo "Checking ${#BSPS[@]} map(s) under $SERVERFILES (crash-risk only$([ $INCLUDE_WARN -eq 1 ] && echo ' + warns'))..."

# Severity classification.
# CRASH: missing .mdl Sys_Errors out of Mod_LoadModel (the bug we're catching).
#        .spr precache failures CAN also Sys_Error in some code paths, so
#        treat as CRASH-RISK too — false positives here are rare-but-possible.
# WARN:  missing .wav (silent), .tga/.bmp (pink), .txt overview (no minimap).
asset_severity() {
    case "$1" in
        *.mdl|*.spr) echo CRASH ;;
        *)           echo WARN ;;
    esac
}

TOTAL_CRASH=0
TOTAL_WARN=0
MAPS_WITH_CRASH=0
MAPS_WITH_WARN=0

for bsp in "${BSPS[@]}"; do
    name=$(basename "$bsp" .bsp)
    res="${bsp%.bsp}.res"

    # Source 1: .res file (primary)
    if [ -f "$res" ]; then
        assets=$(grep -oE '(models|sound|sprites|gfx/env|overviews)/\S+\.(mdl|wav|spr|tga|bmp|txt)' \
                 "$res" 2>/dev/null | tr -d '\r' | sort -u)
    else
        assets=""
    fi

    # Source 2: .bsp strings fallback / supplement
    bsp_assets=$(strings -n 6 "$bsp" 2>/dev/null \
        | grep -oE '(models|sound|sprites|gfx/env|overviews)/[^"[:space:]]+\.(mdl|wav|spr|tga|bmp|txt)' \
        | sort -u)
    assets=$(printf '%s\n%s\n' "$assets" "$bsp_assets" | sort -u | sed '/^$/d')

    [ -z "$assets" ] && continue

    crash_missing=""
    warn_missing=""
    crash_n=0
    warn_n=0

    while IFS= read -r asset; do
        [ -z "$asset" ] && continue
        [ -f "$SERVERFILES/$asset" ] && continue
        sev=$(asset_severity "$asset")
        if [ "$sev" = "CRASH" ]; then
            crash_missing+="    [CRASH-RISK] $asset"$'\n'
            crash_n=$((crash_n + 1))
        else
            [ $INCLUDE_WARN -eq 0 ] && continue
            warn_missing+="    [WARN] $asset"$'\n'
            warn_n=$((warn_n + 1))
        fi
    done <<< "$assets"

    TOTAL_CRASH=$((TOTAL_CRASH + crash_n))
    TOTAL_WARN=$((TOTAL_WARN + warn_n))
    [ $crash_n -gt 0 ] && MAPS_WITH_CRASH=$((MAPS_WITH_CRASH + 1))
    [ $warn_n -gt 0 ]  && MAPS_WITH_WARN=$((MAPS_WITH_WARN + 1))

    if [ -n "$crash_missing" ] || [ -n "$warn_missing" ]; then
        echo
        if [ -n "$crash_missing" ]; then
            echo "FAIL: $name"
        else
            echo "WARN: $name"
        fi
        [ -n "$crash_missing" ] && printf '%s' "$crash_missing"
        [ -n "$warn_missing" ]  && printf '%s' "$warn_missing"
    elif [ $QUIET -eq 0 ]; then
        echo "  OK: $name ($(echo "$assets" | wc -l) refs)"
    fi
done

echo
if [ $INCLUDE_WARN -eq 1 ]; then
    echo "Summary: $MAPS_WITH_CRASH map(s) with CRASH-RISK assets missing ($TOTAL_CRASH refs),"
    echo "         $MAPS_WITH_WARN map(s) with WARN-level missing ($TOTAL_WARN refs)."
else
    echo "Summary: $MAPS_WITH_CRASH map(s) with CRASH-RISK assets missing ($TOTAL_CRASH refs)."
    echo "         (Pass --all to also list WARN-level missing sounds/textures/overviews.)"
fi

[ $MAPS_WITH_CRASH -gt 0 ] && exit 1
exit 0
