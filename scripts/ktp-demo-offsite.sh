#!/bin/bash
# Offsite copy of the demos worth keeping, to provider-diverse hosts.
#
# WHY A SUBSET. The archive is ~150 GB and grows ~47 GB/month; neither offsite
# host has room for it twice, and a full copy would fill the larger one within
# about a month. `docs/BACKUP_SCOPE.md` rules the retain/discard split by type:
# `ktp`/`ktpOT` and `draft` are RETAIN; `12man` and `scrim` are DISCARD
# (deliberately, and they are the fast-growing 121 GB of the ~150 GB archive).
# Everything recorded during a LAN is kept regardless of type -- that ruling
# is unchanged and is not what this revision touches.
#
# FIXED 2026-08-30, ruling-compliant only -- two things, not a widen to every
# type:
#   1. `draft_*.dem` was missing outright. It is RETAIN per BACKUP_SCOPE.md and
#      was excluded unless a LAN window happened to also cover it. Added.
#   2. `ktpOT_` (mixed case) never matched anything, live or in principle. The
#      renamer forces every match type to lowercase before it touches a
#      filename (hltv-demo-renamer.py, `window.match_type.lower()`) because the
#      organizer's own regex is `[a-z0-9]+` and rejects mixed case -- so an OT
#      demo is named `ktpot_...`, never `ktpOT_...`. Corrected the casing
#      rather than dropping the clause, since `ktp`/`ktpOT` is one RETAIN row
#      in the ruling -- but no OT demo has ever existed on this fleet to test
#      the corrected pattern against; it is unverified until one does.
# `12man`/`scrim` stay OUT of scope on purpose -- that is the discard half of
# an existing ruling, and reversing it is an operator decision, not this PR.
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
# Targets that speak rsync/SFTP but have NO shell (Hetzner Storage Box).
# Kept as a SEPARATE list, not folded into KTP_OFFSITE_HOSTS: the transport
# differs, and a shell-capable host silently taking the shell-less path would
# lose the md5 verification without anything saying so.
RSYNC_HOSTS="${KTP_OFFSITE_RSYNC_HOSTS:-}"
RSYNC_RSH="${KTP_OFFSITE_RSYNC_RSH:-}"
RSYNC_DEMO_DIR="${KTP_OFFSITE_RSYNC_DIR:-${KTP_OFFSITE_DIR:-}}"

DEST="${KTP_OFFSITE_DIR:-}"
DB="${KTP_DEMO_DB:-hlstatsx}"
# Selection is the risky half, not the copy. KTP_DEMO_DRYRUN=1 prints what WOULD go and
# touches nothing, so the file set can be reviewed before 34 GB moves.
DRYRUN="${KTP_DEMO_DRYRUN:-0}"

fail() { echo "[demo-offsite] FAILED: $*" >&2; exit 1; }

[ -n "$HOSTS" ] || fail "KTP_OFFSITE_HOSTS is unset. Refusing to guess a target."
[ -n "$DEST" ]  || fail "KTP_OFFSITE_DIR is unset. Refusing to guess a path."
if [ -n "$RSYNC_HOSTS" ]; then
    [ -n "$RSYNC_RSH" ] || fail "KTP_OFFSITE_RSYNC_HOSTS is set but KTP_OFFSITE_RSYNC_RSH is not."
    [ -n "$RSYNC_DEMO_DIR" ] || fail "KTP_OFFSITE_RSYNC_HOSTS is set but no destination dir is."
fi
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

# RETAIN types only, per docs/BACKUP_SCOPE.md -- always. Lowercase: the
# renamer forces every type to lowercase before naming a file (organizer regex
# is `[a-z0-9]+`), so a `ktpOT_` clause here never matches. `12man`/`scrim` are
# the ruled DISCARD types and are deliberately not selected by anything below.
find "$SRC" -type f \( -name 'ktp_*.dem' -o -name 'ktpot_*.dem' \
                        -o -name 'draft_*.dem' \) \
     -print > "$LIST"

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

# A manifest shipped BESIDE the demos, not just this run's stdout log. The LAN
# window that drove part of the selection lives only in the database -- if
# that table is ever lost or edited, this file is the only surviving record of
# what was supposed to be here, letting a restore audit by listing instead of
# trusting a long-gone exit code (docs/BACKUP_SCOPE.md's own principle).
MANIFEST_NAME="ktp-demo-manifest.txt"
{
    echo "# ktp-demo-offsite selection manifest -- $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "# $COUNT files, $(( KB / 1024 / 1024 )) GB / $(( KB / 1024 )) MB"
    echo "# types: ktp, ktpot, draft (RETAIN, per docs/BACKUP_SCOPE.md) -- plus anything recorded during a LAN window"
    cat "$WORK/rel.txt"
} > "$WORK/$MANIFEST_NAME"

if [ "$DRYRUN" = "1" ]; then
    echo "[demo-offsite] DRY RUN -- nothing will be copied"
    echo "[demo-offsite] by type:"
    sed -E 's|.*/||; s/_[0-9]+.*//' "$LIST" | sort | uniq -c | sed 's/^/    /'
    echo "[demo-offsite] first 5:"
    head -5 "$WORK/rel.txt" | sed 's/^/    /'
    echo "[demo-offsite] targets that WOULD be written: $HOSTS -> $DEST"
    [ -n "$RSYNC_HOSTS" ] && echo "[demo-offsite] rsync-only targets: $RSYNC_HOSTS -> ${RSYNC_DEMO_DIR}"
    [ -z "$RSYNC_HOSTS" ] && echo "[demo-offsite] rsync-only targets: (none configured)"
    echo "[demo-offsite] manifest that WOULD ship to each target: $MANIFEST_NAME"
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
        rsync -a "$WORK/$MANIFEST_NAME" "$H:$DEST/$MANIFEST_NAME" \
            || { echo "[demo-offsite] $H: manifest ship failed -- remote copy now has no durable record of what should be there" >&2; RC=1; }
    fi
done


# ---------------------------------------------------------------- shell-less
# Storage Box: rsync/SFTP, no shell, so the per-file `[ -f ]` loop above cannot
# run. The dry-run itemize is a STRONGER check than that loop anyway -- it
# compares size and mtime, where the loop only asks whether a name exists, so a
# truncated demo passes the shell check and fails this one.
for H in $RSYNC_HOSTS; do
    echo "[demo-offsite] --- $H (rsync-only target)"
    rsync -a --checksum --mkpath --partial --human-readable -e "$RSYNC_RSH"           --files-from="$WORK/rel.txt" "$SRC/" "$H:$RSYNC_DEMO_DIR/"         || { echo "[demo-offsite] $H: rsync reported failure" >&2; RC=1; continue; }

    # No --checksum here: the transfer above already checksummed every file, so
    # this pass is confirming arrival, not re-reading 33 GB on both sides.
    DIFFS=$(rsync -ani -e "$RSYNC_RSH"                   --files-from="$WORK/rel.txt" "$SRC/" "$H:$RSYNC_DEMO_DIR/" 2>/dev/null             | grep -E '^[<>ch.*][fL]' || true)
    if [ -z "$DIFFS" ]; then
        echo "[demo-offsite] $H: $COUNT/$COUNT verified by rsync itemize"
        rsync -a -e "$RSYNC_RSH" "$WORK/$MANIFEST_NAME" "$H:$RSYNC_DEMO_DIR/$MANIFEST_NAME" \
            || { echo "[demo-offsite] $H: manifest ship failed -- remote copy now has no durable record of what should be there" >&2; RC=1; }
    else
        echo "[demo-offsite] $H: $(printf '%s
' "$DIFFS" | grep -c .) of $COUNT file(s) missing or wrong size on arrival" >&2
        printf '%s
' "$DIFFS" | head -5 | sed 's/^/    /' >&2
        RC=1
    fi
done

if [ "$RC" -ne 0 ]; then
    echo "[demo-offsite] FAILED: at least one target is incomplete" >&2
    exit 1
fi
echo "[demo-offsite] OK: $COUNT files on every target"
exit 0
