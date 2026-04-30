#!/bin/bash
# KTP HLTV root-level auto-* demo cleanup
#
# The hltv-demo-renamer.service handles auto-*.dem -> canonical filename within
# minutes of MATCH_WINDOW_CLOSE. This cleanup catches the leftovers:
#   - Recordings during dead time (no match active)
#   - Files the renamer never claimed (renamer downtime > 4h grace,
#     malformed plugin log, parser miss, etc.)
#
# ktp-demo-retention.sh only sweeps demos/<friendly>/<matchtype>/*.dem; root
# is its blind spot. This script fills it.
#
# Cron: /etc/cron.d/ktp-demo-cleanup-auto  -- runs daily at 04:45 ET, after
# the 04:00 organize and 04:30 retention pass.
#
# Threshold: anything matching auto*-*.dem at root older than 7 days.
# 7d gives ample buffer for any reasonable renamer-outage recovery.

set -euo pipefail

DEMOS_DIR="/home/hltvserver/hlds/dod"
AGE_DAYS="${AGE_DAYS:-7}"
DRY_RUN="${DRY_RUN:-0}"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

[ -d "$DEMOS_DIR" ] || { echo "[$(ts)] ERROR: $DEMOS_DIR missing" >&2; exit 1; }

# Match files at root (no path separators) named auto*.dem.
# Only sweep root level — `find -maxdepth 1` excludes the organized subfolders.
mapfile -t targets < <(find "$DEMOS_DIR" -maxdepth 1 -type f -name 'auto*.dem' -mtime "+$AGE_DAYS")

if [ "${#targets[@]}" -eq 0 ]; then
    echo "[$(ts)] auto-cleanup: nothing past ${AGE_DAYS}d at root"
    exit 0
fi

total_bytes=0
for f in "${targets[@]}"; do
    sz=$(stat -c '%s' "$f" 2>/dev/null || echo 0)
    total_bytes=$((total_bytes + sz))
done

human_bytes() {
    awk -v b="$1" 'BEGIN{
        if (b>=1073741824) printf "%.2f GB", b/1073741824;
        else if (b>=1048576) printf "%.1f MB", b/1048576;
        else if (b>=1024) printf "%.1f KB", b/1024;
        else printf "%d B", b;
    }'
}

count="${#targets[@]}"
size_str=$(human_bytes "$total_bytes")

if [ "$DRY_RUN" = "1" ]; then
    echo "[$(ts)] DRY_RUN: would delete ${count} files / ${size_str} (>${AGE_DAYS}d at root)"
    for f in "${targets[@]}"; do
        echo "  $(basename "$f")"
    done
    exit 0
fi

echo "[$(ts)] auto-cleanup: deleting ${count} files / ${size_str} (>${AGE_DAYS}d at root)"
for f in "${targets[@]}"; do
    rm -f -- "$f"
done
echo "[$(ts)] auto-cleanup: done"
