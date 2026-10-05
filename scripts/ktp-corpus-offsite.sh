#!/bin/bash
# Offsite copy of the AC replay corpus, to the shell-less archive target.
#
# WHY A THIRD DESTINATION. The corpus already goes to two provider-diverse
# hosts (ktp-corpus-push.service / ktp-corpus-push-denver.service, 04:15 and
# 04:45 daily, md5-verified per upload and never deleting). That is not a
# broken setup -- it is two copies on PRODUCTION GAME SERVERS, which are
# rebuilt, reconfigured and occasionally deleted as ordinary ops. The corpus
# is evidence that cannot be regenerated and it gates every detection change
# through corpus-replay, so it needs a copy somewhere the game fleet's
# lifecycle cannot reach. The archive box already holds the demo archive and
# the DB dumps and is the only destination outside the infrastructure we
# routinely modify.
#
# FAR-SIDE RETENTION: UNBOUNDED, ON PURPOSE. This script never deletes, the
# archive box prunes nothing, and neither does the source -- the upload sweep
# in ktp-ac-retention.sh has been held since 2026-08-16 (operator: retain all
# evidence bundles), so a bundle that lands here is kept until someone removes
# it by hand. That is the same accumulate-forever contract the demo and DB legs
# carry, stated rather than left to be inferred: the copy will grow without
# limit and nobody is watching a quota. Whether the box's own automatic
# snapshots are on is a SEPARATE question (docs/BACKUP_SCOPE.md section 2) --
# unbounded retention of the current bytes is not the same as keeping an older
# generation of a bundle something overwrote, and this script does not provide
# the second one.
#
# SHELL-LESS TARGET ONLY. The archive box speaks rsync and SFTP and offers no
# general shell; worse, it accepts a compound command, runs the first token,
# discards the rest and exits 0 (docs/BACKUP_SCOPE.md section 2). Every check
# here therefore goes through the rsync protocol. There is deliberately NO
# shell-capable host list in this script: the two shell-capable destinations
# already have a writer that verifies each upload by md5, and a second writer
# into the same directory would be a duplicate rather than a third copy. If a
# shell-capable target is ever added here it gets its OWN list and its own
# md5 path -- folding it onto this one would silently downgrade it to whatever
# the shell-less path can prove, with nothing saying so.
#
# VERIFICATION IS A CONTENT CLAIM, NOT AN EXIT CODE. The transfer runs with
# --checksum so a bundle truncated mid-copy on an earlier run is re-sent rather
# than skipped forever on a plausible size and a fresh mtime, and a second
# `rsync -ani --checksum` pass then itemises anything whose bytes still differ.
# Both passes read every byte on both sides. The demo leg cannot afford that at
# 33 GB and verifies by size+mtime instead; at corpus scale it is cheap, so
# this script does what ktp-db-offsite.sh does and makes the stronger claim.
#
# IT PRINTS NO BUNDLE FILENAMES. A bundle is named
# KTP_AC_<player>_STEAM_<id>_<timestamp>.zip, so a file list is a list of
# players and their SteamIDs. This output goes to a log and gets pasted into
# tickets and PRs; the ruling that publishing SteamIDs is fine bounds the HUD
# feed and does NOT reach AC evidence. Everything here is summarised by
# day-dir. The per-file manifest, which does carry the names, ships BESIDE the
# data on the archive box, which is where it belongs.
#
# ENCRYPTED BEFORE IT LEAVES, TO A KEY THIS HOST DOES NOT HAVE. Every other
# offsite leg ships plaintext, which is right for demos and DB dumps and wrong
# here: a bundle is player evidence -- SteamIDs, machine names, IPs, screenshots,
# process and peripheral inventories -- and the archive box is a third party's
# disk. Each bundle is encrypted with `age` to one or more PUBLIC recipient keys.
# The private key is never on this host, never in the conf, and never on the
# archive box, so losing either one yields ciphertext and nothing else.
#
# THE COST OF THAT PROPERTY, STATED PLAINLY: this host cannot verify that what it
# wrote can be decrypted. It can prove the bytes arrived intact -- that is what
# the checksum passes do -- and it cannot prove they are recoverable, because it
# holds no key. Only the key holder can close that loop, and only by restoring.
# `ktp-corpus-drill.sh` is that proof and it runs on synthetic data; a schedule
# for this script without a schedule for the drill is a backup nobody has read.
#
# REMOTE NAMES ARE CONTENT HASHES, NOT FILENAMES. A bundle is named for the
# player and their SteamID, so a directory listing on the archive box would be a
# roster. Each object lands as <YYYY-MM-DD>/<sha256-of-plaintext>.age. The day
# is kept because it is what a restore selects on and it identifies nobody; the
# name is not. Content addressing also makes the local ciphertext cache
# self-describing: the name IS the hash of what it encrypts, so a re-run knows
# what it already has without decrypting anything.
#
#   What that does not hide: someone who already holds a bundle can confirm it is
#   in the archive by hashing it. That is the whole of the leak and it is accepted
#   -- the alternative is a keyed name, which puts a secret on this host.
#
# TWO RECIPIENTS, NOT ONE. A single key is a single point of permanent loss: no
# key, no restore, and the corpus cannot be regenerated. The script warns at one.
#
# NO HOSTNAMES OR CREDENTIALS IN THIS FILE. This repository is public. Targets
# come from the environment; the script refuses rather than guessing. The
# recipient keys are PUBLIC keys -- they are safe in the conf and safe in a log.
#
#   KTP_CORPUS_SRC                 source directory (default below)
#   KTP_OFFSITE_RSYNC_HOSTS        shell-less target(s), user@host
#   KTP_OFFSITE_RSYNC_RSH          transport for those, e.g. ssh with port/key
#   KTP_OFFSITE_RSYNC_CORPUS_DIR   destination directory -- its OWN key, not
#                                  the demo or DB one; sharing a directory
#                                  mixes two archives whose retention and
#                                  restore audiences are different
#   KTP_CORPUS_AGE_RECIPIENTS      one or more age1... PUBLIC keys, whitespace
#                                  separated. Required; no default, because a
#                                  default recipient is a key somebody else holds
#   KTP_CORPUS_ENC_CACHE           local ciphertext cache (default below). Holds
#                                  one .age per bundle; sized like the corpus
#   KTP_WEAPON_CONTEXT_SRC         the AC weapon-context store (default below)
#
# THE SECOND SOURCE: WEAPON-CONTEXT SIDECARS. The AC API keeps each session's
# weapon timeline as <shard>/<session>.weapons.json, and once the nightly sweep
# deletes the database rows behind it the sidecar is the ONLY copy. The files
# carry victim SteamIDs, so they get exactly the bundles' treatment: same
# recipients, encrypted manifest, counts in the log and never a name. They land
# under their own far-side prefix, <dest>/weapon-context/, so a bundle restore and
# a sidecar restore never read each other's objects:
#
#   <dest>/weapon-context/objects/<sha256-of-plaintext>.age
#   <dest>/weapon-context/ktp-weapon-context-manifest.txt.age        (current)
#   <dest>/weapon-context/manifests/ktp-weapon-context-manifest-<UTC>.txt.age
#
# Unlike a bundle, a sidecar is REWRITTEN IN PLACE when a later hydrate is more
# complete. A rewrite has a new hash and therefore a new object, and the old one
# stays: the far side is append-only like everything else here. What says which
# object is the current version of a file is the stable manifest, which is
# rewritten every run from what this run read; the dated manifests are the only
# map to the older versions. The sidecars are copied into the work dir before
# they are hashed, because the writer replaces a file by rename at any moment
# and a hash taken from one version must not name the ciphertext of the next.
#
# Run on the data server, where the corpus already is. Dry run is the default;
# it takes --commit to move anything, matching push-corpus.py and
# feed-staging.py, the two tools that already handle this corpus.

set -uo pipefail
# The work dir holds the PLAINTEXT manifest, which is a list of players.
umask 077

SRC="${KTP_CORPUS_SRC:-/opt/ktp-ac-api/uploads}"
RSYNC_HOSTS="${KTP_OFFSITE_RSYNC_HOSTS:-}"
RSYNC_RSH="${KTP_OFFSITE_RSYNC_RSH:-}"
DEST="${KTP_OFFSITE_RSYNC_CORPUS_DIR:-}"
CACHE="${KTP_CORPUS_ENC_CACHE:-/var/lib/ktp-corpus-offsite/enc}"
RECIPIENTS="${KTP_CORPUS_AGE_RECIPIENTS:-}"
WC_SRC="${KTP_WEAPON_CONTEXT_SRC:-/opt/ktp-ac-api/weapon-context}"
WC_PREFIX="weapon-context"
WC_MANIFEST_NAME="ktp-weapon-context-manifest.txt.age"

COMMIT=0
for arg in "$@"; do
    [ "$arg" = "--commit" ] && COMMIT=1
done

fail() { echo "[corpus-offsite] FAILED: $*" >&2; exit 1; }

[ -n "$RSYNC_HOSTS" ] || fail "KTP_OFFSITE_RSYNC_HOSTS is unset. Refusing to guess a target."
[ -n "$RSYNC_RSH" ]   || fail "KTP_OFFSITE_RSYNC_HOSTS is set but KTP_OFFSITE_RSYNC_RSH is not."
[ -n "$DEST" ]        || fail "KTP_OFFSITE_RSYNC_CORPUS_DIR is unset. Refusing to guess a path."
# A conf line added by copying the demo one is the likeliest way this lands in
# the wrong directory, and the symptom would be two archives interleaved in one
# place with no error anywhere.
[ "$DEST" != "${KTP_OFFSITE_RSYNC_DIR:-}" ] \
    || fail "KTP_OFFSITE_RSYNC_CORPUS_DIR is the same path as the demo archive (KTP_OFFSITE_RSYNC_DIR)."
[ "$DEST" != "${KTP_OFFSITE_RSYNC_DB_DIR:-}" ] \
    || fail "KTP_OFFSITE_RSYNC_CORPUS_DIR is the same path as the DB dumps (KTP_OFFSITE_RSYNC_DB_DIR)."
[ -d "$SRC" ] || fail "source $SRC does not exist"
[ -d "$WC_SRC" ] || fail "weapon-context store $WC_SRC does not exist -- its sidecars are the only copy once the DB rows are swept"

command -v age >/dev/null 2>&1     || fail "age is not installed. This leg does not ship plaintext evidence; install age rather than removing the encryption."
[ -n "$RECIPIENTS" ] || fail "KTP_CORPUS_AGE_RECIPIENTS is unset. Refusing to write player evidence to a third party in the clear."

# A private key pasted where a public one belongs would encrypt to nothing
# useful and would also put the key on this host, which is the one thing this
# design exists to avoid. Check the shape rather than trusting the variable name.
RECIP=()
N_RECIP=0
for r in $RECIPIENTS; do
    case "$r" in
        age1*) RECIP+=( -r "$r" ); N_RECIP=$(( N_RECIP + 1 )) ;;
        AGE-SECRET-KEY-*) fail "KTP_CORPUS_AGE_RECIPIENTS contains a PRIVATE key. It takes public age1... recipients, and the private half must never be on this host." ;;
        *) fail "KTP_CORPUS_AGE_RECIPIENTS contains an entry that is not an age1... public key." ;;
    esac
done
[ "$N_RECIP" -gt 0 ] || fail "KTP_CORPUS_AGE_RECIPIENTS parsed to no recipients."
if [ "$N_RECIP" -eq 1 ]; then
    echo "[corpus-offsite] WARNING: one recipient key. Losing it loses the archive -- the corpus cannot be regenerated. Add a second." >&2
fi

# The cache under the source would be swept into the next selection and
# re-encrypted forever, each generation naming the last one's ciphertext.
case "$CACHE/" in
    "$SRC"/*) fail "KTP_CORPUS_ENC_CACHE is inside the source directory." ;;
    "$WC_SRC"/*) fail "KTP_CORPUS_ENC_CACHE is inside the weapon-context store." ;;
esac

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
LIST="$WORK/rel.txt"
ENCLIST="$WORK/enc.txt"

# ---------------------------------------------------------------- selection
# The AC API writes <guid>_<name>.zip straight into a YYYY-MM-DD day-dir, flat,
# one level deep. Asserting that shape rather than sweeping *.zip recursively
# means a bundle that turns up somewhere else is REPORTED instead of quietly
# widening what this copies.
find "$SRC" -mindepth 2 -maxdepth 2 -type f -name '*.zip' ! -name '.*' -printf '%P\n' \
    | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}/' \
    | sort > "$LIST"
COUNT=$(wc -l < "$LIST")
[ "$COUNT" -gt 0 ] || fail "selection matched no bundles -- refusing to 'succeed' with an empty set"

# Anything under the source the selection did NOT pick up. A bundle in the
# wrong shape is one that never leaves this host, and the only sign of it would
# be a count nobody was comparing against anything.
TOTAL_FILES=$(find "$SRC" -type f ! -name '.*' | wc -l)
UNSELECTED=$(( TOTAL_FILES - COUNT ))
if [ "$UNSELECTED" -ne 0 ]; then
    echo "[corpus-offsite] WARNING: $UNSELECTED file(s) under $SRC are not YYYY-MM-DD/*.zip and are NOT being copied" >&2
fi

# du -c reports KILOBYTES. The demo script once labelled this same figure "MB"
# when it was GB; keep both units so a wrong one is visible rather than plausible.
KB=$( cd "$SRC" && tr '\n' '\0' < "$LIST" | du -c --files0-from=- 2>/dev/null | tail -1 | cut -f1 )
# An unset or empty KB becomes 0 in bash arithmetic, and "0 MB" alongside a
# healthy file count reads as a small corpus rather than as a sizing step that
# did not run.
[ "${KB:-0}" -gt 0 ] 2>/dev/null \
    || fail "$COUNT bundle(s) matched but du sized them at nothing -- refusing to report a size that was never measured"
DAYS=$(cut -d/ -f1 "$LIST" | sort -u)
DAY_COUNT=$(printf '%s\n' "$DAYS" | wc -l)
echo "[corpus-offsite] selected $COUNT bundle(s) ($(( KB / 1024 )) MB / $(( KB / 1024 / 1024 )) GB)"
echo "[corpus-offsite] $DAY_COUNT day-dir(s), $(printf '%s\n' "$DAYS" | head -1) .. $(printf '%s\n' "$DAYS" | tail -1)"

# The manifest is the map from an opaque remote object back to the bundle it
# holds, and it is the only record of what was supposed to be there if this host
# and its database are both gone. It therefore carries the filenames, which makes
# it the most identifying single file in the archive -- so it ships ENCRYPTED,
# to the same recipients as the bundles.
MANIFEST_NAME="ktp-corpus-manifest.txt.age"

# ------------------------------------------------------- content addressing
# sha256 names the remote object; md5 stays in the manifest because `md5sum -c`
# is the idiom the sibling legs and the restore script already use. sha256 does
# the naming because an md5 collision between two bundles would land them on one
# remote name and silently keep whichever arrived last -- a constructible
# collision is a cheap way to make one piece of evidence overwrite another.
( cd "$SRC" && xargs -a "$LIST" -d '\n' md5sum )    > "$WORK/md5.txt"    || fail "could not md5 the local bundles"
( cd "$SRC" && xargs -a "$LIST" -d '\n' sha256sum ) > "$WORK/sha256.txt" || fail "could not sha256 the local bundles"
[ "$(wc -l < "$WORK/md5.txt")"    -eq "$COUNT" ] || fail "md5 pass covered fewer bundles than the selection"
[ "$(wc -l < "$WORK/sha256.txt")" -eq "$COUNT" ] || fail "sha256 pass covered fewer bundles than the selection"

declare -A MD5
while IFS= read -r line; do
    h="${line%% *}"; rel="${line#* }"; rel="${rel# }"
    MD5["$rel"]="$h"
done < "$WORK/md5.txt"

# Plan the encrypted set without encrypting anything, so a dry run stays a read.
: > "$ENCLIST"
: > "$WORK/manifest.body"
TO_ENCRYPT=0
CACHED=0
while IFS= read -r line; do
    sha="${line%% *}"; rel="${line#* }"; rel="${rel# }"
    printf '%s/%s.age\n' "${rel%%/*}" "$sha" >> "$ENCLIST"
    printf '%s  %s  %s\n' "${MD5[$rel]}" "$sha" "$rel" >> "$WORK/manifest.body"
    if [ -s "$CACHE/${rel%%/*}/$sha.age" ]; then
        CACHED=$(( CACHED + 1 ))
    else
        TO_ENCRYPT=$(( TO_ENCRYPT + 1 ))
    fi
done < "$WORK/sha256.txt"
[ "$(wc -l < "$ENCLIST")" -eq "$COUNT" ] || fail "encrypted set is not the same size as the selection"

echo "[corpus-offsite] $N_RECIP recipient key(s); $CACHED bundle(s) already encrypted in the cache, $TO_ENCRYPT to encrypt"

# ------------------------------------------------- weapon-context selection
# The store writes <shard>/<session>.weapons.json and stages each write in tmp/,
# so the shape is asserted the same way as the bundles' and an in-flight temp
# file is never mistaken for a sidecar.
WC_LIST="$WORK/wc-rel.txt"
WC_SNAP="$WORK/wc-snap"
WC_ENCLIST="$WORK/wc-enc.txt"
find "$WC_SRC" -mindepth 2 -maxdepth 2 -type f -name '*.weapons.json' ! -name '.*' -printf '%P\n' \
    | grep -E '^[0-9]+/[0-9]+\.weapons\.json$' \
    | sort > "$WC_LIST"
WC_COUNT=$(wc -l < "$WC_LIST")
[ "$WC_COUNT" -gt 0 ] || fail "weapon-context selection matched no sidecars -- refusing to 'succeed' with an empty set"

WC_TOTAL=$(find "$WC_SRC" -path "$WC_SRC/tmp" -prune -o -type f ! -name '.*' -print | wc -l)
if [ "$(( WC_TOTAL - WC_COUNT ))" -ne 0 ]; then
    echo "[corpus-offsite] WARNING: $(( WC_TOTAL - WC_COUNT )) file(s) under $WC_SRC are not <shard>/<session>.weapons.json and are NOT being copied" >&2
fi

mkdir -p "$WC_SNAP" || fail "could not create the weapon-context snapshot"
( cd "$WC_SRC" && xargs -a "$WC_LIST" -d '\n' cp --parents -p -t "$WC_SNAP" ) \
    || fail "could not snapshot the weapon-context sidecars"
[ "$(find "$WC_SNAP" -type f | wc -l)" -eq "$WC_COUNT" ] \
    || fail "weapon-context snapshot holds fewer files than the selection"
WC_KB=$( cd "$WC_SNAP" && tr '\n' '\0' < "$WC_LIST" | du -c --files0-from=- 2>/dev/null | tail -1 | cut -f1 )
[ "${WC_KB:-0}" -gt 0 ] 2>/dev/null \
    || fail "$WC_COUNT sidecar(s) matched but du sized them at nothing -- refusing to report a size that was never measured"

( cd "$WC_SNAP" && xargs -a "$WC_LIST" -d '\n' md5sum )    > "$WORK/wc-md5.txt"    || fail "could not md5 the weapon-context sidecars"
( cd "$WC_SNAP" && xargs -a "$WC_LIST" -d '\n' sha256sum ) > "$WORK/wc-sha256.txt" || fail "could not sha256 the weapon-context sidecars"
[ "$(wc -l < "$WORK/wc-md5.txt")"    -eq "$WC_COUNT" ] || fail "md5 pass covered fewer sidecars than the selection"
[ "$(wc -l < "$WORK/wc-sha256.txt")" -eq "$WC_COUNT" ] || fail "sha256 pass covered fewer sidecars than the selection"

declare -A WC_MD5
while IFS= read -r line; do
    h="${line%% *}"; rel="${line#* }"; rel="${rel# }"
    WC_MD5["$rel"]="$h"
done < "$WORK/wc-md5.txt"

: > "$WORK/wc-manifest.body"
while IFS= read -r line; do
    sha="${line%% *}"; rel="${line#* }"; rel="${rel# }"
    printf '%s  %s  %s\n' "${WC_MD5[$rel]}" "$sha" "$rel" >> "$WORK/wc-manifest.body"
done < "$WORK/wc-sha256.txt"
# Byte-identical sidecars share one object, so the object set can be smaller
# than the file count and both numbers are right.
cut -d' ' -f1 "$WORK/wc-sha256.txt" | sort -u | sed "s|^|$WC_PREFIX/objects/|; s|\$|.age|" > "$WC_ENCLIST"
WC_OBJECTS=$(wc -l < "$WC_ENCLIST")
WC_CACHED=0
while IFS= read -r obj; do
    [ -s "$CACHE/$obj" ] && WC_CACHED=$(( WC_CACHED + 1 ))
done < "$WC_ENCLIST"
WC_SHARDS=$(cut -d/ -f1 "$WC_LIST" | sort -u | wc -l)
echo "[corpus-offsite] weapon-context: selected $WC_COUNT sidecar(s) in $WC_SHARDS shard(s) ($WC_KB KB), $WC_OBJECTS distinct object(s); $WC_CACHED already encrypted, $(( WC_OBJECTS - WC_CACHED )) to encrypt"

if [ "$COMMIT" != "1" ]; then
    echo "[corpus-offsite] DRY RUN -- no --commit, nothing will be encrypted or copied"
    echo "[corpus-offsite] bundles per day-dir (10 most recent):"
    cut -d/ -f1 "$LIST" | uniq -c | tail -10 | sed 's/^/    /'
    echo "[corpus-offsite] target that WOULD be written: $RSYNC_HOSTS -> $DEST"
    echo "[corpus-offsite] objects that WOULD ship: <YYYY-MM-DD>/<sha256>.age, plus $MANIFEST_NAME"
    echo "[corpus-offsite] and $WC_PREFIX/objects/<sha256>.age, plus $WC_PREFIX/$WC_MANIFEST_NAME"
    echo "[corpus-offsite] (filenames are withheld on purpose -- they carry player names and SteamIDs)"
    exit 0
fi

# ------------------------------------------------------------- encryption
# Written to a temp name and moved into place. The cache is keyed on the hash of
# the PLAINTEXT, so a ciphertext truncated by an interrupted run would sit there
# under a name that says it is complete and be skipped forever -- the same
# failure --checksum exists to stop on the wire, reintroduced on disk.
install -d -m 700 "$CACHE" || fail "could not create the ciphertext cache at $CACHE"
ENCFAIL=0
NEW=0
while IFS= read -r line; do
    sha="${line%% *}"; rel="${line#* }"; rel="${rel# }"
    day="${rel%%/*}"
    [ -s "$CACHE/$day/$sha.age" ] && continue
    install -d -m 700 "$CACHE/$day" || { ENCFAIL=$(( ENCFAIL + 1 )); continue; }
    tmp="$CACHE/$day/.$sha.age.$$"
    if age "${RECIP[@]}" -o "$tmp" "$SRC/$rel" 2>/dev/null && [ -s "$tmp" ] \
       && mv -f "$tmp" "$CACHE/$day/$sha.age"; then
        NEW=$(( NEW + 1 ))
    else
        rm -f "$tmp"
        ENCFAIL=$(( ENCFAIL + 1 ))
    fi
done < "$WORK/sha256.txt"

WC_NEW=0
while IFS= read -r line; do
    sha="${line%% *}"; rel="${line#* }"; rel="${rel# }"
    obj="$CACHE/$WC_PREFIX/objects/$sha.age"
    [ -s "$obj" ] && continue
    install -d -m 700 "$CACHE/$WC_PREFIX" "$CACHE/$WC_PREFIX/objects" || { ENCFAIL=$(( ENCFAIL + 1 )); continue; }
    tmp="$CACHE/$WC_PREFIX/objects/.$sha.age.$$"
    if age "${RECIP[@]}" -o "$tmp" "$WC_SNAP/$rel" 2>/dev/null && [ -s "$tmp" ] \
       && mv -f "$tmp" "$obj"; then
        WC_NEW=$(( WC_NEW + 1 ))
    else
        rm -f "$tmp"
        ENCFAIL=$(( ENCFAIL + 1 ))
    fi
done < "$WORK/wc-sha256.txt"

# Counted, never listed: a path here is a player.
[ "$ENCFAIL" -eq 0 ] \
    || fail "$ENCFAIL of $(( COUNT + WC_COUNT )) file(s) failed to encrypt -- refusing to ship a partial corpus over a complete-looking one"
BUNDLE_OBJECTS=$(sort -u "$ENCLIST" | wc -l)
echo "[corpus-offsite] encrypted $NEW new bundle(s); cache holds $BUNDLE_OBJECTS object(s) for $COUNT bundle(s) in this selection"
echo "[corpus-offsite] encrypted $WC_NEW new weapon-context object(s); cache holds $WC_OBJECTS object(s) for $WC_COUNT sidecar(s)"

STAMP="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
FSTAMP="$(date -u -d "$STAMP" '+%Y%m%dT%H%M%SZ')"
{
    echo "# ktp-corpus-offsite manifest -- $STAMP"
    echo "# $COUNT bundles, $(( KB / 1024 )) MB, $DAY_COUNT day-dirs, $(printf '%s\n' "$DAYS" | head -1) .. $(printf '%s\n' "$DAYS" | tail -1)"
    echo "# columns: md5  sha256  YYYY-MM-DD/original-name"
    echo "# the remote object for each row is <YYYY-MM-DD>/<sha256>.age"
    echo "# restore and verify with ktp-corpus-restore.sh, which rebuilds md5sum -c input from columns 1 and 3"
    cat "$WORK/manifest.body"
} > "$WORK/manifest.txt" || fail "could not write the manifest"
age "${RECIP[@]}" -o "$WORK/$MANIFEST_NAME" "$WORK/manifest.txt" \
    || fail "could not encrypt the manifest"

{
    echo "# ktp-weapon-context offsite manifest -- $STAMP"
    echo "# $WC_COUNT sidecars, $WC_OBJECTS distinct objects, $WC_KB KB, $WC_SHARDS shards"
    echo "# columns: md5  sha256  <shard>/<session>.weapons.json"
    echo "# CURRENT VERSIONS: each row is the version of that file this run read. Sidecars are rewritten"
    echo "# in place and the far side keeps every version, so objects/ also holds older ones; only the"
    echo "# dated copies under manifests/ name those."
    echo "# the remote object for each row is $WC_PREFIX/objects/<sha256>.age"
    echo "# restore and verify with ktp-corpus-restore.sh --set weapon-context"
    cat "$WORK/wc-manifest.body"
} > "$WORK/wc-manifest.txt" || fail "could not write the weapon-context manifest"
age "${RECIP[@]}" -o "$WORK/$WC_MANIFEST_NAME" "$WORK/wc-manifest.txt" \
    || fail "could not encrypt the weapon-context manifest"

# One transfer and one far-side verify for both populations; the prefixes keep
# them apart on the far side, not separate passes.
ALL_ENC="$WORK/all-enc.txt"
sort -u "$ENCLIST" "$WC_ENCLIST" > "$ALL_ENC"
N_OBJ=$(wc -l < "$ALL_ENC")

# ---------------------------------------------------------------- transfer
RC=0
for H in $RSYNC_HOSTS; do
    echo "[corpus-offsite] --- $H (rsync-only target)"

    # --checksum: a bundle truncated mid-copy on an earlier run has a plausible
    # size and a fresh mtime and would otherwise be skipped forever.
    # --mkpath creates the destination, replacing the `ssh mkdir -p` this box
    # cannot serve. No --delete, deliberately: a backup that mirrors deletions
    # propagates the accident it exists to survive.
    rsync -a --checksum --mkpath --partial --human-readable -e "$RSYNC_RSH" \
          --files-from="$ALL_ENC" "$CACHE/" "$H:$DEST/" \
        || { echo "[corpus-offsite] $H: rsync reported failure" >&2; RC=1; continue; }

    # Verify from the FAR SIDE by content. Any itemized FILE line is a
    # mismatch; directory lines carry 'd' in the second column and are not
    # content, so they are not failures.
    DIFFS=$(rsync -ani --checksum -e "$RSYNC_RSH" \
                  --files-from="$ALL_ENC" "$CACHE/" "$H:$DEST/" 2>/dev/null \
            | grep -E '^[<>ch.*][fL]' || true)

    if [ -n "$DIFFS" ]; then
        # Count only -- an itemized line is a path, and a path here is a player.
        echo "[corpus-offsite] $H: $(printf '%s\n' "$DIFFS" | grep -c .) of $N_OBJ object(s) missing or corrupt on arrival" >&2
        RC=1
        continue
    fi

    echo "[corpus-offsite] $H: $N_OBJ/$N_OBJ object(s) verified by rsync --checksum ($BUNDLE_OBJECTS bundle, $WC_OBJECTS weapon-context)"
    # Two copies: a stable name a restore can always reach for, and a dated one,
    # because the stable name is overwritten every run and the manifest is the
    # only statement of what the archive was supposed to contain at that time.
    # --ignore-times because two runs inside one second write a same-size
    # manifest with the same mtime, and rsync's quick check would keep the old one.
    rsync -a -I -e "$RSYNC_RSH" "$WORK/$MANIFEST_NAME" "$H:$DEST/$MANIFEST_NAME" \
        || { echo "[corpus-offsite] $H: manifest ship failed -- the remote copy now has no durable record of what should be there" >&2; RC=1; }
    rsync -a -I --mkpath -e "$RSYNC_RSH" "$WORK/$MANIFEST_NAME" \
          "$H:$DEST/manifests/ktp-corpus-manifest-$FSTAMP.txt.age" \
        || { echo "[corpus-offsite] $H: dated manifest ship failed" >&2; RC=1; }
    # The objects went first, so the current-version manifest never names one
    # that is not there yet.
    rsync -a -I --mkpath -e "$RSYNC_RSH" "$WORK/$WC_MANIFEST_NAME" "$H:$DEST/$WC_PREFIX/$WC_MANIFEST_NAME" \
        || { echo "[corpus-offsite] $H: weapon-context manifest ship failed -- a restore would take stale versions" >&2; RC=1; }
    rsync -a -I --mkpath -e "$RSYNC_RSH" "$WORK/$WC_MANIFEST_NAME" \
          "$H:$DEST/$WC_PREFIX/manifests/ktp-weapon-context-manifest-$FSTAMP.txt.age" \
        || { echo "[corpus-offsite] $H: dated weapon-context manifest ship failed" >&2; RC=1; }
    # A stale current-version manifest restores old sidecars with no error, so
    # its arrival is checked by content like the objects'.
    printf '%s\n' "$MANIFEST_NAME" "$WC_PREFIX/$WC_MANIFEST_NAME" > "$WORK/manifests.txt"
    mkdir -p "$WORK/mstage/$WC_PREFIX" && cp -p "$WORK/$MANIFEST_NAME" "$WORK/mstage/" \
        && cp -p "$WORK/$WC_MANIFEST_NAME" "$WORK/mstage/$WC_PREFIX/" \
        || { echo "[corpus-offsite] $H: could not stage the manifests for verification" >&2; RC=1; continue; }
    if rsync -ani --checksum -e "$RSYNC_RSH" --files-from="$WORK/manifests.txt" \
             "$WORK/mstage/" "$H:$DEST/" 2>/dev/null | grep -qE '^[<>ch.*][fL]'; then
        echo "[corpus-offsite] $H: a current manifest on the far side is not the one this run wrote" >&2
        RC=1
    fi
done

if [ "$RC" -ne 0 ]; then
    echo "[corpus-offsite] FAILED: at least one target is incomplete" >&2
    exit 1
fi
echo "[corpus-offsite] OK: $COUNT encrypted bundle(s) and $WC_COUNT weapon-context sidecar(s) verified on every target"
echo "[corpus-offsite] NOTE: arrival is proven, recoverability is not -- this host holds no key. Run ktp-corpus-drill.sh."
exit 0
