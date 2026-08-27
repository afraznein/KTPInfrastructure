#!/bin/bash
# KTP Post-Swap Verification — run on a game host the morning after a wave.
#
# ktp-scheduled-restart.sh's swap step never rolls back and never retries: a
# `.new` file that fails to `mv -f` into place is simply left where it sat,
# still named `*.new`, still un-activated. That leftover file IS the durable
# record of an incomplete swap — this script just finds it, using the same
# glob set the restart script swaps from.
#
# Usage: ktp-verify-post-swap.sh
# Exit:  0 = no leftover .new files (this host's wave fully activated)
#        1 = one or more leftover .new files found (partial activation)
#
# Read-only. Does not move, delete, or otherwise touch anything it finds.

FOUND=0

PORTS=()
for dir in ~/dod-2701*; do
    [ -d "$dir" ] || continue
    [ -f "$dir/.ktp-disabled" ] && continue
    PORTS+=($(basename "$dir" | sed 's/dod-//'))
done

WARMUP_DIR="${KTP_WARMUP_DIR:-/srv/ktpdata/warmup}"
WARMUP_EXEC="${KTP_WARMUP_EXEC:-dodserver}"
SWAP_BASES=()
for port in "${PORTS[@]}"; do
    SWAP_BASES+=(~/dod-$port/serverfiles)
done
if [ -d "$WARMUP_DIR" ] && [ -x "$WARMUP_DIR/$WARMUP_EXEC" ] && [ ! -f "$WARMUP_DIR/.ktp-disabled" ]; then
    SWAP_BASES+=("$WARMUP_DIR/serverfiles")
fi

for BASE in "${SWAP_BASES[@]}"; do
    port=$(basename "$(dirname "$BASE")"); port=${port#dod-}
    for new_file in "$BASE"/*.new \
                    "$BASE"/dod/addons/ktpamx/dlls/*.new \
                    "$BASE"/dod/addons/ktpamx/modules/*.new \
                    "$BASE"/dod/addons/ktpamx/plugins/*.new; do
        [ -f "$new_file" ] || continue
        echo "UNSWAPPED: [$port] $new_file"
        FOUND=$((FOUND + 1))
    done
done

if [ "$FOUND" -eq 0 ]; then
    echo "OK: no leftover .new files — this host's wave fully activated"
    exit 0
else
    echo "PARTIAL: $FOUND leftover .new file(s) on this host — swap did not fully activate"
    exit 1
fi
