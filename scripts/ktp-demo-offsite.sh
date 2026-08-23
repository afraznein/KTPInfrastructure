#!/bin/bash
# Offsite copy of the demos worth keeping, to provider-diverse hosts.
#
# WHY A SUBSET. The archive is ~150 GB and grows ~47 GB/month; neither offsite
# host has room for it twice, and a full copy would fill the larger one within
# about a month. Operator ruling 2026-08-22: keep league matches (`ktp` /
# `ktpOT`) and everything recorded during a LAN, regardless of type. Measured at
# the time of that ruling that is 485 files / ~34.6 GB against 1,953 / ~149.8 GB
# total -- comfortable on both hosts, with years of headroom.
#
# WHY OFF-PROVIDER, NOT JUST OFF-HOST. Most of the estate -- including the data
# server the demos live on -- sits with a single provider whose terms state it
# keeps no backups and offers no compensation for lost data. A copy on another
# box at that provider protects against a disk, not against an account. Targets
# must therefore be at DIFFERENT providers; which hosts those are is deployment
# configuration, not something this public file should name.
#
# WHAT IT WILL NOT DO. It never deletes on the far side. A backup that mirrors
# deletions propagates the accident it exists to survive.
#
# NO HOSTNAMES OR CREDENTIALS IN THIS FILE. This repository is public. Targets
# come from the environment; the script refuses rather than guessing.
#
#   KTP_DEMO_SRC       source directory (default: the HLTV archive path below)
#   KTP_OFFSITE_HOSTS  space-separated user@host entries
#   KTP_OFFSITE_DIR    destination directory on each target
#
# Run on the data server, where the demos already are -- a workstation round
# trip would move 34 GB twice for no reason.

set -uo pipefail

SRC="${KTP_DEMO_SRC:-/home/hltvserver/hlds/dod/demos}"
HOSTS="${KTP_OFFSITE_HOSTS:-}"
DEST="${KTP_OFFSITE_DIR:-}"
DB="${KTP_DEMO_DB:-hlstatsx}"
# Selection is the risky half, not the copy. DRYRUN=1 prints what WOULD go and
# touches nothing, so the file set can be reviewed before 34 GB moves.
DRYRUN="${KTP_DEMO_DRYRUN:-0}"

fail() { echo "[demo-offsite] FAILED: $*" >&2; exit 1; }

[ -n "$HOSTS" ] || fail "KTP_OFFSITE_HOSTS is unset. Refusing to guess a target."
[ -n "$DEST" ]  || fail "KTP_OFFSITE_DIR is unset. Refusing to guess a path."
[ -d "$SRC" ]   || fail "source $SRC does not exist"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
LIST="$WORK/keep.txt"

# ---------------------------------------------------------------- selection
# LAN windows come from the DATABASE, not from a date pasted here. A hardcoded
# window silently stops covering the next LAN, and nothing would report it.
mysql -N -B "$DB" -e \
  "SELECT DATE_FORMAT(start_at,'%Y-%m-%d'), DATE_FORMAT(COALESCE(end_at,NOW()),'%Y-%m-%d') \
     FROM ktp_ac_lan_windows ORDER BY start_at" > "$WORK/windows.txt" 2>"$WORK/mysql.err"
if [ $? -ne 0 ]; then
    fail "could not read ktp_ac_lan_windows: $(head -1 "$WORK/mysql.err")"
fi
WINDOWS=$(wc -l < "$WORK/windows.txt")
# Zero windows is a legitimate state (no LAN yet) but it changes what this
# backs up, so say it rather than letting the count silently mean "type-only".
echo "[demo-offsite] LAN windows read from the database: $WINDOWS"

# League matches, always.
find "$SRC" -type f \( -name 'ktp_*.dem' -o -name 'ktpOT_*.dem' \) -print > "$LIST"

# Everything recorded during a LAN, whatever its type.
while read -r start end; do
    [ -n "$start" ] || continue
    find "$SRC" -type f -name '*.dem' \
         -newermt "$start" ! -newermt "$end +1 day" -print >> "$LIST"
done < "$WORK/windows.txt"

sort -u "$LIST" -o "$LIST"
COUNT=$(wc -l < "$LIST")
[ "$COUNT" -gt 0 ] || fail "selection matched no files -- refusing to 'succeed' with an empty set"
# du -c reports KILOBYTES. Dividing by 1024^2 therefore yields GIGABYTES -- an
# earlier version labelled that "MB", which read 1000x small and looked exactly
# like a selection that had gone wrong.
KB=$(tr '\n' '\0' < "$LIST" | du -c --files0-from=- 2>/dev/null | tail -1 | cut -f1)
echo "[demo-offsite] selected $COUNT files ($(( KB / 1024 / 1024 )) GB / $(( KB / 1024 )) MB)"

# rsync wants paths relative to the source root.
sed "s|^$SRC/||" "$LIST" > "$WORK/rel.txt"

if [ "$DRYRUN" = "1" ]; then
    echo "[demo-offsite] DRY RUN -- nothing will be copied"
    echo "[demo-offsite] by type:"
    sed -E 's|.*/||; s/_[0-9]+.*//' "$LIST" | sort | uniq -c | sed 's/^/    /'
    echo "[demo-offsite] first 5:"
    head -5 "$WORK/rel.txt" | sed 's/^/    /'
    echo "[demo-offsite] targets that WOULD be written: $HOSTS -> $DEST"
    exit 0
fi

# ---------------------------------------------------------------- transfer
RC=0
for H in $HOSTS; do
    echo "[demo-offsite] --- $H"
    ssh -o BatchMode=yes -o ConnectTimeout=10 "$H" "mkdir -p '$DEST'" \
        || { echo "[demo-offsite] $H: unreachable or cannot create $DEST" >&2; RC=1; continue; }

    # --checksum, not size+mtime: a demo truncated mid-copy on a previous run
    # has a plausible size and a fresh mtime, and would be skipped forever.
    # No --delete, deliberately.
    rsync -a --checksum --partial --human-readable \
          --files-from="$WORK/rel.txt" "$SRC/" "$H:$DEST/" \
        || { echo "[demo-offsite] $H: rsync reported failure" >&2; RC=1; continue; }

    # Verify from the FAR SIDE. rsync exiting 0 says it thinks it finished;
    # counting the files that actually landed is a different claim.
    REMOTE_COUNT=$(ssh -o BatchMode=yes "$H" "cat > /tmp/.ktp_demo_rel.\$\$; \
        n=0; while IFS= read -r f; do [ -f '$DEST'/\"\$f\" ] && n=\$((n+1)); done < /tmp/.ktp_demo_rel.\$\$; \
        rm -f /tmp/.ktp_demo_rel.\$\$; echo \$n" < "$WORK/rel.txt")

    if [ "$REMOTE_COUNT" != "$COUNT" ]; then
        echo "[demo-offsite] $H: only $REMOTE_COUNT of $COUNT present after transfer" >&2
        RC=1
    else
        echo "[demo-offsite] $H: $REMOTE_COUNT/$COUNT present"
    fi
done

if [ "$RC" -ne 0 ]; then
    echo "[demo-offsite] FAILED: at least one target is incomplete" >&2
    exit 1
fi
echo "[demo-offsite] OK: $COUNT files on every target"
exit 0
