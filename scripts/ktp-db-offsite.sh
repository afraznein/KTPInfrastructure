#!/bin/bash
# Offsite copy of the database dumps, to provider-diverse hosts.
#
# The dumps were being written to /opt/backups on the SAME FILESYSTEM as the
# data they protect. That survives a bad DROP; it does not survive the disk, the
# host, or the account.
#
# WHY THIS SHIPS EVERYTHING. The whole dump directory is ~480 MB -- small enough
# that selecting a subset would add a failure mode (picking the wrong "latest")
# to save nothing. It also means the offsite copy keeps a LONGER history than
# the source: /opt/ktp-backup.sh prunes at 28 days, and this never deletes, so
# a dump that ages out locally survives here.
#
# md5 IS CHECKED ON THE FAR SIDE, PER FILE. At this size that is affordable, and
# it is the difference between "rsync believed it finished" and "the bytes that
# arrived are the bytes we sent". The demo script cannot afford this and counts
# files instead; this one can, so it does.
#
# NO HOSTNAMES OR CREDENTIALS. This repository is public. Targets come from the
# environment; the script refuses rather than guessing.
#
#   KTP_BACKUP_DIR     source directory (default /opt/backups)
#   KTP_OFFSITE_HOSTS  space-separated user@host entries
#   KTP_OFFSITE_DB_DIR destination directory on each target

set -uo pipefail

SRC="${KTP_BACKUP_DIR:-/opt/backups}"
HOSTS="${KTP_OFFSITE_HOSTS:-}"
# Targets that speak rsync/SFTP but have NO shell (Hetzner Storage Box).
# Kept as a SEPARATE list, not folded into KTP_OFFSITE_HOSTS: the transport
# differs, and a shell-capable host silently taking the shell-less path would
# lose the md5 verification without anything saying so.
RSYNC_HOSTS="${KTP_OFFSITE_RSYNC_HOSTS:-}"
RSYNC_RSH="${KTP_OFFSITE_RSYNC_RSH:-}"
RSYNC_DB_DIR="${KTP_OFFSITE_RSYNC_DB_DIR:-${KTP_OFFSITE_DB_DIR:-}}"

DEST="${KTP_OFFSITE_DB_DIR:-}"
DRYRUN="${KTP_DB_DRYRUN:-0}"

fail() { echo "[db-offsite] FAILED: $*" >&2; exit 1; }

[ -n "$HOSTS" ] || fail "KTP_OFFSITE_HOSTS is unset. Refusing to guess a target."
[ -n "$DEST" ]  || fail "KTP_OFFSITE_DB_DIR is unset. Refusing to guess a path."
if [ -n "$RSYNC_HOSTS" ]; then
    [ -n "$RSYNC_RSH" ] || fail "KTP_OFFSITE_RSYNC_HOSTS is set but KTP_OFFSITE_RSYNC_RSH is not."
    [ -n "$RSYNC_DB_DIR" ] || fail "KTP_OFFSITE_RSYNC_HOSTS is set but no destination dir is."
fi
[ -d "$SRC" ]   || fail "source $SRC does not exist"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

find "$SRC" -maxdepth 1 -type f -name '*.gz' -printf '%f\n' | sort > "$WORK/files.txt"
COUNT=$(wc -l < "$WORK/files.txt")
# An empty backup directory is not a successful backup. It is the single most
# important thing this script must refuse to call OK.
[ "$COUNT" -gt 0 ] || fail "no dumps found in $SRC -- refusing to report success on an empty set"

# Freshness is worth SAYING, not just shipping. A three-week-old newest dump is
# a finding; copying it offsite unremarked would make the estate feel protected.
NEWEST=$(find "$SRC" -maxdepth 1 -type f -name '*.gz' -printf '%T@ %f\n' | sort -rn | head -1)
# find -printf %T@ yields a FLOAT (1787325912.0362576310). Bash arithmetic
# cannot take the fraction, so strip it -- second resolution is far more than
# an age-in-days check needs.
NEWEST_TS="${NEWEST%% *}"
NEWEST_AGE_D=$(( ( $(date +%s) - ${NEWEST_TS%%.*} ) / 86400 ))
echo "[db-offsite] $COUNT dump(s); newest is ${NEWEST#* } (${NEWEST_AGE_D}d old)"
[ "$NEWEST_AGE_D" -le 10 ] || echo "[db-offsite] WARNING: newest dump is ${NEWEST_AGE_D} days old" >&2

( cd "$SRC" && md5sum $(cat "$WORK/files.txt") ) > "$WORK/local.md5" 2>/dev/null \
    || fail "could not hash the local dumps"

if [ "$DRYRUN" = "1" ]; then
    echo "[db-offsite] DRY RUN -- nothing will be copied"
    sed 's/^/    /' "$WORK/files.txt"
    echo "[db-offsite] targets that WOULD be written: $HOSTS -> $DEST"
    exit 0
fi

RC=0
for H in $HOSTS; do
    echo "[db-offsite] --- $H"
    ssh -o BatchMode=yes -o ConnectTimeout=10 "$H" "mkdir -p '$DEST'" \
        || { echo "[db-offsite] $H: unreachable or cannot create $DEST" >&2; RC=1; continue; }

    # No --delete: a dump pruned locally at 28 days must survive here.
    rsync -a --partial --human-readable \
          --files-from="$WORK/files.txt" "$SRC/" "$H:$DEST/" \
        || { echo "[db-offsite] $H: rsync reported failure" >&2; RC=1; continue; }

    # Verify by CONTENT on the far side, not by rsync's exit code.
    ssh -o BatchMode=yes "$H" "cd '$DEST' && md5sum \$(cat) 2>/dev/null" \
        < "$WORK/files.txt" > "$WORK/remote.md5" 2>/dev/null

    if diff -q <(sort "$WORK/local.md5") <(sort "$WORK/remote.md5") >/dev/null 2>&1; then
        echo "[db-offsite] $H: $COUNT/$COUNT verified by md5"
    else
        MISSING=$(comm -23 <(sort "$WORK/local.md5") <(sort "$WORK/remote.md5") | wc -l)
        echo "[db-offsite] $H: $MISSING of $COUNT dump(s) missing or corrupt on arrival" >&2
        comm -23 <(sort "$WORK/local.md5") <(sort "$WORK/remote.md5") | head -5 | sed 's/^/    /' >&2
        RC=1
    fi
done


# ---------------------------------------------------------------- shell-less
# A Hetzner Storage Box speaks rsync and SFTP but offers NO general shell, so
# neither the mkdir nor the far-side md5sum above can run against it. rsync's
# own dry-run itemize compares both sides through its protocol instead, and
# with --checksum that is the same CONTENT claim the md5 pass makes -- it just
# needs rsync on the far end rather than a shell.
#
# --mkpath creates the destination directory (rsync >= 3.2.3), replacing the
# `ssh mkdir -p` that a Storage Box cannot serve.
for H in $RSYNC_HOSTS; do
    echo "[db-offsite] --- $H (rsync-only target)"
    rsync -a --mkpath --partial --human-readable -e "$RSYNC_RSH"           --files-from="$WORK/files.txt" "$SRC/" "$H:$RSYNC_DB_DIR/"         || { echo "[db-offsite] $H: rsync reported failure" >&2; RC=1; continue; }

    # Any itemized FILE line is a mismatch. Directory lines carry 'd' in the
    # second column and are not content, so they are not failures.
    DIFFS=$(rsync -ani --checksum -e "$RSYNC_RSH"                   --files-from="$WORK/files.txt" "$SRC/" "$H:$RSYNC_DB_DIR/" 2>/dev/null             | grep -E '^[<>ch.*][fL]' || true)
    if [ -z "$DIFFS" ]; then
        echo "[db-offsite] $H: $COUNT/$COUNT verified by rsync --checksum"
    else
        echo "[db-offsite] $H: $(printf '%s
' "$DIFFS" | grep -c .) of $COUNT dump(s) missing or corrupt on arrival" >&2
        printf '%s
' "$DIFFS" | head -5 | sed 's/^/    /' >&2
        RC=1
    fi
done

if [ "$RC" -ne 0 ]; then
    echo "[db-offsite] FAILED: at least one target is incomplete" >&2
    exit 1
fi
echo "[db-offsite] OK: $COUNT dump(s) verified on every target"
exit 0
