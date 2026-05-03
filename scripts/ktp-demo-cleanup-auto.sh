#!/bin/bash
# KTP HLTV root-level auto-* demo cleanup
#
# The hltv-demo-renamer.service handles auto-*.dem -> canonical filename within
# seconds of MATCH_WINDOW_CLOSE. This cleanup catches the leftovers:
#   - Recordings during dead time (no match active) — the bulk of volume since
#     KTPHLTVRecorder 1.7.0 F+A architecture (always-on recording, activated
#     2026-04-29). At 24 active HLTV instances, dead-time recordings accrete
#     at ~75 GB/day fleet-wide.
#   - Files the renamer never claimed (renamer downtime past grace,
#     malformed plugin log, parser miss, etc.)
#
# ktp-demo-retention.sh only sweeps demos/<friendly>/<matchtype>/*.dem; root
# is its blind spot. This script fills it.
#
# Cron: /etc/cron.d/ktp-demo-cleanup-auto -- runs every 30 min.
#
# Threshold: anything matching auto*.dem at root older than 6 hours.
# 6h covers a full DoD match plus renamer-recovery grace; renamer normally
# renames within seconds of MATCH_WINDOW_CLOSE, and renamer outages page via
# the systemd OnFailure= alert framework well before this window elapses.
#
# Pre-F+A this script ran daily with a 7-day threshold (deployed 2026-04-29);
# F+A activation the same day flipped the accumulation curve and required the
# tighter cadence + threshold. Retuned 2026-05-03 after the 100%-disk incident.

set -euo pipefail

DEMOS_DIR="/home/hltvserver/hlds/dod"
AGE_MINUTES="${AGE_MINUTES:-360}"
DRY_RUN="${DRY_RUN:-0}"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

[ -d "$DEMOS_DIR" ] || { echo "[$(ts)] ERROR: $DEMOS_DIR missing" >&2; exit 1; }

# Match files at root (no path separators) named auto*.dem.
# Only sweep root level — `find -maxdepth 1` excludes the organized subfolders.
mapfile -t targets < <(find "$DEMOS_DIR" -maxdepth 1 -type f -name 'auto*.dem' -mmin "+$AGE_MINUTES")

if [ "${#targets[@]}" -eq 0 ]; then
    echo "[$(ts)] auto-cleanup: nothing past ${AGE_MINUTES}m at root"
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
    echo "[$(ts)] DRY_RUN: would delete ${count} files / ${size_str} (>${AGE_MINUTES}m at root)"
    for f in "${targets[@]}"; do
        echo "  $(basename "$f")"
    done
    exit 0
fi

echo "[$(ts)] auto-cleanup: deleting ${count} files / ${size_str} (>${AGE_MINUTES}m at root)"
for f in "${targets[@]}"; do
    rm -f -- "$f"
done
echo "[$(ts)] auto-cleanup: done"
