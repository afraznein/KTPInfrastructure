#!/bin/bash
# KTP AntiCheat data retention (data server, root)
#
# The 2026-05-23 weapon-timeline migration promised a "ktp-ac-retention daily
# cron" that never existed (found in the 2026-07 hardening review, W1-7).
# This is the canonical implementation. Three sweeps:
#
#   1. Evidence bundles: /opt/ktp-ac-api/uploads/YYYY-MM-DD/ day-dirs older
#      than UPLOAD_RETENTION_DAYS. DB session rows (verdicts, review state)
#      are kept forever — only the raw ZIPs age out. Sessions still under
#      admin review past the window should be exported before they age out.
#   2. Weapon timeline rows (ktp_ac_weapon_hits / _switches) older than
#      WEAPON_RETENTION_DAYS, deleted in LIMIT-batches — a naive one-shot
#      DELETE of tens of millions of rows on spinning rust stalls the shared
#      MySQL (HLStatsX lives on the same instance).
#   3. Expired session tokens (24h TTL rows were never purged) older than
#      TOKEN_RETENTION_DAYS past expiry.
#
# Uses the root MySQL socket (same auth as migrations: `mysql hlstatsx`).
# Cron: /etc/cron.d/ktp-ac-retention (04:40 ET daily, after ktp-backup).
# DRY_RUN=1 prints what would be deleted without touching anything.

set -euo pipefail

UPLOADS_DIR="${UPLOADS_DIR:-/opt/ktp-ac-api/uploads}"
UPLOAD_RETENTION_DAYS="${UPLOAD_RETENTION_DAYS:-60}"
WEAPON_RETENTION_DAYS="${WEAPON_RETENTION_DAYS:-30}"
TOKEN_RETENTION_DAYS="${TOKEN_RETENTION_DAYS:-7}"
BATCH_SIZE="${BATCH_SIZE:-10000}"
DRY_RUN="${DRY_RUN:-0}"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

# ── 1. Upload day-dirs ────────────────────────────────────────────────
if [ -d "$UPLOADS_DIR" ]; then
    cutoff=$(date -d "-${UPLOAD_RETENTION_DAYS} days" '+%Y-%m-%d')
    swept=0
    for d in "$UPLOADS_DIR"/????-??-??; do
        [ -d "$d" ] || continue
        day=$(basename "$d")
        # Lexicographic compare works for ISO dates.
        if [[ "$day" < "$cutoff" ]]; then
            if [ "$DRY_RUN" = "1" ]; then
                echo "[$(ts)] DRY_RUN: would delete $d ($(du -sh "$d" 2>/dev/null | cut -f1))"
            else
                rm -rf -- "$d"
            fi
            swept=$((swept + 1))
        fi
    done
    echo "[$(ts)] ac-retention: uploads swept ${swept} day-dir(s) older than ${cutoff}"
else
    echo "[$(ts)] ac-retention: WARN $UPLOADS_DIR missing; skipping upload sweep" >&2
fi

# ── 2 + 3. DB rows, batched ───────────────────────────────────────────
# Loops until a batch deletes fewer than BATCH_SIZE rows. Each batch is its
# own statement so InnoDB commits between batches and replication/undo stays
# bounded.
batched_delete() {
    local label="$1" sql="$2"
    local total=0
    while :; do
        local deleted
        deleted=$(mysql hlstatsx -N -e "${sql} LIMIT ${BATCH_SIZE}; SELECT ROW_COUNT();" | tail -1)
        total=$((total + deleted))
        [ "$deleted" -lt "$BATCH_SIZE" ] && break
        sleep 1   # breathe between batches; HLStatsX shares this instance
    done
    echo "[$(ts)] ac-retention: ${label} deleted ${total} row(s)"
}

if [ "$DRY_RUN" = "1" ]; then
    mysql hlstatsx -N -e "
        SELECT CONCAT('DRY_RUN: weapon_hits rows past ${WEAPON_RETENTION_DAYS}d: ', COUNT(*)) FROM ktp_ac_weapon_hits    WHERE ingested_at < NOW() - INTERVAL ${WEAPON_RETENTION_DAYS} DAY;
        SELECT CONCAT('DRY_RUN: weapon_switches rows past ${WEAPON_RETENTION_DAYS}d: ', COUNT(*)) FROM ktp_ac_weapon_switches WHERE ingested_at < NOW() - INTERVAL ${WEAPON_RETENTION_DAYS} DAY;
        SELECT CONCAT('DRY_RUN: expired tokens past ${TOKEN_RETENTION_DAYS}d: ', COUNT(*)) FROM ktp_ac_session_tokens  WHERE expires_at < NOW() - INTERVAL ${TOKEN_RETENTION_DAYS} DAY;"
    exit 0
fi

batched_delete "weapon_hits"     "DELETE FROM ktp_ac_weapon_hits     WHERE ingested_at < NOW() - INTERVAL ${WEAPON_RETENTION_DAYS} DAY"
batched_delete "weapon_switches" "DELETE FROM ktp_ac_weapon_switches WHERE ingested_at < NOW() - INTERVAL ${WEAPON_RETENTION_DAYS} DAY"
batched_delete "session_tokens"  "DELETE FROM ktp_ac_session_tokens  WHERE expires_at < NOW() - INTERVAL ${TOKEN_RETENTION_DAYS} DAY"

echo "[$(ts)] ac-retention: done"
