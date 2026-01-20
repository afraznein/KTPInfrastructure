#!/bin/bash
# =============================================================================
# KTP Game Server Log Rotation Script
# - Compresses logs older than 120 days
# - Deletes compressed logs older than 365 days
# Runs weekly via cron
# =============================================================================

LOG_FILE="$HOME/log/log-rotation.log"
COMPRESS_DAYS=120
DELETE_DAYS=365
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

log "========== Log Rotation Started =========="
log "Compress after: $COMPRESS_DAYS days | Delete after: $DELETE_DAYS days"
[ "$DRY_RUN" = true ] && log "DRY RUN MODE - No changes will be made"

compressed=0
deleted=0
freed=0

# Function to compress old log files
compress_old_logs() {
    local dir="$1"
    local pattern="$2"
    
    [ ! -d "$dir" ] && return
    
    while IFS= read -r -d '' file; do
        size=$(stat -c%s "$file" 2>/dev/null || echo 0)
        if [ "$DRY_RUN" = true ]; then
            log "[DRY] Would compress: $file ($((size/1024))KB)"
        else
            gzip "$file" && log "Compressed: $file ($((size/1024))KB)"
        fi
        ((compressed++))
    done < <(find "$dir" -type f -name "$pattern" ! -name "*.gz" -mtime +$COMPRESS_DAYS -print0 2>/dev/null)
}

# Function to delete old compressed files
delete_old_archives() {
    local dir="$1"
    local pattern="$2"
    
    [ ! -d "$dir" ] && return
    
    while IFS= read -r -d '' file; do
        size=$(stat -c%s "$file" 2>/dev/null || echo 0)
        if [ "$DRY_RUN" = true ]; then
            log "[DRY] Would delete: $file ($((size/1024))KB)"
        else
            rm -f "$file" && log "Deleted: $file ($((size/1024))KB)"
        fi
        ((deleted++))
        ((freed+=size))
    done < <(find "$dir" -type f -name "$pattern" -mtime +$DELETE_DAYS -print0 2>/dev/null)
}

# Process LinuxGSM console logs
for server_dir in $HOME/dod-2701*/log/console; do
    compress_old_logs "$server_dir" "*.log"
    delete_old_archives "$server_dir" "*.gz"
done

# Process LinuxGSM script logs
for server_dir in $HOME/dod-2701*/log/script; do
    compress_old_logs "$server_dir" "*.log"
    delete_old_archives "$server_dir" "*.gz"
done

# Process game server logs (L*.log files)
for server_dir in $HOME/dod-2701*/serverfiles/dod/logs; do
    compress_old_logs "$server_dir" "L*.log"
    delete_old_archives "$server_dir" "*.gz"
done

# Truncate monitor.log if larger than 50MB (keep last 10000 lines)
MONITOR_LOG="$HOME/log/monitor.log"
if [ -f "$MONITOR_LOG" ]; then
    size=$(stat -c%s "$MONITOR_LOG" 2>/dev/null || echo 0)
    if [ $size -gt 52428800 ]; then
        if [ "$DRY_RUN" = true ]; then
            log "[DRY] Would truncate monitor.log ($((size/1024/1024))MB -> keep last 10000 lines)"
        else
            tail -n 10000 "$MONITOR_LOG" > "$MONITOR_LOG.tmp" && mv "$MONITOR_LOG.tmp" "$MONITOR_LOG"
            new_size=$(stat -c%s "$MONITOR_LOG" 2>/dev/null || echo 0)
            log "Truncated monitor.log: $((size/1024/1024))MB -> $((new_size/1024/1024))MB"
            ((freed+=size-new_size))
        fi
    fi
fi

log "========== Log Rotation Complete =========="
log "Compressed: $compressed | Deleted: $deleted | Space freed: $((freed/1024/1024))MB"
