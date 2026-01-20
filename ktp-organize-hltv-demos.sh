#!/bin/bash
# =============================================================================
# KTP HLTV Demo Organization Script
# Organizes demos into: Hostname / MatchType (e.g., ATL1/ktp/)
# Runs nightly at 4:00 AM EST via cron
# Web accessible at: http://74.91.112.242/demos/
# =============================================================================

DEMO_DIR="/home/hltvserver/hlds/dod"
LOG_FILE="/var/log/ktp-demo-organize.log"
DRY_RUN=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run) DRY_RUN=true; shift ;;
        *) shift ;;
    esac
done

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

log "========== Demo Organization Started =========="
[ "$DRY_RUN" = true ] && log "DRY RUN MODE - No files will be moved"

cd "$DEMO_DIR" || { log "ERROR: Cannot access $DEMO_DIR"; exit 1; }

# Counters
moved=0
skipped=0
errors=0

# Process each .dem file in the root directory (not subdirs)
for demo in *.dem; do
    # Skip if no matches (glob didn't expand)
    [ -e "$demo" ] || continue

    matchtype=""
    hostname=""

    # NEW FORMAT (v0.10.59+): <matchtype>_<timestamp>-<shorthost>-<hltv_ts>-<map>.dem
    # Example: ktp_1768174986-ATL1-2601111843-dod_armory_b6.dem
    # Example: scrim_1768174986-DAL2-2601111843-dod_anzio.dem
    if [[ "$demo" =~ ^([a-z0-9]+)_([0-9]+)-([A-Z]+[0-9]*)-([0-9]+)-(.+)\.dem$ ]]; then
        matchtype="${BASH_REMATCH[1]}"
        hostname="${BASH_REMATCH[3]}"

    # NEW FORMAT 1.3: <matchtype>_1.3-<queueid>-<shorthost>-<hltv_ts>-<map>.dem
    # Example: 12man_1.3-5031-ATL2-2601122113-dod_thunder2.dem
    elif [[ "$demo" =~ ^([a-z0-9]+)_1\.3-([0-9]+)-([A-Z]+[0-9]*)-([0-9]+)-(.+)\.dem$ ]]; then
        matchtype="${BASH_REMATCH[1]}"
        hostname="${BASH_REMATCH[3]}"
    fi

    # If we matched a format, organize the file
    if [[ -n "$matchtype" && -n "$hostname" ]]; then
        # Build target path: hostname/matchtype/
        target_dir="demos/${hostname}/${matchtype}"
        target_path="${target_dir}/${demo}"

        if [ "$DRY_RUN" = true ]; then
            log "[DRY] Would move: $demo -> $target_path"
            ((moved++))
        else
            # Create directory structure if needed (with web-accessible permissions)
            mkdir -p "$target_dir"
            chown hltvserver:www-data "$target_dir"
            chmod 755 "$target_dir"

            if mv "$demo" "$target_path" 2>/dev/null; then
                # Set web-accessible permissions on the file
                chown hltvserver:www-data "$target_path"
                chmod 644 "$target_path"
                log "Moved: $demo -> $target_path"
                ((moved++))
            else
                log "ERROR: Failed to move $demo"
                ((errors++))
            fi
        fi
    else
        log "Skipped (unrecognized format): $demo"
        ((skipped++))
    fi
done

log "========== Demo Organization Complete =========="
log "Moved: $moved | Skipped: $skipped | Errors: $errors"

# Ensure parent directories have correct permissions for web access
if [ "$DRY_RUN" != true ] && [ -d "demos" ]; then
    chown hltvserver:www-data demos
    chmod 755 demos
    # Fix permissions on all hostname/matchtype directories
    find demos -type d -exec chown hltvserver:www-data {} \;
    find demos -type d -exec chmod 755 {} \;
fi

# Cleanup empty log if nothing happened
if [ $moved -eq 0 ] && [ $skipped -eq 0 ] && [ $errors -eq 0 ]; then
    log "No demos to process"
fi
