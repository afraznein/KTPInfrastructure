#!/bin/bash
# Restore the AC replay corpus from the encrypted offsite archive.
#
# RUNS WHERE THE KEY IS, WHICH IS NOT THE DATA SERVER. ktp-corpus-offsite.sh
# encrypts to a public recipient and holds no private key, so the box that makes
# the backup cannot read it. This script is the other half, and it belongs on
# whatever machine the operator keeps the identity file on -- deliberately not
# the data server, not the archive box, and not anything reachable from the web
# or FTP surfaces.
#
# IT WRITES PLAINTEXT PLAYER EVIDENCE. Whatever --dest points at ends up holding
# SteamIDs, machine names, IPs and screenshots in the clear. Point it at local
# disk on a machine you control; never at a docroot, an FTP root, or a synced
# folder. The script creates --dest at 0700 and refuses a destination that is
# not empty, because merging a restore into an existing tree makes "what came
# back" unanswerable at exactly the moment it matters.
#
# VERIFICATION IS THE POINT, NOT A POSTSCRIPT. Every object is checked against
# the manifest's md5 after decryption. A restore that decrypted cleanly and
# produced the wrong bytes is the failure this exists to catch, and age's own
# exit code does not catch it -- it authenticates the ciphertext it was given,
# not that the ciphertext was the right one.
#
# IT PRINTS NO BUNDLE FILENAMES. Same reason as the offsite leg: a path here is
# a player and their SteamID, and this output gets pasted into tickets.
#
#   --src   <rsync spec or local dir>  where the archive is. A remote spec needs --rsh
#   --rsh   <transport>                e.g. the ssh line the offsite conf already carries
#   --dest  <dir>                      empty or nonexistent; created 0700
#   --key   <identity file>            age private key. Required; no default
#   --day   <YYYY-MM-DD>               restore only this day; repeatable. Default: everything
#   --set   bundles|weapon-context     which population to restore (default bundles). The
#                                      weapon-context set restores the CURRENT version of
#                                      every sidecar, from <src>/weapon-context/
#
# No hostnames or credentials in this file. This repository is public.

set -uo pipefail
umask 077

SRC=""
RSH=""
DEST=""
KEY=""
DAYS=()
SET="bundles"

while [ $# -gt 0 ]; do
    case "$1" in
        --src)  SRC="${2:-}";  shift 2 ;;
        --rsh)  RSH="${2:-}";  shift 2 ;;
        --dest) DEST="${2:-}"; shift 2 ;;
        --key)  KEY="${2:-}";  shift 2 ;;
        --day)  DAYS+=( "${2:-}" ); shift 2 ;;
        --set)  SET="${2:-}";  shift 2 ;;
        *) echo "[corpus-restore] unknown argument: $1" >&2; exit 1 ;;
    esac
done

fail() { echo "[corpus-restore] FAILED: $*" >&2; exit 1; }

command -v age >/dev/null 2>&1 || fail "age is not installed."
[ -n "$SRC" ]  || fail "--src is required."
[ -n "$DEST" ] || fail "--dest is required."
[ -n "$KEY" ]  || fail "--key is required. Without the identity file the archive is ciphertext and stays that way."
[ -f "$KEY" ]  || fail "--key $KEY does not exist."
case "$SET" in
    bundles)
        MANIFEST_PATH="ktp-corpus-manifest.txt.age"
        OBJ_PREFIX="" ;;
    weapon-context)
        MANIFEST_PATH="weapon-context/ktp-weapon-context-manifest.txt.age"
        OBJ_PREFIX="weapon-context/objects/"
        [ "${#DAYS[@]}" -eq 0 ] || fail "--day selects bundle day-dirs; sidecars have none." ;;
    *) fail "--set takes bundles or weapon-context." ;;
esac
# A world-readable private key on the machine that decrypts the whole evidence
# corpus is worth one line to catch.
PERM=$(stat -c '%a' "$KEY" 2>/dev/null || echo "")
case "$PERM" in
    400|600|"") ;;
    *) echo "[corpus-restore] WARNING: identity file mode is $PERM; 600 is the expectation." >&2 ;;
esac

case "$SRC" in
    *:*) [ -n "$RSH" ] || fail "--src looks remote but --rsh is unset." ;;
esac

if [ -e "$DEST" ]; then
    [ -d "$DEST" ] || fail "--dest exists and is not a directory."
    [ -z "$(ls -A "$DEST" 2>/dev/null)" ] \
        || fail "--dest is not empty. Restore into a fresh directory so 'what came back' has one answer."
fi
mkdir -p "$DEST" && chmod 700 "$DEST" || fail "could not create $DEST"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

RSYNC_E=()
[ -n "$RSH" ] && RSYNC_E=( -e "$RSH" )

# --------------------------------------------------------------- manifest
MANIFEST_NAME="${MANIFEST_PATH##*/}"
rsync -a "${RSYNC_E[@]}" "$SRC/$MANIFEST_PATH" "$WORK/$MANIFEST_NAME" \
    || fail "could not fetch $MANIFEST_PATH from the archive. Without it the objects are unnamed hashes."
age -d -i "$KEY" -o "$WORK/manifest.txt" "$WORK/$MANIFEST_NAME" \
    || fail "could not decrypt the manifest. Wrong identity file, or the archive was encrypted to a key you do not hold."

grep -vE '^#' "$WORK/manifest.txt" | grep -E '^[0-9a-f]{32}  [0-9a-f]{64}  ' > "$WORK/rows.txt"
TOTAL=$(wc -l < "$WORK/rows.txt")
[ "$TOTAL" -gt 0 ] || fail "the manifest decrypted but parsed to no rows -- refusing to report an empty restore as a restore."

if [ "${#DAYS[@]}" -gt 0 ]; then
    : > "$WORK/filter.txt"
    for d in "${DAYS[@]}"; do printf '%s/\n' "$d" >> "$WORK/filter.txt"; done
    awk 'NR==FNR{want[$0];next}{ split($3,p,"/"); if ((p[1] "/") in want) print }' \
        "$WORK/filter.txt" "$WORK/rows.txt" > "$WORK/rows.sel"
    mv "$WORK/rows.sel" "$WORK/rows.txt"
    SEL=$(wc -l < "$WORK/rows.txt")
    [ "$SEL" -gt 0 ] || fail "--day matched no rows in the manifest."
else
    SEL="$TOTAL"
fi
echo "[corpus-restore] $SET manifest lists $TOTAL file(s); restoring $SEL"

# ----------------------------------------------------------------- fetch
# A bundle object sits in its day-dir; a sidecar object sits under its set's prefix.
objpath() {
    if [ -n "$OBJ_PREFIX" ]; then printf '%s%s.age\n' "$OBJ_PREFIX" "$2"
    else printf '%s/%s.age\n' "${1%%/*}" "$2"; fi
}
while IFS= read -r row; do
    rest="${row#*  }"
    objpath "${rest#*  }" "${rest%%  *}"
done < "$WORK/rows.txt" | sort -u > "$WORK/objects.txt"
rsync -a --checksum "${RSYNC_E[@]}" --files-from="$WORK/objects.txt" "$SRC/" "$WORK/enc/" \
    || fail "could not fetch the encrypted objects."
GOT=$(find "$WORK/enc" -type f -name '*.age' 2>/dev/null | wc -l)
WANT=$(wc -l < "$WORK/objects.txt")
[ "$GOT" -eq "$WANT" ] || fail "fetched $GOT object(s) but the manifest wanted $WANT."

# --------------------------------------------------------------- decrypt
DECFAIL=0
BADSUM=0
OK=0
while IFS= read -r row; do
    md5="${row%%  *}"
    rest="${row#*  }"
    sha="${rest%%  *}"
    rel="${rest#*  }"
    mkdir -p "$DEST/${rel%/*}" || { DECFAIL=$(( DECFAIL + 1 )); continue; }
    if ! age -d -i "$KEY" -o "$DEST/$rel" "$WORK/enc/$(objpath "$rel" "$sha")" 2>/dev/null; then
        rm -f "$DEST/$rel"
        DECFAIL=$(( DECFAIL + 1 ))
        continue
    fi
    # The manifest's md5 is the only independent statement of what this file was
    # supposed to be. age proves the ciphertext was not tampered with; it cannot
    # prove the right ciphertext was stored under that name in the first place.
    if [ "$(md5sum < "$DEST/$rel" | cut -d' ' -f1)" != "$md5" ]; then
        BADSUM=$(( BADSUM + 1 ))
        continue
    fi
    OK=$(( OK + 1 ))
done < "$WORK/rows.txt"

# Counted, never listed.
echo "[corpus-restore] decrypted and md5-verified: $OK of $SEL"
if [ "$DECFAIL" -ne 0 ] || [ "$BADSUM" -ne 0 ]; then
    echo "[corpus-restore] $DECFAIL failed to decrypt, $BADSUM decrypted to the wrong bytes" >&2
    fail "restore is incomplete. The tree in $DEST is partial -- do not treat it as the corpus."
fi
echo "[corpus-restore] OK: $OK file(s) of the $SET set restored to $DEST and verified against the manifest"
exit 0
