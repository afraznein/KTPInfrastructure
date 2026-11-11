#!/bin/bash
# KTP HUD observer archive retention
#
# A HUD replay is only useful while the demo it overlays exists, so this keeps
# the same windows as ktp-demo-retention.sh, tier for tier:
#   ktp, ktpOT                    kept permanently (official matches, by ruling)
#   draft, draftOT               180 days
#   12man, scrim                  30 days
#   player_state.jsonl            30 days, on its own clock, whatever the tier --
#                                 a kept match still loses its player_state
#
# Never touched: a match whose tier has no RETENTION entry (logged as kept),
# a match dir carrying .noprune, a match still open, a match that
# did not come from a fleet game server (LAN boxes included), a match whose type
# cannot be resolved, and a dir holding any file this script does not know.
#
# Match type: metadata.json says 0/0 for every match the recorder auto-started,
# which reads as COMPETITIVE and is usually a pickup. The plugin stamps
# match_type on every event, so a placeholder is typed from its first event.
#
# Age is the events.jsonl mtime. metadata.json is rewritten on reap and on a
# count repair, so its mtime can be days younger than the match.
#
# Modes:
#   delete   (default) remove what is past retention
#   preview            report what falls due in the next PREVIEW_WINDOW_DAYS
#
# Overrides:
#   DRY_RUN=1           list the delete set, remove nothing
#   SKIP_DISCORD=1      suppress Discord posts
#   HUD_MATCHES_DIR=... point at a scratch tree (tests/unit/test_hud_archive_retention.py)
#   FLEET_SOURCE_RE=... extended regex a sourceServer must match to be eligible
#
# Logs: /var/log/ktp-hud-archive-retention.log

set -euo pipefail

HUD_MATCHES_DIR="${HUD_MATCHES_DIR:-/opt/hud-observer/matches}"
FLEET_SOURCE_RE="${FLEET_SOURCE_RE:-^KTP - (Atlanta|Dallas|Denver|New York|Chicago) [0-9]+$}"
PREVIEW_WINDOW_DAYS="${PREVIEW_WINDOW_DAYS:-7}"
PLAYER_STATE_DAYS="${PLAYER_STATE_DAYS:-30}"
DRY_RUN="${DRY_RUN:-0}"
SKIP_DISCORD="${SKIP_DISCORD:-0}"
MODE="${1:-delete}"

# Keyed on the plugin's MatchType enum. A type not listed here is never swept.
declare -A TIER_OF=( [0]=ktp [4]=ktp [3]=draft [5]=draft [2]=12man [1]=scrim )
# A tier absent here is kept forever; ktp is absent because official matches are never retired.
declare -A RETENTION=( [draft]=180 [12man]=30 [scrim]=30 )

KNOWN_FILES_RE='^(events\.jsonl|metadata\.json|player_state\.jsonl)$'

DISCORD_CONF="/etc/ktp/discord-relay.conf"
# shellcheck source=/dev/null
[ -f "$DISCORD_CONF" ] && source "$DISCORD_CONF"
ALERT_CHANNEL="${ALERT_CHANNEL:-1497957091107668070}"
PREVIEW_CHANNEL="${PREVIEW_CHANNEL:-1498813261263405097}"

KTP_EMOJI='<:KTP:1002382703020212245>'
. "$(dirname "${BASH_SOURCE[0]}")/ktp-alert-routing.sh" || {
    echo "FATAL: ktp-alert-routing.sh not found beside $0 — deploy it first" >&2; exit 3; }

ts() { date '+%Y-%m-%d %H:%M:%S'; }

human_bytes() {
    awk -v b="$1" 'BEGIN{
        if (b>=1073741824) printf "%.2f GB", b/1073741824;
        else if (b>=1048576) printf "%.1f MB", b/1048576;
        else if (b>=1024) printf "%.1f KB", b/1024;
        else printf "%d B", b;
    }'
}

# post_discord <severity> <lane> <legacy-channel> <title> <description>
post_discord() {
    local severity="$1" lane="$2" legacy="$3" title="$4" description="$5"
    ktp_alert_route "$severity" "$lane" || return 1
    ktp_alert_channel "$KTP_ALERT_LANE" "$legacy" || return 1
    local full_title="${KTP_EMOJI} ${KTP_ALERT_GLYPH} ${title}"
    local footer_text="KTP Data Server - $(TZ=America/New_York date '+%Y-%m-%d %H:%M %Z')"

    if [ "$SKIP_DISCORD" = "1" ]; then
        echo "[$(ts)] SKIP_DISCORD=1 — would post to $KTP_ALERT_CHANNEL: $full_title"
        return 0
    fi
    if [ -z "${RELAY_URL:-}" ] || [ -z "${AUTH_SECRET:-}" ]; then
        echo "[$(ts)] WARN: RELAY_URL/AUTH_SECRET missing — skipping Discord post" >&2
        return 0
    fi

    local payload http_code
    payload=$(jq -n \
        --arg ch "$KTP_ALERT_CHANNEL" \
        --arg title "$full_title" \
        --arg desc "$description" \
        --arg footer "$footer_text" \
        --argjson color "$KTP_ALERT_COLOR" \
        '{channelId: $ch, embeds: [{title: $title, description: $desc, color: $color, footer: {text: $footer}}]}')
    http_code=$(curl -sS -o /dev/null -w "%{http_code}" \
        -X POST "$RELAY_URL" \
        -H "X-Relay-Auth: $AUTH_SECRET" \
        -H "Content-Type: application/json" \
        -d "$payload" 2>&1) || {
            echo "[$(ts)] WARN: curl failed posting to $KTP_ALERT_CHANNEL" >&2
            return 1
        }
    if [ "$http_code" != "200" ] && [ "$http_code" != "204" ]; then
        echo "[$(ts)] WARN: relay returned HTTP $http_code for $KTP_ALERT_CHANNEL" >&2
        return 1
    fi
}

alert_failure() {
    local desc="$1"
    echo "[$(ts)] ALERT: ${desc}" >&2
    post_discord warn ops-daily "$ALERT_CHANNEL" "HUD Archive Retention — FAILED" "$desc" || true
}

age_days() {
    local now="$1" mtime="$2"
    echo $(( (now - mtime) / 86400 ))
}

# scan: one TSV row per candidate, on stdout.
#   match  <tier> <window_days> <age_days> <bytes> <dir>
#   pstate <tier> <window_days> <age_days> <bytes> <file>
#   skip   <reason> - - - <dir>
# Every mode reads this one list, so what is counted is what is deleted.
scan() {
    local now dir meta fields mtype half state source first_type mtype_resolved tier
    local events stray mtime bytes ps listing name
    now=$(date +%s)
    # find's own failure must surface; an empty listing from a broken find reads as a clean pass.
    listing=$(find "$HUD_MATCHES_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%f\n') || return 1
    while IFS= read -r name; do
        [ -n "$name" ] || continue
        dir="$HUD_MATCHES_DIR/$name"
        if [ -e "$dir/.noprune" ]; then
            printf 'skip\tnoprune\t-\t-\t-\t%s\n' "$dir"; continue
        fi
        meta="$dir/metadata.json"
        events="$dir/events.jsonl"
        if ! fields=$(jq -r '[(.matchType|tostring), (.half|tostring),
                              (if .endedAt == null then "open" else "ended" end),
                              (.sourceServer // "")] | @tsv' "$meta" 2>/dev/null); then
            printf 'skip\tbadmeta\t-\t-\t-\t%s\n' "$dir"; continue
        fi
        IFS=$'\t' read -r mtype half state source <<< "$fields"
        if [ "$state" != "ended" ]; then
            printf 'skip\topen\t-\t-\t-\t%s\n' "$dir"; continue
        fi
        if ! [[ "$source" =~ $FLEET_SOURCE_RE ]]; then
            printf 'skip\tnonfleet\t-\t-\t-\t%s\n' "$dir"; continue
        fi
        stray=$(find "$dir" -mindepth 1 -maxdepth 1 -printf '%f\n' \
                | grep -Ev "$KNOWN_FILES_RE" || true)
        if [ -n "$stray" ]; then
            printf 'skip\tunexpected\t-\t-\t-\t%s\n' "$dir"; continue
        fi

        first_type=""
        if [ -f "$events" ]; then
            first_type=$(head -n 1 "$events" | jq -r '.match_type // empty' 2>/dev/null || true)
        fi
        if [ "$half" != "0" ]; then
            mtype_resolved="$mtype"
            if [ -n "$first_type" ] && [ "$first_type" != "$mtype" ]; then
                printf 'skip\tconflict\t-\t-\t-\t%s\n' "$dir"; continue
            fi
        else
            mtype_resolved="$first_type"
        fi
        tier="${TIER_OF[$mtype_resolved]:-}"
        if [ -z "$mtype_resolved" ] || [ -z "$tier" ]; then
            printf 'skip\tuntyped\t-\t-\t-\t%s\n' "$dir"; continue
        fi

        if [ -z "${RETENTION[$tier]+set}" ]; then
            printf 'skip\tkept\t-\t-\t-\t%s\n' "$dir"
        else
            if [ -f "$events" ]; then
                mtime=$(stat -c %Y "$events")
            else
                mtime=$(stat -c %Y "$meta")
            fi
            bytes=$(find "$dir" -mindepth 1 -maxdepth 1 -type f -printf '%s\n' \
                    | awk '{s+=$1} END{print s+0}')
            printf 'match\t%s\t%s\t%s\t%s\t%s\n' "$tier" "${RETENTION[$tier]}" \
                "$(age_days "$now" "$mtime")" "$bytes" "$dir"
        fi

        ps="$dir/player_state.jsonl"
        if [ -f "$ps" ]; then
            printf 'pstate\tplayer_state\t%s\t%s\t%s\t%s\n' "$PLAYER_STATE_DAYS" \
                "$(age_days "$now" "$(stat -c %Y "$ps")")" "$(stat -c %s "$ps")" "$ps"
        fi
    done <<< "$listing"
}

skip_summary() {
    awk -F'\t' '$1=="skip"{n[$2]++} END{
        out=""; for (k in n) out=out sprintf(" %s=%d", k, n[k]);
        if (out=="") out=" none"; print "skipped:" out
    }'
}

# A dir is removed only if, at the moment of removal, it still holds nothing
# but known files and no .noprune -- the scan is a moment old by then.
remove_match_dir() {
    local dir="$1" f
    [ -e "$dir/.noprune" ] && { echo "[$(ts)] SKIP: .noprune appeared in $dir" >&2; return 0; }
    for f in "$dir"/* "$dir"/.[!.]*; do
        [ -e "$f" ] || continue
        if ! [[ "$(basename "$f")" =~ $KNOWN_FILES_RE ]]; then
            echo "[$(ts)] SKIP: unexpected file in $dir" >&2; return 0
        fi
    done
    rm -f -- "$dir/events.jsonl" "$dir/metadata.json" "$dir/player_state.jsonl" && rmdir -- "$dir"
}

run_delete() {
    [ -d "$HUD_MATCHES_DIR" ] || { echo "[$(ts)] ERROR: matches dir missing: $HUD_MATCHES_DIR" >&2; exit 1; }

    local rows due_matches due_pstate failures=0
    if ! rows=$(scan); then
        alert_failure "\`ktp-hud-archive-retention.sh delete\` -- the scan failed, nothing was swept. See \`/var/log/ktp-hud-archive-retention.log\`."
        return 4
    fi
    due_matches=$(printf '%s\n' "$rows" | awk -F'\t' '$1=="match" && $4>$3')
    # A player_state file inside a match being removed goes with it.
    due_pstate=$(printf '%s\n' "$rows" | awk -F'\t' '
        $1=="match" && $4>$3 {gone[$6]=1}
        $1=="pstate" && $4>$3 {p=$6; sub("/player_state\\.jsonl$","",p); if (!(p in gone)) print}')

    local tier count bytes total_n=0 total_b=0
    for tier in draft 12man scrim; do
        count=$(printf '%s\n' "$due_matches" | awk -F'\t' -v t="$tier" 'NF && $2==t{n++} END{print n+0}')
        bytes=$(printf '%s\n' "$due_matches" | awk -F'\t' -v t="$tier" 'NF && $2==t{s+=$5} END{print s+0}')
        [ "$count" = "0" ] && continue
        if [ "$DRY_RUN" = "1" ]; then
            echo "[$(ts)] DRY_RUN: ${tier} would delete ${count} matches / $(human_bytes "$bytes") (>${RETENTION[$tier]}d)"
        else
            echo "[$(ts)] ${tier} deleting ${count} matches / $(human_bytes "$bytes") (>${RETENTION[$tier]}d)"
        fi
        total_n=$((total_n + count)); total_b=$((total_b + bytes))
    done
    count=$(printf '%s\n' "$due_pstate" | awk -F'\t' 'NF{n++} END{print n+0}')
    bytes=$(printf '%s\n' "$due_pstate" | awk -F'\t' 'NF{s+=$5} END{print s+0}')
    if [ "$count" != "0" ]; then
        if [ "$DRY_RUN" = "1" ]; then
            echo "[$(ts)] DRY_RUN: player_state would delete ${count} files / $(human_bytes "$bytes") (>${PLAYER_STATE_DAYS}d)"
        else
            echo "[$(ts)] player_state deleting ${count} files / $(human_bytes "$bytes") (>${PLAYER_STATE_DAYS}d)"
        fi
    fi

    if [ "$DRY_RUN" != "1" ]; then
        local dir file
        while IFS=$'\t' read -r _ _ _ _ _ dir; do
            [ -n "$dir" ] || continue
            remove_match_dir "$dir" || { echo "[$(ts)] ERROR: could not remove $dir" >&2; failures=$((failures + 1)); }
        done <<< "$due_matches"
        while IFS=$'\t' read -r _ _ _ _ _ file; do
            [ -n "$file" ] || continue
            rm -f -- "$file" || { echo "[$(ts)] ERROR: could not remove $file" >&2; failures=$((failures + 1)); }
        done <<< "$due_pstate"
    fi

    if [ "$total_n" = "0" ]; then
        echo "[$(ts)] delete: no matches past retention"
    else
        echo "[$(ts)] delete: total ${total_n} matches / $(human_bytes "$total_b")"
    fi
    printf '%s\n' "$rows" | skip_summary | sed "s/^/[$(ts)] /"

    if [ "$failures" -ne 0 ]; then
        alert_failure "\`ktp-hud-archive-retention.sh delete\` -- **${failures} removal(s) failed**. See \`/var/log/ktp-hud-archive-retention.log\`."
        return 4
    fi
}

run_preview() {
    [ -d "$HUD_MATCHES_DIR" ] || { echo "[$(ts)] ERROR: matches dir missing: $HUD_MATCHES_DIR" >&2; exit 1; }

    local rows
    if ! rows=$(scan); then
        alert_failure "\`ktp-hud-archive-retention.sh preview\` -- the scan failed. Do not read the silence as an all-clear."
        return 4
    fi
    # Falls due within the window: age in (window_days - PREVIEW_WINDOW_DAYS, window_days].
    local table
    table=$(printf '%s\n' "$rows" | awk -F'\t' -v w="$PREVIEW_WINDOW_DAYS" '
        ($1=="match" || $1=="pstate") && $4>($3-w) && $4<=$3 {n[$2]++; s[$2]+=$5; d[$2]=$3}
        END{for (k in n) printf "%s\t%d\t%d\t%d\n", k, d[k], n[k], s[k]}' | sort)

    if [ -z "$table" ]; then
        echo "[$(ts)] preview: nothing due in the next ${PREVIEW_WINDOW_DAYS}d"
        return 0
    fi
    local desc tier days count bytes
    desc="**HUD replays scheduled for deletion in the next ${PREVIEW_WINDOW_DAYS} days:**"$'\n\n'
    while IFS=$'\t' read -r tier days count bytes; do
        desc+="• \`${tier}\` (${days}d) — ${count} — $(human_bytes "$bytes")"$'\n'
    done <<< "$table"
    desc+=$'\n'"_Drop a \`.noprune\` file into a match's directory under \`${HUD_MATCHES_DIR}\` to keep it._"
    echo "[$(ts)] preview:"
    echo "$desc"
    post_discord info ops-weekly "$PREVIEW_CHANNEL" "HUD Replays — Scheduled for Deletion" "$desc" || true
}

command -v jq >/dev/null || { echo "FATAL: jq is required" >&2; exit 3; }

case "$MODE" in
    delete)  run_delete ;;
    preview) run_preview ;;
    *)       echo "Usage: $0 [delete|preview]" >&2; exit 2 ;;
esac
