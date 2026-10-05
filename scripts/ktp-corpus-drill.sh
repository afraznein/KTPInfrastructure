#!/bin/bash
# Prove the encrypted corpus backup can actually be restored -- on synthetic data.
#
# WHY THIS IS NOT OPTIONAL. ktp-corpus-offsite.sh encrypts to a public key and
# holds no private half, so the machine that makes the backup cannot read it
# back. It can prove the bytes arrived; it cannot prove they are recoverable.
# Nothing in the scheduled path ever decrypts anything, which means a wrong
# recipient, a lost identity file or a mangled manifest would sit undetected
# until the day the corpus was needed. This is the only thing that closes it.
#
# IT NEVER TOUCHES A REAL BUNDLE. The drill builds its own corpus of random
# bytes in a temp directory, in the same YYYY-MM-DD/*.zip shape, with synthetic
# names that deliberately do not resemble real ones -- no player names, no
# SteamID shape. Real evidence is not test data and does not get copied around
# to prove a pipeline works.
#
# IT DEFAULTS TO A LOCAL TARGET, so a drill moves nothing off the machine. Pass
# --remote to exercise the real transport once the local round trip passes; that
# writes synthetic files to a scratch directory on the archive box, and it is
# the operator's call whether to bother.
#
# WHAT IT PROVES, IN ORDER: selection shape, encryption to the configured
# recipients, opaque remote naming, manifest encryption, transfer, and then a
# full decrypt and byte-for-byte comparison against the source -- for the bundles
# and for the weapon-context sidecars, after one sidecar is rewritten in place so
# the restore has to pick the current version over the older object. Plus the
# negative: that a restore WITHOUT the key fails loudly instead of producing a
# partial tree that looks like a success.
#
#   --key    <identity file>   age private key matching KTP_CORPUS_AGE_RECIPIENTS
#   --days   <n>               synthetic day-dirs to build (default 5)
#   --per    <n>               bundles per day-dir (default 4)
#   --wc     <n>               synthetic weapon-context sidecars (default 6)
#   --remote                   also run the real transport to a scratch dir
#
# Run it quarterly, and after any change to either script or to the key set.
# No hostnames or credentials in this file. This repository is public.

set -uo pipefail
umask 077

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OFFSITE="${KTP_CORPUS_OFFSITE_BIN:-$HERE/ktp-corpus-offsite.sh}"
RESTORE="${KTP_CORPUS_RESTORE_BIN:-$HERE/ktp-corpus-restore.sh}"

KEY=""
NDAYS=5
NPER=4
NWC=6
REMOTE=0
while [ $# -gt 0 ]; do
    case "$1" in
        --key)    KEY="${2:-}"; shift 2 ;;
        --days)   NDAYS="${2:-}"; shift 2 ;;
        --per)    NPER="${2:-}"; shift 2 ;;
        --wc)     NWC="${2:-}"; shift 2 ;;
        --remote) REMOTE=1; shift ;;
        *) echo "[corpus-drill] unknown argument: $1" >&2; exit 1 ;;
    esac
done

fail() { echo "[corpus-drill] FAILED: $*" >&2; exit 1; }

command -v age >/dev/null 2>&1 || fail "age is not installed."
[ -n "$KEY" ] || fail "--key is required: the drill exists to prove a key can read the archive."
[ -f "$KEY" ] || fail "--key $KEY does not exist."
[ -x "$OFFSITE" ] || fail "$OFFSITE is not executable."
[ -x "$RESTORE" ] || fail "$RESTORE is not executable."
[ -n "${KTP_CORPUS_AGE_RECIPIENTS:-}" ] \
    || fail "KTP_CORPUS_AGE_RECIPIENTS is unset. Drill the configuration you actually run, not a fresh one."

# The drill is worthless if it silently generates its own keypair and proves
# that keypair works. It must exercise the recipients the real job is using, and
# the identity given must be one of them.
PUB=$(age-keygen -y "$KEY" 2>/dev/null)
[ -n "$PUB" ] || fail "could not derive a public key from $KEY."
case " ${KTP_CORPUS_AGE_RECIPIENTS} " in
    *" $PUB "*) ;;
    *) fail "the identity in $KEY is not among KTP_CORPUS_AGE_RECIPIENTS. This drill would prove a key nobody encrypts to." ;;
esac
echo "[corpus-drill] identity matches a configured recipient"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
SRC="$WORK/corpus"
ARCHIVE="$WORK/archive"
BACK="$WORK/restored"
WCSRC="$WORK/weapon-context"
WCBACK="$WORK/wc-restored"
mkdir -p "$SRC" "$ARCHIVE" "$WCSRC/tmp"

# ------------------------------------------------------- synthetic corpus
# Random bytes, realistic sizes, deliberately unrealistic names.
N=0
for i in $(seq 1 "$NDAYS"); do
    day=$(date -u -d "-$i days" '+%Y-%m-%d')
    mkdir -p "$SRC/$day"
    for j in $(seq 1 "$NPER"); do
        head -c $(( (RANDOM % 900 + 100) * 1024 )) /dev/urandom \
            > "$SRC/$day/DRILL_synthetic_${i}_${j}.zip" || fail "could not build the synthetic corpus"
        N=$(( N + 1 ))
    done
done
echo "[corpus-drill] built $N synthetic bundle(s) across $NDAYS day-dir(s)"

# Same <shard>/<session>.weapons.json shape as the store, spread over two shards,
# plus an in-flight temp file that must never be selected.
for k in $(seq 1 "$NWC"); do
    shard=$(( 998 + k % 2 ))
    mkdir -p "$WCSRC/$shard"
    head -c $(( (RANDOM % 200 + 20) * 1024 )) /dev/urandom \
        > "$WCSRC/$shard/$(( shard * 1000 + k )).weapons.json" || fail "could not build the synthetic sidecars"
done
head -c 4096 /dev/urandom > "$WCSRC/tmp/0123456789abcdef0123456789abcdef"
echo "[corpus-drill] built $NWC synthetic weapon-context sidecar(s)"

run_leg() {
    local label="$1" hosts="$2" rsh="$3" dest="$4"
    echo "[corpus-drill] === $label"
    KTP_CORPUS_SRC="$SRC" \
    KTP_WEAPON_CONTEXT_SRC="$WCSRC" \
    KTP_CORPUS_ENC_CACHE="$WORK/cache-$label" \
    KTP_OFFSITE_RSYNC_HOSTS="$hosts" \
    KTP_OFFSITE_RSYNC_RSH="$rsh" \
    KTP_OFFSITE_RSYNC_CORPUS_DIR="$dest" \
    KTP_OFFSITE_RSYNC_DIR="__unset_demo__" \
    KTP_OFFSITE_RSYNC_DB_DIR="__unset_db__" \
        "$OFFSITE" --commit || return 1
}

# ---------------------------------------------------------- local round trip
# rsync speaks to a local path with no transport at all, so "$hosts:" would be
# wrong here; the offsite script joins host and dest with a colon, and a local
# leg gets an empty host so the spec collapses to :path -- which rsync reads as
# a remote. Use a loopback-free form instead: a single "host" of "." is not it
# either. So the local leg runs the same code with rsh=/bin/true and a host that
# resolves through a tiny shim that just drops the host argument.
cat > "$WORK/localsh" <<'SHIM'
#!/bin/sh
# rsync calls: <rsh> <host> <remote-command...>. Drop the host, run the rest
# locally. That makes a local directory look like a remote target to rsync
# without needing ssh, a daemon, or a second machine.
shift
exec "$@"
SHIM
chmod +x "$WORK/localsh"

run_leg "local" "localhost" "$WORK/localsh" "$ARCHIVE" \
    || fail "the local offsite leg failed."

[ -s "$ARCHIVE/ktp-corpus-manifest.txt.age" ] \
    || fail "no encrypted manifest in the archive."
bundle_objects() { find "$ARCHIVE" -mindepth 2 -maxdepth 2 -type f -path "$ARCHIVE/????-??-??/*.age" | wc -l; }
wc_objects() { find "$ARCHIVE/weapon-context/objects" -type f -name '*.age' 2>/dev/null | wc -l; }
OBJS=$(bundle_objects)
[ "$OBJS" -eq "$N" ] || fail "archive holds $OBJS bundle object(s), expected $N."
[ -s "$ARCHIVE/weapon-context/ktp-weapon-context-manifest.txt.age" ] \
    || fail "no encrypted weapon-context manifest in the archive."
WCOBJS=$(wc_objects)
[ "$WCOBJS" -eq "$NWC" ] || fail "archive holds $WCOBJS weapon-context object(s), expected $NWC."

# The confidentiality claim, checked rather than assumed: nothing in the archive
# may carry an original filename, and no object may be readable as a zip.
if find "$ARCHIVE" \( -name '*DRILL_synthetic*' -o -name '*.weapons.json*' \) | grep -q .; then
    fail "an original filename survived into the archive -- the opaque naming is not working."
fi
if head -c 2 "$(find "$ARCHIVE" -type f -name '*.age' ! -name 'ktp-corpus-manifest*' | head -1)" | grep -q 'PK'; then
    fail "an archive object still begins with a zip signature -- it was not encrypted."
fi
if ! head -c 21 "$(find "$ARCHIVE/weapon-context/objects" -type f -name '*.age' | head -1)" | grep -q 'age-encryption.org'; then
    fail "a weapon-context object does not carry an age header -- it was not encrypted."
fi
echo "[corpus-drill] archive holds $OBJS bundle and $WCOBJS weapon-context object(s), opaque and encrypted, with their manifests"

# ------------------------------------------- a sidecar rewritten in place
# The writer replaces a sidecar by rename when a later hydrate is more complete.
# The far side must keep the old object AND the restore must take the new one.
REWRITTEN=$(find "$WCSRC" -mindepth 2 -maxdepth 2 -name '*.weapons.json' | sort | head -1)
head -c 51200 /dev/urandom > "$WCSRC/tmp/rewrite" && mv -f "$WCSRC/tmp/rewrite" "$REWRITTEN" \
    || fail "could not rewrite a synthetic sidecar."
run_leg "local" "localhost" "$WORK/localsh" "$ARCHIVE" \
    || fail "the second local offsite leg failed."
[ "$(bundle_objects)" -eq "$N" ] || fail "the second run changed the bundle object count."
[ "$(wc_objects)" -eq $(( NWC + 1 )) ] \
    || fail "after one rewrite the archive holds $(wc_objects) weapon-context object(s), expected $(( NWC + 1 )) -- an older version was lost or the new one never shipped."
echo "[corpus-drill] a rewritten sidecar added one object and kept the old one"

# ------------------------------------------------- the negative: no key, no data
NOKEY="$WORK/wrong.key"
age-keygen -o "$NOKEY" >/dev/null 2>&1 || fail "could not mint a throwaway key for the negative test."
if "$RESTORE" --src "$ARCHIVE" --dest "$WORK/nokey" --key "$NOKEY" >/dev/null 2>&1; then
    fail "a restore with the WRONG key reported success. The archive is not confidential."
fi
if "$RESTORE" --set weapon-context --src "$ARCHIVE" --dest "$WORK/nokey-wc" --key "$NOKEY" >/dev/null 2>&1; then
    fail "a weapon-context restore with the WRONG key reported success."
fi
echo "[corpus-drill] restore with the wrong key refused, as it must"

# ------------------------------------------------------------------ restore
"$RESTORE" --src "$ARCHIVE" --dest "$BACK" --key "$KEY" || fail "the restore failed."

# The claim is not "it ran" -- it is that what came back is what went in.
if ! diff -r "$SRC" "$BACK" >/dev/null 2>&1; then
    fail "the restored tree differs from the synthetic source."
fi
echo "[corpus-drill] restored tree is byte-for-byte identical to the source"

"$RESTORE" --set weapon-context --src "$ARCHIVE" --dest "$WCBACK" --key "$KEY" \
    || fail "the weapon-context restore failed."
# Identical to the source means the rewritten file came back as its NEW bytes.
diff -r -x tmp "$WCSRC" "$WCBACK" >/dev/null 2>&1 \
    || fail "the restored sidecars differ from the current source -- the restore did not take the latest versions."
[ ! -e "$WCBACK/tmp" ] || fail "an in-flight temp file was backed up as if it were a sidecar."
echo "[corpus-drill] restored sidecars are byte-for-byte the CURRENT versions"

# ------------------------------------------------------------- real transport
if [ "$REMOTE" = "1" ]; then
    [ -n "${KTP_OFFSITE_RSYNC_HOSTS:-}" ] && [ -n "${KTP_OFFSITE_RSYNC_RSH:-}" ] \
        || fail "--remote needs KTP_OFFSITE_RSYNC_HOSTS and KTP_OFFSITE_RSYNC_RSH."
    SCRATCH="${KTP_CORPUS_DRILL_REMOTE_DIR:-}"
    [ -n "$SCRATCH" ] \
        || fail "--remote needs KTP_CORPUS_DRILL_REMOTE_DIR, a scratch path. It must not be the real corpus directory."
    [ "$SCRATCH" != "${KTP_OFFSITE_RSYNC_CORPUS_DIR:-}" ] \
        || fail "the drill scratch directory is the real corpus directory. Refusing to write synthetic bundles into the archive."
    run_leg "remote" "$KTP_OFFSITE_RSYNC_HOSTS" "$KTP_OFFSITE_RSYNC_RSH" "$SCRATCH" \
        || fail "the remote offsite leg failed."
    rm -rf "$WORK/remote-back"
    "$RESTORE" --src "$(echo "$KTP_OFFSITE_RSYNC_HOSTS" | awk '{print $1}'):$SCRATCH" \
               --rsh "$KTP_OFFSITE_RSYNC_RSH" --dest "$WORK/remote-back" --key "$KEY" \
        || fail "the remote restore failed."
    diff -r "$SRC" "$WORK/remote-back" >/dev/null 2>&1 \
        || fail "the remotely restored tree differs from the synthetic source."
    rm -rf "$WORK/remote-wc-back"
    "$RESTORE" --set weapon-context --src "$(echo "$KTP_OFFSITE_RSYNC_HOSTS" | awk '{print $1}'):$SCRATCH" \
               --rsh "$KTP_OFFSITE_RSYNC_RSH" --dest "$WORK/remote-wc-back" --key "$KEY" \
        || fail "the remote weapon-context restore failed."
    diff -r -x tmp "$WCSRC" "$WORK/remote-wc-back" >/dev/null 2>&1 \
        || fail "the remotely restored sidecars differ from the synthetic source."
    echo "[corpus-drill] real transport round-tripped $N synthetic bundle(s) and $NWC sidecar(s)"
    echo "[corpus-drill] REMINDER: remove $SCRATCH from the archive box by hand; this script does not delete on the far side."
fi

echo "[corpus-drill] OK: encrypt, ship, refuse-without-key and restore all proved on $N synthetic bundle(s) and $NWC sidecar(s)"
exit 0
