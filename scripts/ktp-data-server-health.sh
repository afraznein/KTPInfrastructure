#!/bin/bash
# KTP Data Server Health Check
#
# Monitors critical services + timers + HLTV instance coverage. Alerts to
# Discord ONLY on state transitions (service goes down → alert; service
# recovers → alert "restored"; persistent-down → silent, no chat spam).
#
# Schedule: hourly via /etc/cron.d/ktp-data-server-health. Issues here are
# background services whose failures aren't player-visible, so a 10-minute
# window felt like overkill.
#
# State file: /var/lib/ktp-data-server-health.json
# Log:        /var/log/ktp-data-server-health.log
# Discord:    sources /etc/ktp/discord-relay.conf (RELAY_URL + AUTH_SECRET)

set -euo pipefail

STATE_FILE=/var/lib/ktp-data-server-health.json
# #ktp-crashes — consolidated with perf-rollup (PERF_ALERT_CHANNEL in
# /etc/ktp/discord-relay.conf, same channel) per operator decision
# 2026-05-06. Health alerts are crash-class signals (services dying);
# routing them alongside crashes keeps the operational signal in one
# place. Reverses the May 3 "dedicated #ktp-data-server-health" split.
# Override via ALERT_CHANNEL env var if a different routing is needed.
ALERT_CHANNEL="${ALERT_CHANNEL:-1497957091107668070}"
# HLTV port range mirrors game ports: 27020=ATL1, 27021=ATL2, ... 27044=CHI5
HLTV_PORT_START=27020
HLTV_PORT_END=27044
# Intentionally excluded (e.g. hltv@27044 was disabled 2026-04-10 when the
# upstream Chicago 27019 game server was taken offline for the 4-server trial).
# Add a port here if the corresponding game server is disabled on purpose.
HLTV_EXCLUDED_PORTS=(27044)

# Critical services that must be active (systemctl is-active == "active")
CRITICAL_SERVICES=(
    mysql.service
    nginx.service
    hlstatsx.service
    hltv-api.service
    ktp-ac-api.service
    ktp-file-distributor.service
    # A dead renamer silently loses league demos to the 6h auto-cleanup sweep
    # (unrenamed auto-*.dem get purged) — it MUST page promptly.
    hltv-demo-renamer.service
    # A dead aggregator silently suppresses the whole perf-alert tier
    # (perf-rollup exits quietly on an empty day).
    ktp-profile-aggregator.service
)

# Timers that must be enabled + scheduled
CRITICAL_TIMERS=(
    hltv-restart.timer
    # Renders the central ban list into the distribute tree. A stopped timer is
    # silent: the last-published file stays in place and reads as healthy.
    ktp-render-banlist.timer
    # Files renamed demos into the published tree and rebuilds the archive
    # pages. Stopped, it is silent: the site keeps serving yesterday's index.
    ktp-demo-publish.timer
)

# Central ban-list renderer. Checked on three independent legs because each one
# hides the others: the file can be absent, the timer can have stopped, or it can
# be running every minute and failing — the 2026-08-12 case, whose exit timestamp
# stays fresh, so staleness alone misses it.
# Renamer LIVENESS, which is-active cannot answer. The unit is already in
# CRITICAL_SERVICES precisely to stop demo loss, yet on 2026-08-25 it wedged on
# a half-open SSH session and sat "active" for 53h while every match demo in the
# window went unrenamed and was purged by the auto-cleanup. A hung process is
# active. The poll loop rewrites state.json once per 30s cycle, so that file's
# mtime is the cheapest true "work happened" signal available.
RENAMER_STATE_FILE=/var/lib/hltv-demo-renamer/state.json
RENAMER_STALE_SEC=900

BANLIST_FILE="/home/dod/distribute/addons/ktpamx/configs/ktp_ac_bans.ini"
BANLIST_UNIT="ktp-render-banlist.service"
BANLIST_STALE_SEC=900

[ -f /etc/ktp/discord-relay.conf ] && source /etc/ktp/discord-relay.conf

ts() { date '+%Y-%m-%d %H:%M:%S'; }

# ---- Collect current "down" set ----
down=()

for svc in "${CRITICAL_SERVICES[@]}"; do
    state=$(systemctl is-active "$svc" 2>/dev/null || true)
    if [ "$state" != "active" ]; then
        down+=("$svc=$state")
    fi
done

for t in "${CRITICAL_TIMERS[@]}"; do
    state=$(systemctl is-active "$t" 2>/dev/null || true)
    enabled=$(systemctl is-enabled "$t" 2>/dev/null || true)
    if [ "$state" != "active" ] || [ "$enabled" != "enabled" ]; then
        down+=("$t=${state}/${enabled}")
    fi
done

# Keyed on the UNIT's last exit, never on the file's mtime or the renderer's log.
# Both of those go permanently quiet once the list stops changing — which is the
# healthy steady state — so either would read as `stale` forever and get tuned out.
banlist_load=$(systemctl show "$BANLIST_UNIT" -p LoadState --value 2>/dev/null || true)
if [ "$banlist_load" != "loaded" ]; then
    # A nonexistent unit answers Result=success and exits 0, so a Result-only
    # check calls a typo healthy. LoadState is the mandatory guard.
    down+=("$BANLIST_UNIT=not-loaded")
else
    banlist_result=$(systemctl show "$BANLIST_UNIT" -p Result --value 2>/dev/null || true)
    if [ "$banlist_result" != "success" ]; then
        down+=("$BANLIST_UNIT=render-failed")
    fi
    banlist_last=$(systemctl show "$BANLIST_UNIT" -p ExecMainExitTimestamp --value 2>/dev/null || true)
    if [ -z "$banlist_last" ]; then
        # `date -d ''` SUCCEEDS, returning midnight today, so an empty timestamp
        # must be caught here rather than handed to date.
        down+=("$BANLIST_UNIT=never-ran")
    else
        banlist_epoch=$(date -d "$banlist_last" +%s 2>/dev/null || echo 0)
        if [ "$banlist_epoch" -eq 0 ] || \
           [ $(( $(date +%s) - banlist_epoch )) -gt "$BANLIST_STALE_SEC" ]; then
            down+=("$BANLIST_UNIT=stale")
        fi
    fi
fi
# Tokens above are fixed strings, never an age — the report is a set-diff against
# the previous run, so a ticking value would look like a new failure every hour.
if [ ! -f "$BANLIST_FILE" ]; then
    down+=("ktp_ac_bans.ini=absent")
fi

# Renamer liveness. Only meaningful while the unit is up — a stopped unit is
# already reported by CRITICAL_SERVICES, and both legs firing would double-count
# one fault as two set members.
if [ "$(systemctl is-active hltv-demo-renamer.service 2>/dev/null || true)" = "active" ]; then
    if [ ! -f "$RENAMER_STATE_FILE" ]; then
        down+=("hltv-demo-renamer-state=absent")
    else
        renamer_epoch=$(stat -c %Y "$RENAMER_STATE_FILE" 2>/dev/null || echo 0)
        if [ "$renamer_epoch" -eq 0 ] ||            [ $(( $(date +%s) - renamer_epoch )) -gt "$RENAMER_STALE_SEC" ]; then
            # Fixed token, never the age: the report is a set-diff, so a ticking
            # value would read as a fresh failure on every hourly run.
            down+=("hltv-demo-renamer=wedged")
        fi
    fi
fi

# HLTV instance coverage — check each port in the expected set,
# skipping intentionally-excluded ones.
is_excluded() {
    local p="$1"
    for ex in "${HLTV_EXCLUDED_PORTS[@]}"; do
        [ "$ex" = "$p" ] && return 0
    done
    return 1
}
expected_hltv=0
active_hltv=0
missing_hltv=()
for p in $(seq "$HLTV_PORT_START" "$HLTV_PORT_END"); do
    if is_excluded "$p"; then continue; fi
    expected_hltv=$((expected_hltv + 1))
    state=$(systemctl is-active "hltv@$p" 2>/dev/null || true)
    if [ "$state" = "active" ]; then
        active_hltv=$((active_hltv + 1))
    else
        missing_hltv+=("hltv@$p=$state")
    fi
done
if [ "$active_hltv" -lt "$expected_hltv" ]; then
    down+=("hltv-instance-count=${active_hltv}/${expected_hltv}")
    # Also list which specific instance(s) are down so the alert is actionable
    for m in "${missing_hltv[@]}"; do
        down+=("$m")
    done
fi

# ---- Disk usage + growth ----
# No df history existed anywhere on this box (sysstat is installed but its
# collector never ran), so the 2026-07-30 syslog runaway was reconstructed from
# file mtimes. 49% used trips no ceiling — the 24h rate is what catches it.
DISK_HISTORY="${DISK_HISTORY:-/var/log/ktp-disk-history.log}"
DISK_PCT_WARN="${DISK_PCT_WARN:-75}"
DISK_GROWTH_WARN_GIB="${DISK_GROWTH_WARN_GIB:-3}"
# Extrapolating GiB/day from a 1h window turns every transient into an alert.
DISK_GROWTH_MIN_HOURS="${DISK_GROWTH_MIN_HOURS:-12}"

now_epoch=$(date +%s)
now_ts=$(ts)

if [ ! -e "$DISK_HISTORY" ]; then
    install -m 0640 -o root -g root /dev/null "$DISK_HISTORY" 2>/dev/null || true
fi

# delaycompress in the rotate stanza keeps .1 plain text, so the 24h lookback
# still resolves on the day after a rotation.
disk_history() { cat "$DISK_HISTORY" "$DISK_HISTORY.1" 2>/dev/null || true; }

# Bucket reported values — an unbucketed "78%" ticking to "79%" reads to the
# set comparison below as one recovery plus one new failure, i.e. hourly spam.
bucket5() { echo $(( ${1:-0} / 5 * 5 )); }
bucket_gib() {
    local b=0 t
    for t in 3 5 10 20 40 80 160 320; do
        if [ "${1:-0}" -ge "$t" ]; then b=$t; fi
    done
    echo "$b"
}

growth_cutoff=$(( now_epoch - DISK_GROWTH_MIN_HOURS * 3600 ))
# -k so the arithmetic stays integer KiB; pseudo-filesystems carry no trend.
inode_rows=$(df -P -i -x tmpfs -x devtmpfs -x squashfs -x overlay 2>/dev/null | tail -n +2 || true)
disk_rows=$(df -P -k -x tmpfs -x devtmpfs -x squashfs -x overlay 2>/dev/null | tail -n +2 || true)

while read -r fs size used avail pct mount; do
    if [ -z "${mount:-}" ]; then continue; fi
    pct=${pct%\%}
    ipct=$(printf '%s\n' "$inode_rows" | awk -v m="$mount" '$6==m {gsub(/%/,"",$5); print $5; exit}')
    printf '%s|%s|DF|%s|%s|%s|%s|%s|%s|%s\n' \
        "$now_ts" "$now_epoch" "$fs" "$mount" "$size" "$used" "$avail" "$pct" "${ipct:-0}" \
        >> "$DISK_HISTORY" || true

    rate=""
    base=$(disk_history | awk -F'|' -v m="$mount" -v c="$growth_cutoff" \
        '$3=="DF" && $5==m && ($2+0)<=c && ($2+0)>best {best=$2+0; u=$7+0}
         END {if (best>0) print best" "u}' || true)
    if [ -n "$base" ]; then
        base_epoch=${base% *}
        base_used=${base#* }
        span=$(( now_epoch - base_epoch ))
        if [ "$span" -gt 0 ]; then
            rate=$(( (used - base_used) * 86400 / span / 1048576 ))
        fi
    fi

    echo "[$now_ts] disk $mount ${pct}% used, inodes ${ipct:-?}%, 24h rate ${rate:-n/a} GiB/day"

    case "$pct" in
        ''|*[!0-9]*) ;;
        *) if [ "$pct" -ge "$DISK_PCT_WARN" ]; then
               down+=("disk-usage:${mount}=$(bucket5 "$pct")%+")
           fi ;;
    esac
    case "${ipct:-}" in
        ''|*[!0-9]*) ;;
        *) if [ "$ipct" -ge "$DISK_PCT_WARN" ]; then
               down+=("disk-inodes:${mount}=$(bucket5 "$ipct")%+")
           fi ;;
    esac
    if [ -n "$rate" ] && [ "$rate" -ge "$DISK_GROWTH_WARN_GIB" ]; then
        down+=("disk-growth:${mount}=$(bucket_gib "$rate")GiB/day+")
    fi
done <<< "$disk_rows"

# Largest entries directly under /var/log. -a so single runaway FILES are
# caught (the incident was syslog itself, which no directory listing shows);
# timeout so a slow walk can never wedge the service checks above.
log_top=$(timeout 60 du -kax --max-depth=1 /var/log 2>/dev/null | sort -rn | head -6 || true)
while read -r kb path; do
    if [ -z "${path:-}" ]; then continue; fi
    printf '%s|%s|LOG|%s|%s\n' "$now_ts" "$now_epoch" "$path" "$kb" >> "$DISK_HISTORY" || true
done <<< "$log_top"

# ---- Build sorted lists for set comparison ----
# curr.list: sorted, deduplicated set of currently-down items
# prev.list: same from the previous run's state file
TMP_CURR=$(mktemp) TMP_PREV=$(mktemp)
trap 'rm -f "$TMP_CURR" "$TMP_PREV" /tmp/ktp-health-resp.txt' EXIT

if [ ${#down[@]} -gt 0 ]; then
    printf '%s\n' "${down[@]}" | sort -u > "$TMP_CURR"
else
    : > "$TMP_CURR"
fi

if [ -f "$STATE_FILE" ]; then
    jq -r '.down[]?' < "$STATE_FILE" 2>/dev/null | sort -u > "$TMP_PREV"
else
    : > "$TMP_PREV"
fi

# ---- Compute transitions via comm ----
# comm -23: lines only in curr (new_down)
# comm -13: lines only in prev (recovered)
mapfile -t new_down < <(comm -23 "$TMP_CURR" "$TMP_PREV")
mapfile -t recovered < <(comm -13 "$TMP_CURR" "$TMP_PREV")

# ---- State save (called AFTER a successful alert, or on no-transition runs) ----
# Persisting before the Discord POST permanently consumed the edge on a failed
# delivery (the relay has no queue) — the transition became "known state" and
# never re-alerted. Now a failed POST leaves the previous state intact so the
# next hourly run re-detects the same transitions and retries the alert.
# Accepted trade: a service that flaps down AND back up entirely between a
# failed-POST run and the next run produces no alert for either edge (the
# recovered state matches the stale prev). Sub-hour flap + relay outage
# coinciding — rarer and less important than losing a persistent-down alert.
save_state() {
    mkdir -p "$(dirname "$STATE_FILE")"
    local down_json
    if [ -s "$TMP_CURR" ]; then
        down_json=$(jq -R . < "$TMP_CURR" | jq -s .)
    else
        down_json='[]'
    fi
    jq -n --argjson d "$down_json" --arg ts "$(ts)" \
        '{updated_at: $ts, down: $d}' > "$STATE_FILE"
}

# ---- Alert on transitions only ----
if [ ${#new_down[@]} -eq 0 ] && [ ${#recovered[@]} -eq 0 ]; then
    save_state
    echo "[$(ts)] no transitions (currently down: ${#down[@]})"
    exit 0
fi

echo "[$(ts)] TRANSITIONS: new_down=${#new_down[@]} recovered=${#recovered[@]}"

# Build Discord embed body
desc=""
if [ ${#new_down[@]} -gt 0 ]; then
    desc+='⚠️ **Services down:**'$'\n'
    for x in "${new_down[@]}"; do
        desc+="• \`${x}\`"$'\n'
    done
fi
if [ ${#recovered[@]} -gt 0 ]; then
    [ -n "$desc" ] && desc+=$'\n'
    desc+='✅ **Recovered:**'$'\n'
    for x in "${recovered[@]}"; do
        desc+="• \`${x}\`"$'\n'
    done
fi

# Still-down services (persistent, informational footer)
if [ ${#down[@]} -gt 0 ]; then
    current_list=$(printf '%s\n' "${down[@]}" 2>/dev/null | grep -v '^$' | sort -u)
    if [ -n "$current_list" ]; then
        desc+=$'\n''_All currently down: '"$(echo "$current_list" | paste -sd, -)"'_'
    fi
fi

# KTP canonical colors — match perf-rollup, crashreporter, soak-verify, etc.
# Pre-1.5.24 used raw hex (65280 / 16711680) which rendered as pure green/red
# instead of the KTP brand colors. Aligning now so the data-server-health
# embeds visually match the rest of the alert flow.
KTP_GREEN=5763719
KTP_RED=15548997
color=$KTP_GREEN
[ ${#new_down[@]} -gt 0 ] && color=$KTP_RED

payload=$(jq -n \
    --arg ch "$ALERT_CHANNEL" \
    --arg title '<:KTP:1002382703020212245> KTP Data Server Health' \
    --arg desc "$desc" \
    --arg footer "ktp-data-server-health @ $(TZ=America/New_York date '+%Y-%m-%d %H:%M %Z')" \
    --argjson color "$color" \
    '{channelId: $ch, embeds: [{title: $title, description: $desc, color: $color, footer: {text: $footer}}]}')

http=$(curl -sS -o /tmp/ktp-health-resp.txt -w "%{http_code}" \
    -X POST "${RELAY_URL:-}" \
    -H "X-Relay-Auth: ${AUTH_SECRET:-}" \
    -H "Content-Type: application/json" \
    -d "$payload" 2>&1 || echo "000")
if [ "$http" != "200" ] && [ "$http" != "204" ]; then
    echo "[$(ts)] WARN: relay returned HTTP $http: $(cat /tmp/ktp-health-resp.txt 2>/dev/null | head -c 200)" >&2
    echo "[$(ts)] state NOT saved — transitions will re-alert on the next run" >&2
else
    save_state
    echo "[$(ts)] alert posted (HTTP $http)"
fi
