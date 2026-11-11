#!/bin/bash
# Run KTPAntiCheat's scripts/check-migrations-applied.py on the data server, against the
# live hlstatsx schema and the ledger as it stands on that repo's origin/main right now.
#
# Wrapped by ktp-run-record.sh from ktp-migrations-applied-check.service; runbook:
# docs/runbooks/MIGRATIONS_APPLIED_CHECK.md.
#
# Exit codes are the checker's, unchanged: 0 clean, 1 a finding (a migration not applied,
# or a ledger row that contradicts the schema), 2 could not check. 1 and 2 both fail the
# unit, so both reach OnFailure=.
#
# The success stamp is written only when the checker ran to a verdict (0 or 1). The
# health sweep ages that stamp, which is what catches a timer that stops firing or a
# run that dies before checking anything -- states in which the unit reads healthy.

set -uo pipefail

STATE_ROOT="${STATE_DIRECTORY:-}"
STATE_ROOT="${STATE_ROOT%%:*}"
CHECKOUT="${KTP_AC_CHECKOUT:-${STATE_ROOT:+$STATE_ROOT/KTPAntiCheat}}"
STAMP="${KTP_MIGRATIONS_CHECK_STAMP:-${STATE_ROOT:+$STATE_ROOT/last-checked}}"
REF="${KTP_AC_REF:-origin/main}"
DB="${KTP_AC_DB:-hlstatsx}"

cannot_check() {
    echo "CANNOT CHECK: $* -- this is not evidence that any migration is unapplied." >&2
    exit 2
}

[ -n "$CHECKOUT" ] || cannot_check "no KTP_AC_CHECKOUT and no STATE_DIRECTORY"
[ -n "$STAMP" ] || cannot_check "no KTP_MIGRATIONS_CHECK_STAMP and no STATE_DIRECTORY"
git -C "$CHECKOUT" rev-parse --git-dir >/dev/null 2>&1 \
    || cannot_check "$CHECKOUT is not a git checkout of KTPAntiCheat"

# A stale ledger silently skips every migration newer than it, so a failed fetch is a
# could-not-check, never a run against whatever was fetched last.
git -C "$CHECKOUT" fetch --quiet origin || cannot_check "git fetch failed in $CHECKOUT"
COMMIT="$(git -C "$CHECKOUT" rev-parse --verify --quiet "$REF^{commit}")" \
    || cannot_check "$REF does not resolve in $CHECKOUT"

WORK="$(mktemp -d)" || cannot_check "mktemp failed"
trap 'rm -rf "$WORK"' EXIT

# Only the three paths the checker reads, from the fetched commit, never the working tree.
git -C "$CHECKOUT" archive "$COMMIT" \
        scripts/check-migrations-applied.py docs/MIGRATIONS_APPLIED.md sql/migrations \
    | tar -x -C "$WORK" \
    || cannot_check "could not extract the checker and ledger at $COMMIT"
CHECKER="$WORK/scripts/check-migrations-applied.py"

# The snapshot query is the checker's own; reading it from there keeps one copy of it.
SNAPSHOT_SQL="$(KTP_AC_DB="$DB" python3 -I - "$CHECKER" <<'PY'
import importlib.util
import sys
spec = importlib.util.spec_from_file_location("checker", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
sys.stdout.write(mod.SNAPSHOT_SQL.format(db=mod.DB))
PY
)" || cannot_check "could not read SNAPSHOT_SQL from the checker at $COMMIT"
[ -n "$SNAPSHOT_SQL" ] || cannot_check "the checker's SNAPSHOT_SQL is empty at $COMMIT"

# Local socket, not the checker's SSH path: this IS the data server.
printf '%s\n' "$SNAPSHOT_SQL" | mysql -N -B --raw "$DB" > "$WORK/schema.tsv" \
    || cannot_check "mysql could not read the $DB schema"

echo "ledger: KTPAntiCheat $REF at $COMMIT"
KTP_AC_DB="$DB" python3 -I "$CHECKER" --snapshot "$WORK/schema.tsv"
rc=$?

case "$rc" in
    0|1)
        tmp="$STAMP.tmp.$$"
        if printf 'checked=%s\ncommit=%s\nrc=%s\n' \
                "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$COMMIT" "$rc" > "$tmp" \
                && mv -f "$tmp" "$STAMP"; then
            :
        else
            rm -f "$tmp"
            echo "could not write the success stamp $STAMP -- the health sweep will read this run as missing" >&2
            [ "$rc" -eq 0 ] && rc=2
        fi
        ;;
esac
exit "$rc"
