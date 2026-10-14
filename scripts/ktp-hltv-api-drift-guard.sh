#!/usr/bin/env bash
# Daily schedule for check-hltv-api-drift.py, which is a tool and not a standing check.
#
# The checker compares the live /home/hltvserver/hltv-api.py against the committed
# reference and exits: 0 identical, 1 drift, 2 a file is missing or unreadable, 3
# redaction failed. It posts nothing and knows nothing about Discord -- deliberately, so
# that what "drift" means stays in one reviewed script. This wrapper adds a schedule, a
# log, and the only thing the checker cannot do for itself: turn those exit codes into an
# alert someone sees.
#
# ⛔ THE CHECKER IS NOT MODIFIED HERE AND MUST NOT BE. Its bytes are pinned to a review,
# and a wrapper that edits its subject is how a reviewed artifact stops being the thing
# that was reviewed.
#
# ⛔ DEPLOY ORDER IS LOAD-BEARING: #708 FIRST, THEN THIS.
# Before #708 the installed checker's only reference default was "beside this script",
# which is never true at /usr/local/bin -- so a BARE run exits 2 on `cannot read`. Install
# this schedule first and you get an exit-2 alert every single morning, which is the noise
# dpl-53ba's own leg warns about. The preflight below refuses in that state rather than
# alerting as though it were drift, but refusing daily is still daily: do not field this
# until a bare run of the installed checker exits 0.
#
# WHAT GOES IN AN ALERT, and this is the part to read before editing:
# ⛔ NEVER the checker's output. On drift it prints a diff of the LIVE hltv-api.py, which
# holds AUTH_KEY. The checker redacts by shape before printing and aborts rather than
# print an unredacted secret -- but exit 3 IS that abort, so the one case where output is
# most tempting to forward is exactly the case where it is least safe. The embed carries
# the verdict, the exit code and where to read the detail; the log on the box carries the
# detail. A Discord channel is not a place to put a diff of a file with a key in it.
#
# ALERTING, same rules as ktp-corpus-integrity-guard and ktp-review-integrity-guard,
# because they are what keep a daily readable:
#   - exit 0 posts NOTHING. A clean run re-posted every morning trains everyone to mute.
#   - exit 1 posts once: drift found, go read the log.
#   - exit 2 ALWAYS posts. "could not look" reading as "nothing there" is the whole defect
#     this row exists to kill, and it is the state the box is in TODAY.
#   - exit 3 posts as a page: redaction failed is a secrets-safety failure, not a drift
#     report.
#
# Exit codes are the checker's own, passed through unchanged, so the log and the state file
# say the same thing the tool said. 2 is also used for a preflight refusal, which is the
# honest code for it: we could not look.
set -uo pipefail

CHECKER="${KTP_DRIFT_CHECKER:-/usr/local/bin/check-hltv-api-drift.py}"
STATE_DIR="${KTP_DRIFT_STATE:-/var/lib/ktp-hltv-api-drift}"
RELAY_CONF="${KTP_DRIFT_RELAY:-/etc/ktp/discord-relay.conf}"
ROUTING="${KTP_DRIFT_ROUTING:-/usr/local/bin/ktp-alert-routing.sh}"

ts() { date '+%Y-%m-%d %H:%M:%S %Z'; }
log() { printf '[%s] %s\n' "$(ts)" "$*"; }

post_alert() {
    local severity="$1" text="$2"
    if [ ! -r "$ROUTING" ] || [ ! -r "$RELAY_CONF" ] || ! command -v jq >/dev/null; then
        log "WOULD POST ($severity) but routing, relay conf or jq is unavailable: $text"
        return 0
    fi
    # shellcheck source=/dev/null
    . "$RELAY_CONF"; . "$ROUTING"
    ktp_alert_route "$severity" || { log "unknown severity $severity"; return 0; }
    ktp_alert_channel "$KTP_ALERT_LANE" "${ALERT_CHANNEL:-}" || {
        log "no channel for lane $KTP_ALERT_LANE; not guessing one"; return 0; }
    local payload http
    payload="$(jq -n --arg ch "$KTP_ALERT_CHANNEL" \
        --arg title "${KTP_ALERT_GLYPH} hltv-api drift — $(hostname -s)" \
        --arg desc "$text" --argjson color "$KTP_ALERT_COLOR" \
        '{channelId:$ch, embeds:[{title:$title, description:$desc, color:$color}]}')"
    http="$(curl -sS -o /dev/null -w '%{http_code}' -X POST "${RELAY_URL:-}" \
        -H "X-Relay-Auth: ${AUTH_SECRET:-}" -H 'Content-Type: application/json' \
        -d "$payload" || echo 000)"
    log "posted ($severity) HTTP $http via lane $KTP_ALERT_LANE"
}

record() {  # <exit code> -- a durable one-line state, independent of the log's tail
    [ -d "$STATE_DIR" ] || mkdir -p "$STATE_DIR" || { log "cannot create $STATE_DIR"; return 0; }
    printf '%s %s\n' "$(date +%s)" "$1" > "$STATE_DIR/last" || log "cannot write $STATE_DIR/last"
}

log "hltv-api drift check starting; checker=$CHECKER"

# >>> ktp-hltv-api-drift-preflight
# The checker must be there and runnable. A missing checker is "could not look", not "no
# drift" -- the distinction this whole row is about.
if [ ! -x "$CHECKER" ]; then
    log "FATAL: $CHECKER is not executable"
    post_alert page "The drift checker is missing or not executable at \`$CHECKER\`, so nothing was compared. This is not a clean result."
    record 2
    exit 2
fi
# <<< ktp-hltv-api-drift-preflight

out="$($CHECKER 2>&1)"; rc=$?
printf '%s\n' "$out"
record "$rc"

# >>> ktp-hltv-api-drift-verdict
case "$rc" in
    0)
        # Silent on purpose. The log line above is the record that it looked.
        log "no drift; posting nothing"
        ;;
    1)
        log "DRIFT found (exit 1)"
        # ⛔ The verdict, never the diff: $out contains a diff of the live hltv-api.py.
        post_alert warn "\`hltv-api.py\` has DRIFTED from its committed reference (checker exit 1). ⛔ The diff is deliberately not reproduced here — it is a diff of a file holding \`AUTH_KEY\`. Read it on the box: \`/var/log/ktp-hltv-api-drift.log\`, or re-run \`$CHECKER\`."
        ;;
    2)
        log "COULD NOT LOOK (exit 2)"
        # Names both causes rather than guessing, because one of them is a fielding
        # mistake we can make and the other is a real missing file.
        post_alert page "The drift check **could not look** (checker exit 2) — a file it needs is missing or unreadable, so today has NO drift answer either way. Two causes, and it cannot tell them apart: the live file or the reference is genuinely absent, or the installed checker predates \`#708\` and cannot resolve a reference at all, in which case this schedule was fielded too early. Check with a bare run of \`$CHECKER\`."
        ;;
    3)
        log "REDACTION FAILED (exit 3)"
        # ⛔ No output at all here: exit 3 means the checker could not prove it had
        # redacted, so its buffer is the last thing to forward anywhere.
        post_alert page "The drift check aborted because **redaction failed** (checker exit 3). It refused to print rather than risk emitting a secret, and its output is deliberately not reproduced here for the same reason. This is a secrets-safety failure, not a drift report — investigate on the box before re-running."
        ;;
    *)
        log "UNEXPECTED exit $rc"
        post_alert page "The drift check exited **$rc**, which is not one of its documented codes (0 identical, 1 drift, 2 could not look, 3 redaction failed). Treat as no answer."
        ;;
esac
# <<< ktp-hltv-api-drift-verdict

log "hltv-api drift check done; exit $rc"
exit "$rc"
