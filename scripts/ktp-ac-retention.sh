#!/bin/bash
# KTP AntiCheat data retention (data server, root)
#
# The 2026-05-23 weapon-timeline migration promised a "ktp-ac-retention daily
# cron" that never existed (found in the 2026-07 hardening review, W1-7).
# This is the canonical implementation. Five sweeps:
#
#   1. Evidence bundles: /opt/ktp-ac-api/uploads/YYYY-MM-DD/ day-dirs older
#      than UPLOAD_RETENTION_DAYS. DB session rows (verdicts, review state)
#      are kept forever — only the raw ZIPs age out, and each pruned bundle's
#      zip_path is nulled so /api/mybundles availability stays truthful.
#      Sessions still under admin review past the window should be exported
#      before they age out.
#   2. Weapon timeline rows (ktp_ac_weapon_hits / _switches) older than
#      WEAPON_RETENTION_DAYS, deleted in LIMIT-batches — a naive one-shot
#      DELETE of tens of millions of rows on spinning rust stalls the shared
#      MySQL (HLStatsX lives on the same instance).
#   3. Expired session tokens (24h TTL rows were never purged) older than
#      TOKEN_RETENTION_DAYS past expiry.
#   4. ktp_net_sessions identity: name + steam_id blanked on rows older than
#      NET_IDENTITY_RETENTION_DAYS. The only sweep that is an UPDATE rather
#      than a DELETE -- the operator ruled on 2026-10-08 that the per-connection
#      netcode metrics are kept indefinitely and only the identity ages out, so
#      deleting the row would take the measurement with the name. Same
#      blank-rather-than-delete shape as sweep 1's zip_path.
#   5. ktp_net_intervals identity: the per-interval worst-player name columns
#      set to NULL on rows older than the same NET_IDENTITY_RETENTION_DAYS. The
#      interval metrics and the *_slot columns stay; only the names age out.
#
# Uses the root MySQL socket (same auth as migrations: `mysql hlstatsx`).
# Cron: /etc/cron.d/ktp-ac-retention (04:40 ET daily, after ktp-backup).
# DRY_RUN=1 prints what would be deleted or blanked without touching anything.

set -euo pipefail

UPLOADS_DIR="${UPLOADS_DIR:-/opt/ktp-ac-api/uploads}"
# Opt-in by design: unset means DO NOT SWEEP. A default that deletes evidence is the
# wrong failure mode for an append-only archive -- an operator who forgets to set it
# loses bundles, which is what happened before the 2026-08-16 hold. 0 = retain all.
UPLOAD_RETENTION_DAYS="${UPLOAD_RETENTION_DAYS:-0}"
# Weapon rows are what explain a retained bundle, and bundles are held indefinitely --
# at 30d a session reviewed a month later had an empty weapon timeline in its dossier.
# 365d is the bounded version of forever: ~10 GB steady state, and it deletes nothing
# until 2027-08-25 because the sweep already took everything older.
WEAPON_RETENTION_DAYS="${WEAPON_RETENTION_DAYS:-365}"
# Never shorter than the API purge grace past expiry, or this becomes the real bound and
# a staged bundle outlives the key that verifies it. The API side pins its own three, and
# its grace now carries the offset between a login and the packaging it keys -- a client
# retries from when the bundle was written, not from when the session began.
TOKEN_RETENTION_DAYS="${TOKEN_RETENTION_DAYS:-22}"
# Ruled 2026-10-08: ktp_net_sessions metrics are kept forever, identity for 90 days. 0 means
# keep identity forever -- and like UPLOAD_RETENTION_DAYS that guard has to sit at the sweep
# too, because INTERVAL 0 DAY resolves to NOW() and would blank the whole table.
NET_IDENTITY_RETENTION_DAYS="${NET_IDENTITY_RETENTION_DAYS:-90}"
BATCH_SIZE="${BATCH_SIZE:-10000}"
DRY_RUN="${DRY_RUN:-0}"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

# Declared once so the DRY_RUN count and the sweep can never describe different rows.
net_identity_where="ts < NOW() - INTERVAL ${NET_IDENTITY_RETENTION_DAYS} DAY AND steam_id <> ''"

# Every player-name column of ktp_net_intervals, as read from information_schema on the
# data server; a column added there and not here keeps its names forever.
NET_INTERVAL_NAME_COLUMNS="lagcomp_first_name latency_worst_name jitter_worst_name
    maxunlag_excess_worst_name shadow_worst_name drops_worst_name latzero_worst_name
    updates_worst_name loss_worst_name subinterval_worst_name synth_worst_name
    interp_diff_worst_name"
net_interval_set="" net_interval_named=""
for c in $NET_INTERVAL_NAME_COLUMNS; do
    net_interval_set="${net_interval_set:+$net_interval_set, }$c = NULL"
    net_interval_named="${net_interval_named:+$net_interval_named OR }$c IS NOT NULL"
done
net_interval_where="ts < NOW() - INTERVAL ${NET_IDENTITY_RETENTION_DAYS} DAY AND (${net_interval_named})"

# ── 1. Upload day-dirs ────────────────────────────────────────────────
# 0 or unset means RETAIN EVERYTHING. The guard has to be HERE, not only in the
# default: "-0 days" resolves to TODAY, so a bare default of 0 would sweep the
# entire archive rather than none of it.
# Directory tested first and separately: one combined guard called the store
# missing whenever retention was merely off, and the two need opposite responses.
# Both messages interpolate, so grep the format string — the rendered phrase
# returns zero on a script that plainly emits it, and reads as "not in the file".
if [ ! -d "$UPLOADS_DIR" ]; then
    echo "[$(ts)] ac-retention: WARN $UPLOADS_DIR missing; skipping upload sweep" >&2
elif [ "${UPLOAD_RETENTION_DAYS}" -le 0 ]; then
    echo "[$(ts)] ac-retention: upload sweep is off (UPLOAD_RETENTION_DAYS=${UPLOAD_RETENTION_DAYS}); retaining all bundles"
else
    cutoff=$(date -d "-${UPLOAD_RETENTION_DAYS} days" '+%Y-%m-%d')
    swept=0
    for d in "$UPLOADS_DIR"/????-??-??; do
        [ -d "$d" ] || continue
        day=$(basename "$d")
        # Lexicographic compare works for ISO dates.
        if [[ "$day" < "$cutoff" ]]; then
            # SQL-escape single quotes (defensive; the fixed uploads path has none).
            esc=${d//\'/\'\'}
            if [ "$DRY_RUN" = "1" ]; then
                n=$(mysql hlstatsx -N -e "SELECT COUNT(*) FROM ktp_ac_sessions WHERE zip_path LIKE '${esc}/%';")
                echo "[$(ts)] DRY_RUN: would delete $d ($(du -sh "$d" 2>/dev/null | cut -f1)) and NULL ${n} zip_path(s)"
            else
                rm -rf -- "$d"
                # Reconcile the DB: the session row lives forever but its ZIP is now
                # gone, so clear zip_path. Otherwise GET /api/mybundles reports
                # available:true for a bundle whose file no longer exists — the
                # detail/download routes 410 on the file stat, but the LIST derives
                # availability from this column alone.
                mysql hlstatsx -e "UPDATE ktp_ac_sessions SET zip_path = NULL WHERE zip_path LIKE '${esc}/%';"
            fi
            swept=$((swept + 1))
        fi
    done
    echo "[$(ts)] ac-retention: uploads swept ${swept} day-dir(s) older than ${cutoff}"
fi

# ── 2 + 3 + 4 + 5. DB rows, batched ───────────────────────────────────────
# Loops until a batch changes fewer than BATCH_SIZE rows. Each batch is its
# own statement so InnoDB commits between batches and replication/undo stays
# bounded. Every table here is InnoDB, so a batch takes row locks and readers
# are never blocked -- the bound that matters is undo size, not lock scope.
batched_write() {
    local label="$1" sql="$2" verb="$3"
    local total=0
    while :; do
        local changed
        changed=$(mysql hlstatsx -N -e "${sql} LIMIT ${BATCH_SIZE}; SELECT ROW_COUNT();" | tail -1)
        total=$((total + changed))
        [ "$changed" -lt "$BATCH_SIZE" ] && break
        sleep 1   # breathe between batches; HLStatsX shares this instance
    done
    echo "[$(ts)] ac-retention: ${label} ${verb} ${total} row(s)"
}

if [ "$DRY_RUN" = "1" ]; then
    mysql hlstatsx -N -e "
        SELECT CONCAT('DRY_RUN: weapon_hits rows past ${WEAPON_RETENTION_DAYS}d: ', COUNT(*)) FROM ktp_ac_weapon_hits    WHERE ingested_at < NOW() - INTERVAL ${WEAPON_RETENTION_DAYS} DAY;
        SELECT CONCAT('DRY_RUN: weapon_switches rows past ${WEAPON_RETENTION_DAYS}d: ', COUNT(*)) FROM ktp_ac_weapon_switches WHERE ingested_at < NOW() - INTERVAL ${WEAPON_RETENTION_DAYS} DAY;
        SELECT CONCAT('DRY_RUN: expired tokens past ${TOKEN_RETENTION_DAYS}d: ', COUNT(*)) FROM ktp_ac_session_tokens  WHERE expires_at < NOW() - INTERVAL ${TOKEN_RETENTION_DAYS} DAY;"
    if [ "${NET_IDENTITY_RETENTION_DAYS}" -gt 0 ]; then
        mysql hlstatsx -N -e "SELECT CONCAT('DRY_RUN: net_sessions identities past ${NET_IDENTITY_RETENTION_DAYS}d: ', COUNT(*)) FROM ktp_net_sessions WHERE ${net_identity_where};"
        mysql hlstatsx -N -e "SELECT CONCAT('DRY_RUN: net_intervals identities past ${NET_IDENTITY_RETENTION_DAYS}d: ', COUNT(*)) FROM ktp_net_intervals WHERE ${net_interval_where};"
    else
        echo "DRY_RUN: net_sessions and net_intervals identity blanking is off (NET_IDENTITY_RETENTION_DAYS=0)"
    fi
    exit 0
fi

batched_write "weapon_hits"     "DELETE FROM ktp_ac_weapon_hits     WHERE ingested_at < NOW() - INTERVAL ${WEAPON_RETENTION_DAYS} DAY" deleted
batched_write "weapon_switches" "DELETE FROM ktp_ac_weapon_switches WHERE ingested_at < NOW() - INTERVAL ${WEAPON_RETENTION_DAYS} DAY" deleted
batched_write "session_tokens"  "DELETE FROM ktp_ac_session_tokens  WHERE expires_at < NOW() - INTERVAL ${TOKEN_RETENTION_DAYS} DAY" deleted

# An UPDATE, not a DELETE: the metrics outlive the identity. The `steam_id <> ''` guard makes
# the batched loop COMPLETE as well as idempotent -- ROW_COUNT() counts rows CHANGED, so
# without it batch 2 re-selects rows it already blanked, reports 0, and stops early.
# net_intervals needs the same completeness guard: any name still set, or the loop stops early.
if [ "${NET_IDENTITY_RETENTION_DAYS}" -gt 0 ]; then
    batched_write "net_sessions identity" \
        "UPDATE ktp_net_sessions SET name = '', steam_id = '' WHERE ${net_identity_where}" blanked
    batched_write "net_intervals identity" \
        "UPDATE ktp_net_intervals SET ${net_interval_set} WHERE ${net_interval_where}" blanked
else
    echo "[$(ts)] ac-retention: net_sessions and net_intervals identity blanking is off (NET_IDENTITY_RETENTION_DAYS=0)"
fi

echo "[$(ts)] ac-retention: done"
