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

# classify_missing: for a CRASH-RISK miss, see if a nearby file might be what
# the .bsp actually means. Sets globals MISS_CLASS and MISS_VARIANT.
#   MISSING       — nothing similar in the same dir; real crash risk
#   CASE-DIFF     — case-insensitive exact match exists in same dir; Linux
#                   engine's filesystem_stdio.so usually resolves these
#   RENAME-CHECK  — same-stem prefix variant exists (foo.mdl vs foo1k.mdl);
#                   operator decides whether to symlink, rename, or source
# Caller guarantees the case-sensitive file does NOT exist.
classify_missing() {
    local asset="$1"
    local dir; dir="$SERVERFILES/$(dirname "$asset")"
    local file; file=$(basename "$asset")
    local stem="${file%.*}"
    local ext="${file##*.}"

    MISS_CLASS=MISSING
    MISS_VARIANT=""

    [ ! -d "$dir" ] && return

    # Case-insensitive exact match in the same dir.
    local exact
    exact=$(find "$dir" -maxdepth 1 -iname "$file" -type f 2>/dev/null | head -1)
    if [ -n "$exact" ]; then
        MISS_CLASS=CASE-DIFF
        MISS_VARIANT=$(basename "$exact")
        return
    fi

    # Same-stem-prefix variant (e.g. woodgibs -> woodgibs1k, gib_a -> gib_a_v2).
    local variants
    variants=$(find "$dir" -maxdepth 1 -iname "${stem}*.${ext}" -type f 2>/dev/null | sort | head -3)
    if [ -n "$variants" ]; then
        MISS_CLASS=RENAME-CHECK
        local first; first=$(echo "$variants" | head -1 | xargs -I{} basename {})
        local count; count=$(echo "$variants" | wc -l)
        if [ "$count" -gt 1 ]; then
            MISS_VARIANT="$first (+$((count - 1)) more)"
        else
            MISS_VARIANT="$first"
        fi
    fi
}

TOTAL_CRASH=0
TOTAL_RENAME=0
TOTAL_CASE=0
TOTAL_WARN=0
MAPS_WITH_CRASH=0
MAPS_WITH_RENAME=0
MAPS_WITH_CASE=0
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
    rename_missing=""
    case_missing=""
    warn_missing=""
    crash_n=0
    rename_n=0
    case_n=0
    warn_n=0

    while IFS= read -r asset; do
        [ -z "$asset" ] && continue
        [ -f "$SERVERFILES/$asset" ] && continue
        sev=$(asset_severity "$asset")
        if [ "$sev" = "CRASH" ]; then
            classify_missing "$asset"
            case "$MISS_CLASS" in
                MISSING)
                    crash_missing+="    [CRASH-RISK]   $asset"$'\n'
                    crash_n=$((crash_n + 1))
                    ;;
                RENAME-CHECK)
                    rename_missing+="    [RENAME-CHECK] $asset    (nearby: $MISS_VARIANT)"$'\n'
                    rename_n=$((rename_n + 1))
                    ;;
                CASE-DIFF)
                    case_missing+="    [CASE-DIFF]    $asset    (on-disk: $MISS_VARIANT — engine likely resolves)"$'\n'
                    case_n=$((case_n + 1))
                    ;;
            esac
        else
            [ $INCLUDE_WARN -eq 0 ] && continue
            warn_missing+="    [WARN]         $asset"$'\n'
            warn_n=$((warn_n + 1))
        fi
    done <<< "$assets"

    TOTAL_CRASH=$((TOTAL_CRASH + crash_n))
    TOTAL_RENAME=$((TOTAL_RENAME + rename_n))
    TOTAL_CASE=$((TOTAL_CASE + case_n))
    TOTAL_WARN=$((TOTAL_WARN + warn_n))
    [ $crash_n -gt 0 ]  && MAPS_WITH_CRASH=$((MAPS_WITH_CRASH + 1))
    [ $rename_n -gt 0 ] && MAPS_WITH_RENAME=$((MAPS_WITH_RENAME + 1))
    [ $case_n -gt 0 ]   && MAPS_WITH_CASE=$((MAPS_WITH_CASE + 1))
    [ $warn_n -gt 0 ]   && MAPS_WITH_WARN=$((MAPS_WITH_WARN + 1))

    if [ -n "$crash_missing$rename_missing$case_missing$warn_missing" ]; then
        echo
        # Header reflects worst category present (FAIL > INVESTIGATE > INFO > WARN).
        if [ -n "$crash_missing" ]; then
            echo "FAIL: $name"
        elif [ -n "$rename_missing" ]; then
            echo "INVESTIGATE: $name"
        elif [ -n "$case_missing" ]; then
            echo "INFO: $name"
        else
            echo "WARN: $name"
        fi
        [ -n "$crash_missing" ]  && printf '%s' "$crash_missing"
        [ -n "$rename_missing" ] && printf '%s' "$rename_missing"
        [ -n "$case_missing" ]   && printf '%s' "$case_missing"
        [ -n "$warn_missing" ]   && printf '%s' "$warn_missing"
    elif [ $QUIET -eq 0 ]; then
        echo "  OK: $name ($(echo "$assets" | wc -l) refs)"
    fi
done

echo
echo "Summary:"
echo "  FAIL         (CRASH-RISK)   — $MAPS_WITH_CRASH map(s),  $TOTAL_CRASH ref(s)"
echo "  INVESTIGATE  (RENAME-CHECK) — $MAPS_WITH_RENAME map(s), $TOTAL_RENAME ref(s)"
echo "  INFO         (CASE-DIFF)    — $MAPS_WITH_CASE map(s),  $TOTAL_CASE ref(s)"
if [ $INCLUDE_WARN -eq 1 ]; then
    echo "  WARN         (sound/tex)    — $MAPS_WITH_WARN map(s),  $TOTAL_WARN ref(s)"
else
    echo "  (Pass --all to also list WARN-level missing sounds/textures/overviews.)"
fi
echo
echo "FAIL and RENAME-CHECK both contribute to exit code 1: a RENAME-CHECK"
echo "file is still ABSENT on disk (the engine Sys_Errors on it exactly like"
echo "a FAIL — the ATL1 2026-05-11 crash was bakery_counter3.mdl missing with"
echo "bakery_counter31.mdl present, which the old exit logic passed). The"
echo "annotation just tells the operator a likely rename-source exists."
echo "CASE-DIFF stays informational (Linux servers ship case-preserved files)."

if [ $MAPS_WITH_CRASH -gt 0 ] || [ $MAPS_WITH_RENAME -gt 0 ]; then
    exit 1
fi
exit 0
