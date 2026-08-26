#!/bin/bash
# KTP retired-credential carrier purge (data server, root)
#
# Rotated secrets keep living in backup copies -- *.bak-*, *.cfg.bak*, and
# compressed archives -- long after the value itself is dead. Every value found
# so far was already rotated, so this is hygiene rather than exposure. The point
# is that dead values age out unattended instead of needing another census: that
# census was re-derived four times and produced a different number each time,
# which is the argument for a dated rule instead of a sweep.
#
# Matches on NAME and AGE only. It never greps for a secret, so no credential
# appears in this script, its arguments, or its log -- which is what makes it
# safe to keep in a public repository.
#
# EXCLUSIONS, each load-bearing:
#   - $PROTECTED_DIR (default /opt/backups) holds the real database dumps on
#     their own 28-day prune and they are the ONLY database copies that exist.
#     Guarded twice: it is never descended into, and every candidate is
#     re-checked against it by resolved path before deletion.
#   - Shell and client histories (.bash_history, .mysql_history, anywhere) are
#     NEVER touched. They need a deliberate decision, not a name-and-age rule.
#   - *fallback* files are referenced by nginx and are not backups.
#   - Live configuration is not backup-shaped and is not matched. Only the
#     suffixes in CARRIER_PATTERNS are considered.
#
# DRY_RUN defaults to 1. This script reports and does nothing until it is
# explicitly told otherwise, because the first real run deletes everything back
# to the retention horizon at once.
#
# Cron: /etc/cron.d/ktp-credential-carrier-purge (staged disabled on install).
# Canonical copy: KTPInfrastructure/scripts/.

set -euo pipefail

RETENTION_DAYS="${RETENTION_DAYS:-90}"
DRY_RUN="${DRY_RUN:-1}"
PROTECTED_DIR="${PROTECTED_DIR:-/opt/backups}"
SCAN_DIRS="${SCAN_DIRS:-/home /opt /root /etc /usr/local/bin /srv /var/backups}"

# Backup-shaped suffixes only. Deliberately excludes *.tmp: FastDL serves live
# .ztmp assets and a loose tmp glob is one edit away from matching them.
CARRIER_PATTERNS=(
    '*.bak' '*.bak-*' '*.bak.*' '*.bak_*'
    '*.cfg.bak*' '*.conf.bak*'
    '*.orig' '*.old' '*.save'
    '*.pre-*' '*-backup-*' '*.backup'
)

ts() { date '+%Y-%m-%d %H:%M:%S'; }

echo "[$(ts)] carrier purge starting: retention=${RETENTION_DAYS}d dry_run=${DRY_RUN} protected=${PROTECTED_DIR}"

# A missing protected dir means the assumption behind this script no longer
# holds. Refuse rather than run with one guard silently absent.
if [ ! -d "$PROTECTED_DIR" ]; then
    echo "[$(ts)] FATAL: protected dir $PROTECTED_DIR does not exist -- refusing to run"
    exit 1
fi
protected_resolved=$(readlink -f "$PROTECTED_DIR")

# Deleting a file the purge itself protects would be silent, so verify by
# resolved path rather than by string prefix.
is_protected() {
    local p; p=$(readlink -f "$1" 2>/dev/null) || return 0   # unresolvable -> treat as protected
    case "$p" in
        "$protected_resolved"|"$protected_resolved"/*) return 0 ;;
    esac
    case "$(basename "$p")" in
        .bash_history|.mysql_history|.psql_history|*fallback*) return 0 ;;
    esac
    return 1
}

total=0
bytes=0

for dir in $SCAN_DIRS; do
    [ -d "$dir" ] || { echo "[$(ts)] skip $dir (absent)"; continue; }

    # Per-directory, never one whole-box sweep: a whole-box find can be killed
    # partway and its partial output is indistinguishable from a clean zero.
    find_args=()
    for pat in "${CARRIER_PATTERNS[@]}"; do
        find_args+=( -o -name "$pat" )
    done
    unset 'find_args[0]'   # drop the leading -o

    while IFS= read -r -d '' f; do
        is_protected "$f" && continue
        sz=$(stat -c %s "$f" 2>/dev/null || echo 0)
        if [ "$DRY_RUN" = "1" ]; then
            echo "[$(ts)] DRY_RUN: would delete $f (${sz} bytes, $(( ( $(date +%s) - $(stat -c %Y "$f") ) / 86400 ))d old)"
        else
            rm -f -- "$f" && echo "[$(ts)] deleted $f (${sz} bytes)"
        fi
        total=$((total + 1))
        bytes=$((bytes + sz))
    done < <(find "$dir" -xdev -path "$protected_resolved" -prune -o \
                   -type f -mtime "+${RETENTION_DAYS}" \( "${find_args[@]}" \) -print0 2>/dev/null)

    echo "[$(ts)] SWEEP_COMPLETE ${dir}"
done

echo "[$(ts)] carrier purge finished: ${total} file(s), ${bytes} bytes (dry_run=${DRY_RUN})"
# Gate automation on this sentinel. A killed run otherwise reads as a clean zero.
echo "PURGE_COMPLETE"
