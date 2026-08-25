#!/bin/bash
# KTP HLTV Demo Retention
#
# Tiered retention per match-type:
#   ktp/     180 days   (league matches — long archive)
#   draft/   180 days   (draft matches — long archive)
#   12man/    90 days   (pickup games — shorter)
#   scrim/    90 days   (scrims — shorter)
#
# Modes:
#   delete   (default) — delete .dem files past their per-type retention
#   preview            — post Discord heads-up for demos scheduled for deletion
#                        in the next 7 days (both KTP + 1.3 Community channels)
#
# Schedule (via /etc/cron.d/ktp-demo-retention):
#   30 4 * * *   delete   (daily at 04:30 ET)
#   0 9 * * 0    preview  (Sunday at 09:00 ET)
#
# Overrides (ad-hoc):
#   DRY_RUN=1           list deletions without performing them
#   SKIP_DISCORD=1      suppress Discord posts
#   ARCHIVE_URL=...     override archive URL shown in preview
#   DEMO_ROOT=...       point at a scratch tree (tests/unit/test_demo_retention.py)
#
# Logs: /var/log/ktp-demo-retention.log
# Archive browser: https://fastdl.ktpdod.com/demos/

set -euo pipefail

DEMO_ROOT="${DEMO_ROOT:-/home/hltvserver/hlds/dod/demos}"

# Directories carrying a .noprune marker are NEVER swept, whatever they are called.
# The LAN-* pattern below is kept for belt-and-braces, but a marker file survives a
# folder rename -- a path pattern does not, and losing it would be silent.
PRUNE_EXCLUDES=()
while IFS= read -r marker; do
    PRUNE_EXCLUDES+=( -not -path "$(dirname "$marker")/*" )
done < <(find "$DEMO_ROOT" -name .noprune -type f 2>/dev/null)

PREVIEW_WINDOW_DAYS="${PREVIEW_WINDOW_DAYS:-7}"
DRY_RUN="${DRY_RUN:-0}"
SKIP_DISCORD="${SKIP_DISCORD:-0}"
ARCHIVE_URL="${ARCHIVE_URL:-https://fastdl.ktpdod.com/demos/}"
MODE="${1:-delete}"

# Event archives under demos/LAN-*/ are EXCLUDED from retention. They are
# irreplaceable one-off recordings that happen to use the same ktp/draft/12man/
# scrim subdir names, so the per-subdir patterns below match them by accident.
# Without this guard the Philly 2026 set would vanish from the web tree at the
# 90/180-day marks with no warning.
# Per-subdir retention (days). Anything not listed here is NOT touched —
# intentionally conservative: a new match-type must be explicitly enrolled.
declare -A RETENTION=(
    [ktp]=180
    [draft]=180
    [12man]=90
    [scrim]=90
)

# Discord channels for preview alerts
DISCORD_CONF="/etc/ktp/discord-relay.conf"
# shellcheck source=/dev/null
[ -f "$DISCORD_CONF" ] && source "$DISCORD_CONF"
DEMO_CHANNEL_KTP="${DEMO_CHANNEL_KTP:-1081255192529477744}"
DEMO_CHANNEL_COMMUNITY="${DEMO_CHANNEL_COMMUNITY:-1092158706399064067}"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

human_bytes() {
    awk -v b="$1" 'BEGIN{
        if (b>=1073741824) printf "%.2f GB", b/1073741824;
        else if (b>=1048576) printf "%.1f MB", b/1048576;
        else if (b>=1024) printf "%.1f KB", b/1024;
        else printf "%d B", b;
    }'
}

# Assembles one tier's find arguments into FIND_ARGV. Every consumer -- count,
# preview and the delete pass itself -- goes through here, so the set that gets
# counted is by construction the set that gets deleted.
# Never flatten the excludes into a string: unquoted, the trailing /* glob-expands
# and find dies with "paths must precede expression".
build_find_argv() {
    local subdir="$1" min="$2" maxexc="$3"
    FIND_ARGV=( "$DEMO_ROOT" -path "*/${subdir}/*.dem" -not -path "*/LAN-*/*"
                "${PRUNE_EXCLUDES[@]}" -type f -mtime "+${min}" )
    [ -n "$maxexc" ] && FIND_ARGV+=( -mtime "-${maxexc}" )
    return 0
}

# find_matches <subdir> <min_age_days> <max_age_days_inclusive_plus_1>
# Emits "<bytes>\t<YYYY-MM-DD>\t<path>" per match; returns 1 if find itself failed.
# find's stderr is deliberately NOT discarded -- swallowing it is what let a broken
# filter read as an empty result for ten days.
find_matches() {
    build_find_argv "$1" "$2" "$3"
    local out rc=0
    out=$(find "${FIND_ARGV[@]}" -printf '%s\t%TY-%Tm-%Td\t%p\n') || rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "[$(ts)] ERROR: find exited ${rc} for tier '${1}' -- tier SKIPPED, retention NOT applied" >&2
        return 1
    fi
    [ -n "$out" ] && printf '%s\n' "$out"
    return 0
}

# count_and_size <subdir> <min_age_days> <max_age_days_inclusive_plus_1>
# Returns "count<TAB>bytes" on stdout; returns 1 if the underlying find failed.
count_and_size() {
    local matches
    matches=$(find_matches "$@") || return 1
    printf '%s\n' "$matches" \
        | awk -F'\t' 'BEGIN{n=0;s=0} NF{n++;s+=$1} END{printf "%d\t%d\n", n, s+0}'
}

oldest_mtime() {
    local matches
    matches=$(find_matches "$@") || return 1
    # ISO dates, so lexicographic min is chronological min -- and no sort|head
    # pipeline to raise SIGPIPE under pipefail.
    printf '%s\n' "$matches" \
        | awk -F'\t' 'NF && (m=="" || $2<m){m=$2} END{if(m!="")print m}'
}

# KTP Discord embed constants (match plugins/include/ktp_discord.inc)
KTP_EMOJI='<:KTP:1002382703020212245>'
KTP_COLOR_RED=16711680
KTP_COLOR_ORANGE=16750848
KTP_COLOR_GREEN=65280
KTP_COLOR_BLUE=3447003

# post_discord <channel_id> <title-without-emoji> <description> <color>
# Matches the standard KTP embed format used by plugins + hltv-restart-all.sh:
#   - Prepends the KTP emoji to the title
#   - Auth via X-Relay-Auth header (not payload field)
#   - Footer: "KTP Data Server - YYYY-MM-DD HH:MM ET"
post_discord() {
    local channel="$1" title="$2" description="$3" color="${4:-$KTP_COLOR_ORANGE}"
    local full_title="${KTP_EMOJI} ${title}"
    local footer_text="KTP Data Server - $(TZ=America/New_York date '+%Y-%m-%d %H:%M %Z')"

    if [ "$SKIP_DISCORD" = "1" ]; then
        echo "[$(ts)] SKIP_DISCORD=1 — would post to $channel: $full_title"
        return 0
    fi
    if [ -z "${RELAY_URL:-}" ] || [ -z "${AUTH_SECRET:-}" ]; then
        echo "[$(ts)] WARN: RELAY_URL/AUTH_SECRET missing — skipping Discord post" >&2
        return 0
    fi

    local payload
    payload=$(jq -n \
        --arg ch "$channel" \
        --arg title "$full_title" \
        --arg desc "$description" \
        --arg footer "$footer_text" \
        --argjson color "$color" \
        '{channelId: $ch, embeds: [{title: $title, description: $desc, color: $color, footer: {text: $footer}}]}')

    local http_code
    http_code=$(curl -sS -o /tmp/ktp-demo-retention-resp.txt -w "%{http_code}" \
        -X POST "$RELAY_URL" \
        -H "X-Relay-Auth: $AUTH_SECRET" \
        -H "Content-Type: application/json" \
        -d "$payload" 2>&1) || {
            echo "[$(ts)] WARN: curl failed posting to $channel" >&2
            return 1
        }
    if [ "$http_code" != "200" ] && [ "$http_code" != "204" ]; then
        echo "[$(ts)] WARN: relay returned HTTP $http_code for $channel: $(cat /tmp/ktp-demo-retention-resp.txt 2>/dev/null)" >&2
        return 1
    fi
}

# A pass that errors and then reports zero is indistinguishable from a healthy one --
# that is exactly how this job ran for ten days. Route failures somewhere a human looks.
alert_failure() {
    local desc="$1"
    echo "[$(ts)] ALERT: ${desc}" >&2
    post_discord "$DEMO_CHANNEL_KTP" "HLTV Demo Retention — FAILED" "$desc" "$KTP_COLOR_RED" || true
}

# ---- delete mode ----
run_delete() {
    [ -d "$DEMO_ROOT" ] || { echo "[$(ts)] ERROR: demo root missing" >&2; exit 1; }

    local total_deleted=0 total_bytes=0 failures=0
    for subdir in "${!RETENTION[@]}"; do
        local days=${RETENTION[$subdir]}
        local matches count bytes gb
        if ! matches=$(find_matches "$subdir" "$days" ""); then
            failures=$((failures + 1))
            continue
        fi
        count=$(printf '%s\n' "$matches" | awk -F'\t' 'BEGIN{n=0} NF{n++} END{print n}')
        bytes=$(printf '%s\n' "$matches" | awk -F'\t' 'BEGIN{s=0} NF{s+=$1} END{print s+0}')
        [ "$count" = "0" ] && continue

        # The excludes are the only thing between this job and the irreplaceable event
        # archives. Assert on the resulting set, not on the argv that produced it.
        if printf '%s\n' "$matches" | grep -q '/LAN-'; then
            echo "[$(ts)] FATAL: event-archive path in the ${subdir}/ delete set -- aborting, nothing deleted" >&2
            alert_failure "Event-archive path reached the delete set for \`${subdir}/\`. Retention **aborted with nothing deleted** -- inspect before re-running."
            exit 3
        fi

        gb=$(human_bytes "$bytes")
        if [ "$DRY_RUN" = "1" ]; then
            echo "[$(ts)] DRY_RUN: ${subdir}/ would delete ${count} files / ${gb} (>${days}d)"
        else
            echo "[$(ts)] ${subdir}/ deleting ${count} files / ${gb} (>${days}d)"
            build_find_argv "$subdir" "$days" ""
            if ! find "${FIND_ARGV[@]}" -delete; then
                echo "[$(ts)] ERROR: delete pass failed for ${subdir}/" >&2
                failures=$((failures + 1))
            fi
        fi
        total_deleted=$((total_deleted + count))
        total_bytes=$((total_bytes + bytes))
    done

    if [ "$total_deleted" = "0" ]; then
        if [ "$failures" -eq 0 ]; then
            echo "[$(ts)] delete: nothing past retention"
        else
            echo "[$(ts)] delete: 0 files, but ${failures} tier(s) ERRORED -- this is not a clean pass" >&2
        fi
    else
        local total_gb
        total_gb=$(human_bytes "$total_bytes")
        echo "[$(ts)] delete: total ${total_deleted} files / ${total_gb}"
    fi

    if [ "$failures" -ne 0 ]; then
        alert_failure "\`ktp-demo-retention.sh delete\` -- **${failures} tier(s) failed to evaluate**, so those demos were not swept. See \`/var/log/ktp-demo-retention.log\`."
        return 4
    fi
}

# ---- preview mode (Sunday lookahead) ----
run_preview() {
    [ -d "$DEMO_ROOT" ] || { echo "[$(ts)] ERROR: demo root missing" >&2; exit 1; }

    # Collect per-tier stats for files due for deletion in the next PREVIEW_WINDOW_DAYS.
    # For subdir retention=D, age range is (D - window, D]  =>  find -mtime +(D-window-1) -mtime -(D+1)
    local any=0 failures=0
    local -a rows=()

    for subdir in ktp draft 12man scrim; do
        local days=${RETENTION[$subdir]}
        local warn_min=$((days - PREVIEW_WINDOW_DAYS - 1))
        local warn_maxexc=$((days + 1))
        local result count bytes oldest
        if ! result=$(count_and_size "$subdir" "$warn_min" "$warn_maxexc"); then
            failures=$((failures + 1))
            continue
        fi
        count="${result%$'\t'*}"
        bytes="${result#*$'\t'}"
        [ "$count" = "0" ] && continue

        any=1
        oldest=$(oldest_mtime "$subdir" "$warn_min" "$warn_maxexc" || true)
        local size_str
        size_str=$(human_bytes "$bytes")
        rows+=("\`${subdir}\` (${days}d) — ${count} files / ${size_str} — oldest ${oldest}")
    done

    if [ "$failures" -ne 0 ]; then
        alert_failure "\`ktp-demo-retention.sh preview\` -- **${failures} tier(s) failed to evaluate**. The weekly heads-up is incomplete; do not read it as an all-clear."
    fi

    if [ "$any" = "0" ]; then
        if [ "$failures" -eq 0 ]; then
            echo "[$(ts)] preview: no demos due for deletion in next ${PREVIEW_WINDOW_DAYS}d"
        else
            echo "[$(ts)] preview: 0 tiers reported, but ${failures} ERRORED -- not an all-clear" >&2
            return 4
        fi
        return 0
    fi

    local desc
    desc="**Demos scheduled for deletion in the next ${PREVIEW_WINDOW_DAYS} days:**"$'\n\n'
    for r in "${rows[@]}"; do
        desc+="• ${r}"$'\n'
    done
    desc+=$'\n'"**Archive browser:** ${ARCHIVE_URL}"$'\n\n'
    desc+="_To preserve a demo, download it from the archive before the daily 04:30 ET cleanup._"

    echo "[$(ts)] preview: posting to KTP + 1.3 Community"
    echo "$desc"
    post_discord "$DEMO_CHANNEL_KTP"       "HLTV Demos — Scheduled for Deletion" "$desc" "$KTP_COLOR_ORANGE"
    post_discord "$DEMO_CHANNEL_COMMUNITY" "HLTV Demos — Scheduled for Deletion" "$desc" "$KTP_COLOR_ORANGE"

    [ "$failures" -eq 0 ] || return 4
}

case "$MODE" in
    delete)  run_delete ;;
    preview) run_preview ;;
    *)       echo "Usage: $0 [delete|preview]" >&2; exit 2 ;;
esac
