#!/usr/bin/env bash
# Daily accrual read over the two position-corpus integrity definitions.
#
# `sql/integrity/position_corpus_integrity.sql` (#646) and
# `producer_clock_corpus_integrity.sql` (#649) pin one re-runnable definition each for
# the two defects -- an epoch-zero `event_time` and an orphan `match_id`. Nothing ran
# them: no cron entry, no timer, no CI leg, no runbook. So they answered "has the source
# stopped" only when a human remembered the command, and *stopped* is exactly the state
# that regresses quietly.
#
# THE SQL IS THE DEFINITION AND STAYS THAT WAY. This wrapper adds a schedule, a log and
# a watermark; it issues no SELECT of its own. Every count, control and threshold lives
# in the committed .sql files, so a change to what "defect" means is a change there.
#
# WHY THE SCOPED FORM. Both files honour @since_id in every section and default it to 0.
# Unscoped they scan the whole corpus -- the right shape for a baseline, the wrong shape
# for a daily. Scoped to ids above the last reading's rows_max_id they answer the only
# question a daily can answer: did a NEW defective row appear? The files say so
# themselves: "orphan_max_id against the previous reading's rows_max_id answers accrual".
#
# ALERT ON THE WATERMARK, NEVER ON THE RUN. A wedged read reports success, and the
# defect population this watches is currently CLOSED -- 326,429 position rows and 2,771
# flag_state rows, all inserted 2026-08-27..08-31, nothing since. A guard that alerts on
# "it ran" would say nothing on the day that changes.
#
# POSTING RULES, copied from ktp-review-integrity-guard because they are what keep a
# daily alert readable:
#   - a clean run posts NOTHING. A standing finding re-posted every morning trains
#     everyone to mute the channel.
#   - a run that finds accrual posts once, naming the stream and the new watermark.
#   - exit 2 ALWAYS posts. "could not look" reading as "nothing there" is the exact
#     defect this whole effort exists to kill.
#
# READ-ONLY. Both files are pure SELECT (proven before first use: 13 and 16
# statement-initial SELECTs, 0 writes of any kind), and the session is opened READ ONLY
# so the server refuses a write even if one were ever added.
#
# Exit codes: 0 = read, no accrual. 1 = read, accrual found. 2 = could not look.
set -uo pipefail

STATE_DIR="${KTP_CORPUS_GUARD_STATE:-/var/lib/ktp-corpus-integrity-guard}"
SQL_DIR="${KTP_CORPUS_GUARD_SQL:-/usr/local/share/ktp-infra/sql/integrity}"
MYSQL_BIN="${KTP_CORPUS_GUARD_MYSQL:-mysql}"
DB="${KTP_CORPUS_GUARD_DB:-hlstatsx}"
RELAY_CONF="${KTP_CORPUS_GUARD_RELAY:-/etc/ktp/discord-relay.conf}"

# >>> ktp-corpus-guard-streams
# Each entry: <label>:<sql file>:<watermark metric>:<defect metrics, comma separated>
# The metric names are the .sql files' own column aliases -- not restated definitions.
STREAMS=(
  "position:position_corpus_integrity.sql:rows_max_id:epoch_zero_rows,orphan_match_rows"
  "producer_clock:producer_clock_corpus_integrity.sql:rows_max_id:epoch_zero_max_id,orphan_max_id"
)
# <<< ktp-corpus-guard-streams

ts() { date '+%Y-%m-%d %H:%M:%S %Z'; }
log() { printf '[%s] %s\n' "$(ts)" "$*"; }
die() { log "FATAL: $*"; exit "${2:-2}"; }

[ -d "$STATE_DIR" ] || mkdir -p "$STATE_DIR" || die "cannot create $STATE_DIR"
[ -d "$SQL_DIR" ] || die "SQL directory $SQL_DIR does not exist -- the definitions are not installed"
command -v "$MYSQL_BIN" >/dev/null || die "$MYSQL_BIN not on PATH"

# >>> ktp-corpus-guard-metric
# Pull one metric out of mysql's --table output. The files emit a header row and a value
# row per section, so the metric is a COLUMN name and its value sits under it.
# Deliberately tolerant of column order and of extra sections; deliberately NOT tolerant
# of a missing metric, which returns empty and is treated as "could not look".
metric_of() {
    local out="$1" name="$2"
    printf '%s\n' "$out" | awk -v want="$name" '
        /^\|/ {
            n = split($0, cells, /[|]/)
            for (i = 2; i < n; i++) {
                gsub(/^[ \t]+|[ \t]+$/, "", cells[i])
                if (cells[i] == want) { col = i; hdr = NR; next }
            }
            if (col && NR > hdr) {
                n2 = split($0, v, /[|]/)
                gsub(/^[ \t]+|[ \t]+$/, "", v[col])
                if (v[col] ~ /^[0-9]+$/) { print v[col]; exit }
            }
        }'
}
# <<< ktp-corpus-guard-metric

post_alert() {
    local severity="$1" text="$2"
    local routing=/usr/local/bin/ktp-alert-routing.sh
    if [ ! -r "$routing" ] || [ ! -r "$RELAY_CONF" ]; then
        log "WOULD POST ($severity) but routing or relay conf is unavailable: $text"
        return 0
    fi
    # shellcheck source=/dev/null
    . "$RELAY_CONF"; . "$routing"
    ktp_alert_route "$severity" || { log "unknown severity $severity"; return 0; }
    ktp_alert_channel "$KTP_ALERT_LANE" "${ALERT_CHANNEL:-}" || {
        log "no channel for lane $KTP_ALERT_LANE; not guessing one"; return 0; }
    local payload
    payload="$(jq -n --arg ch "$KTP_ALERT_CHANNEL" \
        --arg title "${KTP_ALERT_GLYPH} KTP corpus integrity — $(hostname -s)" \
        --arg desc "$text" --argjson color "$KTP_ALERT_COLOR" \
        '{channelId:$ch, embeds:[{title:$title, description:$desc, color:$color}]}')"
    local http
    http="$(curl -sS -o /dev/null -w '%{http_code}' -X POST "${RELAY_URL:-}" \
        -H "X-Relay-Auth: ${AUTH_SECRET:-}" -H 'Content-Type: application/json' \
        -d "$payload" || echo 000)"
    log "posted ($severity) HTTP $http via lane $KTP_ALERT_LANE"
}

log "corpus-integrity guard starting; state=$STATE_DIR sql=$SQL_DIR"
overall=0
accrued_lines=""

for entry in "${STREAMS[@]}"; do
    IFS=: read -r label file wm_metric defect_metrics <<<"$entry"
    sql="$SQL_DIR/$file"
    [ -r "$sql" ] || die "$sql is not readable -- definition missing for $label"

    wm_file="$STATE_DIR/$label.watermark"
    prev="$(cat "$wm_file" 2>/dev/null || true)"
    case "$prev" in ''|*[!0-9]*) prev=0 ;; esac
    log "$label: scoping to ids above $prev"

    # READ ONLY on the session, and @since_id is the files' own scoping variable.
    out="$("$MYSQL_BIN" --table \
            --init-command="SET SESSION TRANSACTION READ ONLY; SET @since_id := $prev" \
            "$DB" < "$sql" 2>&1)" || {
        log "$label: the read FAILED -- output follows"
        printf '%s\n' "$out"
        post_alert page "Corpus integrity: the \`$label\` read could not run. A read that cannot look is not a clean result."
        exit 2
    }
    printf '%s\n' "$out"

    new_wm="$(metric_of "$out" "$wm_metric")"
    if [ -z "$new_wm" ]; then
        log "$label: metric '$wm_metric' absent from the output -- treating as could-not-look"
        post_alert page "Corpus integrity: \`$label\` ran but emitted no \`$wm_metric\`. The definition changed shape, so the watermark cannot be trusted."
        exit 2
    fi

    # Defect accrual is the only alerting question. Scoped above the watermark, any
    # non-zero means a NEW defective row exists -- not a historical one.
    found=""
    IFS=, read -ra metrics <<<"$defect_metrics"
    for m in "${metrics[@]}"; do
        v="$(metric_of "$out" "$m")"
        [ -n "$v" ] || continue
        if [ "$v" -gt 0 ]; then found="$found $m=$v"; fi
    done

    if [ -n "$found" ]; then
        log "$label: ACCRUAL since id $prev --$found"
        accrued_lines="$accrued_lines"$'\n'"• \`$label\` gained:$found (scoped to ids above $prev)"
        overall=1
    else
        log "$label: no accrual since id $prev"
    fi

    printf '%s\n' "$new_wm" > "$wm_file" || die "cannot write $wm_file"
    log "$label: watermark $prev -> $new_wm"
done

if [ -n "$accrued_lines" ]; then
    post_alert warn "A corpus-integrity defect has ACCRUED — the population was closed since 2026-08-31 and is not any more.${accrued_lines}"
fi

log "corpus-integrity guard done; exit $overall"
exit "$overall"
