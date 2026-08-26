#!/bin/bash
# KTP retired-credential carrier purge (data server, root)
#
# Rotated secrets keep living in *.bak-* / *.cfg.bak* / archive copies long
# after the value itself is dead. Every value found so far was already rotated,
# so this is hygiene rather than exposure. The point is that dead values age out
# unattended instead of needing another census: that census was re-derived four
# times and produced a different number each time, which is the argument for a
# dated rule instead of a sweep.
#
# Matches on NAME and AGE only. It never greps for a secret, so no credential
# appears in this script, its arguments, or its log -- which is what makes it
# safe to keep in a public repository.
#
# ⚠️ NECESSARY, NOT SUFFICIENT -- measured on the data server 2026-08-25:
#   - Of the carriers that exist, roughly one in ten is NOT backup-shaped and
#     this script cannot see it by design: shell/SQL histories and a handful of
#     ordinary .log and .sql files. Those need a deliberate decision each.
#   - Roughly one in ten is NEWER than the horizon on any given day, including
#     the largest ones. A 90-day rule reaches them eventually, never promptly.
# Do not read a clean run as "no carriers remain".
#
# EXCLUSIONS. Every entry below was measured to contain live data, curated
# archives, or git-tracked CI fixtures that match the name patterns anyway.
# Removing an entry without re-measuring will delete production data.
#
# DRY_RUN defaults to 1. This script reports and does nothing until it is
# explicitly told otherwise, because the first real run deletes everything back
# to the retention horizon in one pass.
#
# Cron: /etc/cron.d/ktp-credential-carrier-purge (staged disabled on install).
# Canonical copy: KTPInfrastructure/scripts/.

set -euo pipefail

RETENTION_DAYS="${RETENTION_DAYS:-90}"
DRY_RUN="${DRY_RUN:-1}"
PROTECTED_DIR="${PROTECTED_DIR:-/opt/backups}"
SCAN_DIRS="${SCAN_DIRS:-/home /opt /root /etc /usr/local/bin /srv}"

# Backup-shaped suffixes only. Deliberately excludes *.tmp (FastDL serves live
# .ztmp assets) and bare *.gz / *.zip / *.tar.gz (those are overwhelmingly real
# data here -- demo uploads, evidence bundles, dpkg state -- and the two archives
# that ARE carriers already match via *.bak-* and *-backup-*).
CARRIER_PATTERNS=(
    '*.bak' '*.bak-*' '*.bak.*' '*.bak_*'
    '*.cfg.bak*' '*.conf.bak*'
    '*.orig' '*.old' '*.save'
    '*.pre-*' '*-backup-*' '*.backup'
)

# Measured 2026-08-25. Each is live data, a curated archive, or a CI fixture
# that matches the patterns above. Order does not matter; all are pruned.
EXCLUDE_PATHS=(
    "$PROTECTED_DIR"                                  # only DB copies that exist; own 28d prune
    /home/dod/distribute                              # LIVE deploy path; deletions sync fleet-wide in ~15s
    /home/hltvserver/hlds/dod/demos                   # demo archive; ktp-demo-retention.sh owns it
    /home/hltvserver/hlds/configs                     # the 24 live proxy configs
    /opt/ktp-ac-api/uploads                           # evidence bundles; retention deliberately HELD
    /opt/ktp-lan-archive                              # curated LAN event archive
    /opt/ktp-infra                                    # git-tracked; tier-2 CI fixtures live here
    /opt/ktp-tier2-runner/actions-runner/_work        # runner checkouts + Python toolcache
    /var/backups                                      # owned by dpkg-db-backup.timer
    /etc/console-setup                                # cached fonts/keymaps
)

ts() { date '+%Y-%m-%d %H:%M:%S'; }

echo "[$(ts)] carrier purge starting: retention=${RETENTION_DAYS}d dry_run=${DRY_RUN}"

# A missing protected dir means the assumption behind this script no longer
# holds. Refuse rather than run with one guard silently absent.
if [ ! -d "$PROTECTED_DIR" ]; then
    echo "[$(ts)] FATAL: protected dir $PROTECTED_DIR does not exist -- refusing to run"
    exit 1
fi

resolved_excludes=()
for p in "${EXCLUDE_PATHS[@]}"; do
    [ -e "$p" ] || continue
    resolved_excludes+=( "$(readlink -f "$p")" )
done

# Verify by RESOLVED path, not string prefix: /home/hltvserver/hlds/dod/demos is
# a symlink on this box, and a prefix test would sail straight past it.
is_protected() {
    local p; p=$(readlink -f "$1" 2>/dev/null) || return 0   # unresolvable -> treat as protected
    local e
    for e in "${resolved_excludes[@]}"; do
        case "$p" in "$e"|"$e"/*) return 0 ;; esac
    done
    case "$(basename "$p")" in
        .bash_history|.mysql_history|.psql_history|*fallback*) return 0 ;;
    esac
    return 1
}

total=0
bytes=0

for dir in $SCAN_DIRS; do
    [ -d "$dir" ] || { echo "[$(ts)] skip $dir (absent)"; continue; }

    find_args=()
    for pat in "${CARRIER_PATTERNS[@]}"; do
        find_args+=( -o -name "$pat" )
    done
    unset 'find_args[0]'   # drop the leading -o

    # Per-directory, never one whole-box sweep: a whole-box find can be killed
    # partway and its partial output is indistinguishable from a clean zero.
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
    done < <(find "$dir" -xdev -type f -mtime "+${RETENTION_DAYS}" \( "${find_args[@]}" \) -print0 2>/dev/null)

    echo "[$(ts)] SWEEP_COMPLETE ${dir}"
done

echo "[$(ts)] carrier purge finished: ${total} file(s), ${bytes} bytes (dry_run=${DRY_RUN})"
# Gate automation on this sentinel. A killed run otherwise reads as a clean zero.
echo "PURGE_COMPLETE"
