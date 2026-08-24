#!/bin/bash
# Restore a backup into a scratch database and prove it came back whole.
#
# WHY. Every other check in this estate proves a dump was WRITTEN: it exists, it
# is not a stub, it reached two offsite hosts, its md5 matches. None of that
# proves it can be READ BACK. Until a restore runs, coverage is an inference.
#
# Non-destructive by construction: it restores into a scratch database, compares
# against the live one, and drops the scratch. It never writes to the source.
#
# VERIFICATION IS PER-TABLE ROW COUNTS, NOT TABLE COUNTS. A dump that creates
# every table and populates none would pass a table-count check and lose
# everything. COUNT(*) is used deliberately over information_schema.table_rows,
# which is an ESTIMATE for InnoDB and would pass on a half-restored table.
#
# 🔑 EQUALITY WITH LIVE IS THE WRONG ORACLE FOR A DATABASE THAT IS STILL BEING
# WRITTEN. A first version demanded it and reported "51 tables did not come back
# whole" for hlstatsx -- every one of them simply had MORE rows live than in a
# dump taken 36 hours earlier. That reads as catastrophic data loss and is
# actually a working backup. The categories that matter:
#
#   restored  <  live      DRIFT. Expected on a live database; not a fault.
#   restored  >  live      REAL. The dump cannot hold more than the source did
#                          unless rows were deleted live, or the restore doubled.
#   restored == 0 < live   REAL. The table exists but loaded nothing.
#   table absent from dump SCHEMA DRIFT. Created after the dump was taken.
#
# Only the middle two fail the run.
#
#   ktp-restore-test.sh <database>
#
# Exit 0 when the dump loads and no table shows a LOSS signal. Drift is reported,
# not failed on.

set -uo pipefail

DB="${1:-}"
BACKUP_DIR="${KTP_BACKUP_DIR:-/opt/backups}"
SCRATCH="${DB}_restore_test"

fail() { echo "[restore-test] FAILED: $*" >&2; exit 1; }

[ -n "$DB" ] || fail "usage: ktp-restore-test.sh <database>"
mysql -N -B -e "SELECT 1 FROM information_schema.schemata WHERE schema_name='$DB'" | grep -q 1 \
    || fail "no live database named '$DB' to compare against"

# ${DB}_[0-9]* not ${DB}_*: the names are <db>_<YYYYMMDD>_<HHMMSS>, and a bare
# prefix glob makes `hlstatsx` also match `hlstatsx_lan`. That exact bug had the
# backup watchdog validating the wrong database's file.
DUMP=$(ls -t "$BACKUP_DIR"/${DB}_[0-9]*.sql.gz 2>/dev/null | head -1)
[ -n "$DUMP" ] || fail "no dump found for '$DB' in $BACKUP_DIR"
echo "[restore-test] $DB <- $(basename "$DUMP")"

echo "[restore-test] restoring into scratch database '$SCRATCH'"
mysql -e "DROP DATABASE IF EXISTS \`$SCRATCH\`; CREATE DATABASE \`$SCRATCH\`" \
    || fail "could not create the scratch database"

# The pipe is why pipefail matters here: gunzip failing mid-stream would
# otherwise be masked by mysql's own exit code.
if ! gunzip -c "$DUMP" | mysql "$SCRATCH"; then
    mysql -e "DROP DATABASE IF EXISTS \`$SCRATCH\`"
    fail "the restore itself errored -- the dump is not loadable"
fi

echo "[restore-test] comparing every table against live '$DB'"
mismatch=0; checked=0; empty=0; rows=0; drift=0; driftrows=0
for t in $(mysql -N -B -e "SELECT table_name FROM information_schema.tables \
           WHERE table_schema='$DB' AND table_type='BASE TABLE'"); do
    a=$(mysql -N -B -e "SELECT COUNT(*) FROM \`$DB\`.\`$t\`" 2>/dev/null)
    b=$(mysql -N -B -e "SELECT COUNT(*) FROM \`$SCRATCH\`.\`$t\`" 2>/dev/null)
    checked=$((checked + 1))
    [ "${a:-0}" = "0" ] && empty=$((empty + 1))
    rows=$((rows + ${a:-0}))

    if [ -z "${b:-}" ]; then
        # Absent from the dump entirely -- created after it was taken.
        echo "  schema-drift $t: not in the dump (live=${a:-?})"
        drift=$((drift + 1))
    elif [ "$b" -gt "${a:-0}" ] 2>/dev/null; then
        echo "  LOSS-SIGNAL $t: restored=$b EXCEEDS live=${a:-?}"
        mismatch=$((mismatch + 1))
    elif [ "$b" -eq 0 ] && [ "${a:-0}" -gt 0 ]; then
        echo "  LOSS-SIGNAL $t: loaded 0 rows but live has ${a}"
        mismatch=$((mismatch + 1))
    elif [ "$b" -lt "${a:-0}" ]; then
        drift=$((drift + 1))
        driftrows=$((driftrows + a - b))
    fi
done

mysql -e "DROP DATABASE IF EXISTS \`$SCRATCH\`" || echo "[restore-test] WARNING: scratch '$SCRATCH' left behind" >&2

echo "[restore-test] tables compared : $checked"
echo "[restore-test] rows in live    : $rows"
echo "[restore-test] empty on live   : $empty"
echo "[restore-test] drifted (live ahead): $drift table(s), $driftrows row(s)"
echo "[restore-test] loss signals    : $mismatch"

# A comparison over an all-empty database passes vacuously. Say so rather than
# reporting a green that means nothing.
if [ "$checked" -eq 0 ]; then
    fail "no tables compared -- this proves nothing"
fi
if [ "$rows" -eq 0 ]; then
    fail "every live table is empty -- the comparison passed vacuously and proves nothing"
fi
if [ "$mismatch" -ne 0 ]; then
    fail "$mismatch table(s) show real loss (restored exceeded live, or loaded nothing)"
fi

echo "[restore-test] OK: $DB restores cleanly ($checked tables, $rows live rows; $drift drifted since the dump)"
exit 0
