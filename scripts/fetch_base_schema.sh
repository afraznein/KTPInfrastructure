#!/usr/bin/env bash
# Fetch a Lane B base schema from the production database. READ-ONLY.
#
# Run this ON the data server (or via ssh). It writes a schema-only dump — no
# rows, no credentials — that Lane B loads into its ephemeral MySQL.
#
# Why this is needed at all: `sql/ktp_schema.sql` in KTPHLStatsX is an
# ALTER-only overlay (8 ALTER TABLE, 3 conditional CREATEs, 4 indexes) that
# assumes the stock HLStatsX tables already exist. There is no base schema in
# any repo, so an empty database cannot be built from source. That is also why
# a fresh LAN data-server provision is the documented hazard case.
#
# ## Two grant limitations, both legitimate — handled, not routed around
#
#   * `hlstats_Servers` is denied to the read-only analytics account, because
#     HLStatsX keeps per-server rcon configuration there. We do NOT try to get
#     at it. The table is reconstructed from `information_schema` metadata,
#     which carries column types, nullability, defaults and indexes but no
#     values.
#   * Views are denied (`SHOW VIEW`). Skipped: they are reporting helpers and
#     Lane B asserts on base tables. mysqldump aborts the moment it walks into
#     one, so the table list is enumerated explicitly rather than left to
#     mysqldump's own discovery.
#
# ## Safety
#
# `--no-data` (structure only), `--single-transaction --skip-lock-tables` (no
# locking on a live server), `--no-tablespaces` (no PROCESS privilege needed).
# Nothing here writes to the database.
#
# Usage:
#   scripts/fetch_base_schema.sh [database] [output]
#   ssh krodssh@api.ktpdod.com 'bash -s' < scripts/fetch_base_schema.sh
set -uo pipefail

DB="${1:-hlstatsx}"
OUT="${2:-$HOME/base-schema.sql}"
DENIED_TABLE="hlstats_Servers"

tables=$(mysql -N -B -e "
    SELECT table_name FROM information_schema.tables
    WHERE table_schema='$DB' AND table_type='BASE TABLE'
      AND table_name <> '$DENIED_TABLE'
    ORDER BY table_name" 2>/dev/null | tr '\n' ' ')

if [ -z "$tables" ]; then
    echo "no readable base tables in '$DB' — check the account's grants" >&2
    exit 1
fi

# shellcheck disable=SC2086
mysqldump --no-data --single-transaction --skip-lock-tables --no-tablespaces \
    --set-gtid-purged=OFF --routines=FALSE --triggers=FALSE \
    "$DB" $tables > "$OUT" 2>"$OUT.err"
rc=$?
if [ $rc -ne 0 ]; then
    echo "mysqldump failed (rc=$rc):" >&2
    cat "$OUT.err" >&2
    exit $rc
fi

# Reconstruct the one denied table from metadata.
{
  echo ""
  echo "-- ---------------------------------------------------------------"
  echo "-- $DENIED_TABLE: RECONSTRUCTED from information_schema. The"
  echo "-- read-only account is denied SHOW CREATE on it because HLStatsX"
  echo "-- stores per-server rcon configuration there. Types, nullability,"
  echo "-- defaults and indexes are production's; only the DDL text is"
  echo "-- synthesised, and no values are read."
  echo "-- ---------------------------------------------------------------"
  echo "DROP TABLE IF EXISTS \`$DENIED_TABLE\`;"
  echo "CREATE TABLE \`$DENIED_TABLE\` ("
  mysql -N -B -e "
    SELECT CONCAT(
      '  \`', column_name, '\` ', column_type,
      IF(is_nullable='NO', ' NOT NULL', ' NULL'),
      CASE
        WHEN column_default IS NULL AND is_nullable='YES' THEN ' DEFAULT NULL'
        WHEN column_default IS NULL THEN ''
        WHEN column_type REGEXP '^(int|bigint|smallint|tinyint|float|double|decimal)'
          THEN CONCAT(' DEFAULT ', column_default)
        ELSE CONCAT(' DEFAULT ''', column_default, '''')
      END,
      IF(extra<>'', CONCAT(' ', extra), ''),
      ','
    )
    FROM information_schema.columns
    WHERE table_schema='$DB' AND table_name='$DENIED_TABLE'
    ORDER BY ordinal_position" 2>/dev/null
  echo "  PRIMARY KEY (\`serverId\`),"
  echo "  UNIQUE KEY \`addressport\` (\`address\`,\`port\`)"
  echo ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"
} >> "$OUT"

rm -f "$OUT.err"

echo "wrote $OUT"
echo "  tables:  $(grep -c '^CREATE TABLE' "$OUT")"
echo "  inserts: $(grep -c '^INSERT' "$OUT")   (must be 0 — schema only)"
echo "  bytes:   $(wc -c < "$OUT")"
