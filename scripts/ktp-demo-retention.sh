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
#
# Logs: /var/log/ktp-demo-retention.log
# Archive browser: https://fastdl.ktpdod.com/demos/

set -euo pipefail

DEMO_ROOT="/home/hltvserver/hlds/dod/demos"

# Directories carrying a .noprune marker are NEVER swept, whatever they are called.
# The LAN-* pattern below is kept for belt-and-braces, but a marker file survives a
# folder rename -- a path pattern does not, and losing it would be silent.
PRUNE_EXCLUDES=()
while IFS= read -r marker; do
    PRUNE_EXCLUDES+=( -not -path "$(dirname "$marker")/*" )
done < <(find "$DEMO_ROOT" -name .noprune -type f 2>/dev/null)
PRUNE_EXCLUDES_STR="${PRUNE_EXCLUDES[*]}"

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

# count_and_size <subdir> <min_age_days> <max_age_days_inclusive_plus_1>
# Returns "count<TAB>bytes" on stdout.
count_and_size() {
    local subdir="$1" min="$2" maxexc="$3"
    local filter_cmd="find \"$DEMO_ROOT\" -path \"*/${subdir}/*.dem\" -not -path \"*/LAN-*/*\" $PRUNE_EXCLUDES_STR -type f -mtime \"+${min}\""
    if [ -n "$maxexc" ]; then
        filter_cmd="$filter_cmd -mtime \"-${maxexc}\""
    fi
    local count bytes
    count=$(eval "$filter_cmd" 2>/dev/null | wc -l)
    bytes=$(eval "$filter_cmd -printf '%s\\n'" 2>/dev/null \
            | awk 'BEGIN{s=0} {s+=$1} END{print s+0}')
    printf '%s\t%s\n' "$count" "$bytes"
}

oldest_mtime() {
    local subdir="$1" min="$2" maxexc="$3"
    local filter_cmd="find \"$DEMO_ROOT\" -path \"*/${subdir}/*.dem\" -not -path \"*/LAN-*/*\" $PRUNE_EXCLUDES_STR -type f -mtime \"+${min}\""
    if [ -n "$maxexc" ]; then
        filter_cmd="$filter_cmd -mtime \"-${maxexc}\""
    fi
    eval "$filter_cmd -printf '%TY-%Tm-%Td\\n'" 2>/dev/null | sort -u | head -1
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

# ---- delete mode ----
run_delete() {
    [ -d "$DEMO_ROOT" ] || { echo "[$(ts)] ERROR: demo root missing" >&2; exit 1; }

    local total_deleted=0 total_bytes=0
    for subdir in "${!RETENTION[@]}"; do
        local days=${RETENTION[$subdir]}
        local result count bytes gb
        result=$(count_and_size "$subdir" "$days" "")
        count="${result%$'\t'*}"
        bytes="${result#*$'\t'}"
        [ "$count" = "0" ] && continue

        gb=$(human_bytes "$bytes")
        if [ "$DRY_RUN" = "1" ]; then
            echo "[$(ts)] DRY_RUN: ${subdir}/ would delete ${count} files / ${gb} (>${days}d)"
        else
            echo "[$(ts)] ${subdir}/ deleting ${count} files / ${gb} (>${days}d)"
            find "$DEMO_ROOT" -path "*/${subdir}/*.dem" -not -path "*/LAN-*/*" "${PRUNE_EXCLUDES[@]}" -type f -mtime "+${days}" -delete
        fi
        total_deleted=$((total_deleted + count))
        total_bytes=$((total_bytes + bytes))
    done

    if [ "$total_deleted" = "0" ]; then
        echo "[$(ts)] delete: nothing past retention"
    else
        local total_gb
        total_gb=$(human_bytes "$total_bytes")
        echo "[$(ts)] delete: total ${total_deleted} files / ${total_gb}"
    fi
}

# ---- preview mode (Sunday lookahead) ----
run_preview() {
    [ -d "$DEMO_ROOT" ] || { echo "[$(ts)] ERROR: demo root missing" >&2; exit 1; }

    # Collect per-tier stats for files due for deletion in the next PREVIEW_WINDOW_DAYS.
    # For subdir retention=D, age range is (D - window, D]  =>  find -mtime +(D-window-1) -mtime -(D+1)
    local any=0
    local -a rows=()

    for subdir in ktp draft 12man scrim; do
        local days=${RETENTION[$subdir]}
        local warn_min=$((days - PREVIEW_WINDOW_DAYS - 1))
        local warn_maxexc=$((days + 1))
        local result count bytes oldest
        result=$(count_and_size "$subdir" "$warn_min" "$warn_maxexc")
        count="${result%$'\t'*}"
        bytes="${result#*$'\t'}"
        [ "$count" = "0" ] && continue

        any=1
        oldest=$(oldest_mtime "$subdir" "$warn_min" "$warn_maxexc")
        local size_str
        size_str=$(human_bytes "$bytes")
        rows+=("\`${subdir}\` (${days}d) — ${count} files / ${size_str} — oldest ${oldest}")
    done

    if [ "$any" = "0" ]; then
        echo "[$(ts)] preview: no demos due for deletion in next ${PREVIEW_WINDOW_DAYS}d"
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
}

case "$MODE" in
    delete)  run_delete ;;
    preview) run_preview ;;
    *)       echo "Usage: $0 [delete|preview]" >&2; exit 2 ;;
esac