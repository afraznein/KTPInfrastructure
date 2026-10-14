#!/usr/bin/env bash
# Daily accrual check over the two position-corpus defects, with the pinned reports
# behind it.
#
# `sql/integrity/position_corpus_integrity.sql` (#646) and
# `producer_clock_corpus_integrity.sql` (#649) pin one re-runnable definition each for
# an epoch-zero `event_time` and an orphan `match_id`. Nothing ran them: no cron entry,
# no timer, no CI leg, no runbook. So they answered "has the source stopped" only when a
# human remembered the command, and *stopped* is exactly the state that regresses quietly.
#
# ⛔ THIS DOES NOT PARSE THEIR OUTPUT, AND THE FIRST VERSION OF THIS SCRIPT DID.
# That version read a named metric out of `mysql --table` text, which cannot work here:
# the position file is ROW-oriented key/value (`| 9 | rows_max_id | 6684393 |` -- the
# metric name is a VALUE in a name column) while the producer-clock file is
# COLUMN-oriented per stream. One parser keyed on column names cannot read both, and the
# trial run proved it: it reported `orphan_max_id=9` (the ROW NUMBER, while every real
# cell read NULL), `epoch_zero_rows=58442` against a true 326,429, and the SAME watermark
# for two different tables. It would have alerted on garbage every morning.
#
# So the alerting question is asked DIRECTLY, in two trivial indexed SELECTs per stream,
# and the predicate is the one the .sql files use -- verified against them: on
# 2026-10-14 `event_time = FROM_UNIXTIME(0)` returns exactly 326,429 position rows and
# 2,771 flag_state rows, which are the populations those files and the ledger record.
#
# THE PINNED REPORTS STILL RUN -- but only when there is something to report. A clean day
# costs two COUNTs; an accrual day pays for the full definition, which is when you want
# its sections, controls and watermarks in the log. That also keeps the daily off the
# position corpus, which the unscoped report scans for ~3 minutes.
#
# ALERT ON ACCRUAL, NEVER ON THE RUN. A wedged read reports success, and this population
# is currently CLOSED -- every defective row was inserted 2026-08-27..08-31 and the
# writer `dpl-6baa` fixed has produced none in six weeks. A guard keyed on "it ran" would
# say nothing on the day that changes.
#
# POSTING RULES, from ktp-review-integrity-guard because they are what keep a daily
# readable: a clean run posts NOTHING; accrual posts once, naming the stream and scope;
# exit 2 ALWAYS posts, because "could not look" reading as "nothing there" is the defect
# this whole effort exists to kill.
#
# READ-ONLY. Every statement is a SELECT and the session is opened READ ONLY, so the
# server refuses a write even if one is ever added to a definition.
#
# Exit codes: 0 = read, no accrual. 1 = read, accrual found. 2 = could not look.
set -uo pipefail

STATE_DIR="${KTP_CORPUS_GUARD_STATE:-/var/lib/ktp-corpus-integrity-guard}"
SQL_DIR="${KTP_CORPUS_GUARD_SQL:-/usr/local/share/ktp-infra/sql/integrity}"
MYSQL_BIN="${KTP_CORPUS_GUARD_MYSQL:-mysql}"
DB="${KTP_CORPUS_GUARD_DB:-hlstatsx}"
RELAY_CONF="${KTP_CORPUS_GUARD_RELAY:-/etc/ktp/discord-relay.conf}"

# >>> ktp-corpus-guard-streams
# <label>:<table>:<id column>:<report file>
# The two streams that have ever carried a defective row. Adding one here is the whole
# change needed to watch it; the predicates below are shared because both defects are
# defined the same way on every stream.
STREAMS=(
  "position:ktp_position_samples:id:position_corpus_integrity.sql"
  "flag_state:ktp_flag_state_events:id:producer_clock_corpus_integrity.sql"
)
# <<< ktp-corpus-guard-streams

# >>> ktp-corpus-guard-predicates
# Epoch zero: the .sql files' own definition. FROM_UNIXTIME(0) renders 1969-12-31
# 19:00:00 on this box because the server clock is ET -- ⛔ never hardcode that literal,
# and never a UTC one either; let the function do it.
EPOCH_ZERO_PRED='event_time = FROM_UNIXTIME(0)'
# Orphan: a match_id with no row in ktp_matches. ⚠️ Guarded by a sentinel below, because
# an UNREADABLE ktp_matches makes every row score as an orphan -- the exact false finding
# the .sql files halt on rather than report.
ORPHAN_PRED='match_id IS NOT NULL AND match_id <> "" AND match_id NOT IN (SELECT match_id FROM ktp_matches)'
# <<< ktp-corpus-guard-predicates

ts() { date '+%Y-%m-%d %H:%M:%S %Z'; }
log() { printf '[%s] %s\n' "$(ts)" "$*"; }
die() { log "FATAL: $*"; post_alert page "Corpus integrity: $*"; exit 2; }

q() {  # one scalar, or empty on failure
    "$MYSQL_BIN" --batch --skip-column-names \
        --init-command="SET SESSION TRANSACTION READ ONLY" "$DB" -e "$1" 2>&1
}

post_alert() {
    local severity="$1" text="$2"
    local routing=/usr/local/bin/ktp-alert-routing.sh
    if [ ! -r "$routing" ] || [ ! -r "$RELAY_CONF" ] || ! command -v jq >/dev/null; then
        log "WOULD POST ($severity) but routing, relay conf or jq is unavailable: $text"
        return 0
    fi
    # shellcheck source=/dev/null
    . "$RELAY_CONF"; . "$routing"
    ktp_alert_route "$severity" || { log "unknown severity $severity"; return 0; }
    ktp_alert_channel "$KTP_ALERT_LANE" "${ALERT_CHANNEL:-}" || {
        log "no channel for lane $KTP_ALERT_LANE; not guessing one"; return 0; }
    local payload http
    payload="$(jq -n --arg ch "$KTP_ALERT_CHANNEL" \
        --arg title "${KTP_ALERT_GLYPH} KTP corpus integrity — $(hostname -s)" \
        --arg desc "$text" --argjson color "$KTP_ALERT_COLOR" \
        '{channelId:$ch, embeds:[{title:$title, description:$desc, color:$color}]}')"
    http="$(curl -sS -o /dev/null -w '%{http_code}' -X POST "${RELAY_URL:-}" \
        -H "X-Relay-Auth: ${AUTH_SECRET:-}" -H 'Content-Type: application/json' \
        -d "$payload" || echo 000)"
    log "posted ($severity) HTTP $http via lane $KTP_ALERT_LANE"
}

[ -d "$STATE_DIR" ] || mkdir -p "$STATE_DIR" || die "cannot create $STATE_DIR"
command -v "$MYSQL_BIN" >/dev/null || die "$MYSQL_BIN not on PATH"

# The sentinel the .sql files halt on: an ungranted or empty ktp_matches turns every row
# into an orphan, so refuse to report rather than report a corpus-wide false finding.
matches_rows="$(q 'SELECT COUNT(*) FROM ktp_matches')"
case "$matches_rows" in
    ''|*[!0-9]*) die "ktp_matches is not readable ($matches_rows) -- every row would score as an orphan" ;;
    0)           die "ktp_matches has 0 rows -- every row would score as an orphan" ;;
esac
log "sentinel ok: ktp_matches has $matches_rows rows"

log "corpus-integrity guard starting; state=$STATE_DIR"
overall=0
accrued=""

for entry in "${STREAMS[@]}"; do
    IFS=: read -r label table idcol report <<<"$entry"

    wm_file="$STATE_DIR/$label.watermark"
    prev="$(cat "$wm_file" 2>/dev/null || true)"
    case "$prev" in ''|*[!0-9]*) prev=0 ;; esac

    new_wm="$(q "SELECT COALESCE(MAX($idcol),0) FROM $table")"
    case "$new_wm" in
        ''|*[!0-9]*) die "$label: could not read MAX($idcol) from $table ($new_wm)" ;;
    esac

    ez="$(q "SELECT COUNT(*) FROM $table WHERE $idcol > $prev AND $EPOCH_ZERO_PRED")"
    orph="$(q "SELECT COUNT(*) FROM $table WHERE $idcol > $prev AND $ORPHAN_PRED")"
    for v in "$ez" "$orph"; do
        case "$v" in ''|*[!0-9]*) die "$label: a defect count did not return a number ($v)" ;; esac
    done

    log "$label: ids above $prev -> epoch_zero=$ez orphan=$orph; watermark $prev -> $new_wm"

    if [ "$ez" -gt 0 ] || [ "$orph" -gt 0 ]; then
        overall=1
        accrued="$accrued"$'\n'"• \`$table\`: epoch_zero=$ez orphan=$orph above id $prev"
        # Something happened, so pay for the pinned definition and log all of it.
        if [ -r "$SQL_DIR/$report" ]; then
            log "$label: ACCRUAL -- running the pinned report $report scoped to ids above $prev"
            "$MYSQL_BIN" --table \
                --init-command="SET SESSION TRANSACTION READ ONLY; SET @since_id := $prev" \
                "$DB" < "$SQL_DIR/$report" 2>&1 || log "$label: the pinned report exited non-zero"
        else
            log "$label: ACCRUAL but $SQL_DIR/$report is not readable -- no detail captured"
        fi
    fi

    printf '%s\n' "$new_wm" > "$wm_file" || die "cannot write $wm_file"
done

if [ -n "$accrued" ]; then
    post_alert warn "A corpus-integrity defect has ACCRUED — this population was closed since 2026-08-31 and is not any more.${accrued}"
fi

log "corpus-integrity guard done; exit $overall"
exit "$overall"
