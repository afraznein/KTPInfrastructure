#!/bin/bash
# Severity/colour canon. Deploy ktp-alert-routing.sh beside this script; a
# partial deploy must fail loudly here, not post the wrong colour or nothing.
. "$(dirname "${BASH_SOURCE[0]}")/ktp-alert-routing.sh" || {
    echo "FATAL: ktp-alert-routing.sh not found beside $0 — deploy it first" >&2; exit 3; }
# KTP — HLTV proxy liveness check.
#
# WHY THIS EXISTS
# On 2026-08-10 hltv@27035 (NY 1) died inside Proxy::Init at 11:00:02 and stayed
# dead until 20:48 — 9h48m — and nothing noticed. The HLTV binary died while the
# wrapper (a `tail -f` on the command pipe) stayed alive, so systemd reported
# `active (running)` the entire time and every check built on unit state agreed.
# The 12man played on NY 1 that evening was never recorded.
#
# The only thing that alerts on HLTV is hltv-restart-all.sh at 03:00 and 11:00,
# so a proxy dying just after a restart is unmonitored for the rest of the day.
# That is exactly the 9h48m observed. Silence was indistinguishable from health.
#
# WHAT IT CHECKS, AND WHY THESE
# Whether the port is actually BOUND, not what systemd believes. A dead binary
# releases its socket; a live wrapper does not hold it open. `ss` therefore
# disagrees with systemd precisely in the failure mode that matters.
#
# And whether a bound proxy is RECORDING. A proxy can bind, never load its own
# config and answer "Not connected." until the next restart: the port check reads
# healthy while every match on that server goes unrecorded. A connected proxy
# appends to its demo continuously, even on an empty server, so the age of its
# newest demo is the signal a bound port cannot give.
#
# Deliberately NOT rcon: rcon needs the admin password on the command line, and
# a proxy can be bound-but-wedged in ways rcon would catch — but rcon failing
# is also how a busy proxy looks. Port-bound is the cheap unambiguous signal.
set -uo pipefail

STATE_DIR="${KTP_HLTV_LIVENESS_STATE_DIR:-/var/lib/ktp-hltv-liveness}"
STATE="$STATE_DIR/state"          # consecutive-failure counter + last-alert stamp
CONF="${KTP_RELAY_CONF:-/etc/ktp/discord-relay.conf}"
HLTV_CONFIG_DIR="${HLTV_CONFIG_DIR:-/home/hltvserver/hlds/configs}"
HLTV_DEMO_DIR="${HLTV_DEMO_DIR:-/home/hltvserver/hlds/dod}"
LOG_PREFIX="[hltv-liveness]"

# Two consecutive failures before alerting. The 03:00/11:00 restarts unbind all
# 24 briefly, so a single-sample check pages twice a day forever — and a monitor
# that cries wolf gets muted, which lands back at no monitoring.
FAIL_THRESHOLD=2
# While still down, re-alert this often so a long outage does not go quiet after
# the first message.
REMIND_SECONDS=10800   # 3h
# Comfortably past a game-server restart's reconnect; FAIL_THRESHOLD then has to
# see it twice before anyone is paged.
STALE_SECONDS="${STALE_SECONDS:-300}"

# The alert path is reached only once something is already wrong, so an unbounded
# wait there hangs precisely the run that has something to say. These exist to fail
# fast and REPORT; TimeoutStartSec=4min only kills the run, it never explains it.
RELAY_CONNECT_SECONDS="${RELAY_CONNECT_SECONDS:-5}"
RELAY_MAX_SECONDS="${RELAY_MAX_SECONDS:-15}"
# Paid once per DOWN proxy, so the whole fleet being down is the sizing case; the
# budget against TimeoutStartSec= is asserted in the unit tests, not guessed here.
SYSTEMCTL_SECONDS="${SYSTEMCTL_SECONDS:-3}"
SS_SECONDS="${SS_SECONDS:-10}"

mkdir -p "$STATE_DIR"

in_list() {
    local want="$1" x
    shift
    for x in "$@"; do [ "$x" = "$want" ] && return 0; done
    return 1
}

fmt_age() {
    local s="$1"
    if [ "$s" -ge 3600 ]; then
        printf '%dh%02dm' $((s / 3600)) $((s % 3600 / 60))
    else
        printf '%dm%02ds' $((s / 60)) $((s % 60))
    fi
}

# The demo name comes from the proxy's own config, the file that decides what it
# records, so it cannot drift the way a second port table would.
record_name() {
    grep -m1 -oE '^[[:space:]]*record[[:space:]]+[A-Za-z0-9_]+' "$HLTV_CONFIG_DIR/hltv-$1.cfg" 2>/dev/null \
        | awk '{print $2}'
}

# ---------------------------------------------------------------- expected set
# Derived from the enabled hltv@ units, never a hardcoded 27020-27043. A literal
# range silently goes wrong the next time a proxy is added or removed — exactly
# what left a stale row for the deleted Chicago 27019 in hlstats_Servers.
# Captured before the pipe so a kill is distinguishable from a genuine zero; a
# process substitution would hand back grep's status instead.
units=$(timeout "$SYSTEMCTL_SECONDS" systemctl list-units 'hltv@*' --no-pager --plain --all 2>/dev/null)
enum_rc=$?
mapfile -t EXPECTED < <(printf '%s\n' "$units" \
    | grep -oE 'hltv@[0-9]+' | grep -oE '[0-9]+' | sort -u)

# FAIL CLOSED. A probe that cannot run looks exactly like a clean result, and
# this project has been bitten by that repeatedly. No units enumerated means the
# check is broken, not that the fleet is empty.
if [ "${#EXPECTED[@]}" -eq 0 ]; then
    why="enumerated 0 hltv@ units"
    [ "$enum_rc" -eq 124 ] && why="systemctl list-units did not answer within ${SYSTEMCTL_SECONDS}s"
    echo "$LOG_PREFIX CONTROL FAILED: $why; refusing to report healthy" >&2
    exit 2
fi

# ------------------------------------------------------------------ bound set
# Bounded: a kill leaves BOUND empty, which is already the designed answer below.
mapfile -t BOUND < <(timeout "$SS_SECONDS" ss -lunH 2>/dev/null \
    | grep -oE ':(270[0-9][0-9])\b' | tr -d ':' | sort -u)

# Same fail-closed rule: ss returning nothing while units exist is a broken probe
# or a total outage. Both warrant an alert; neither is "healthy".
MISSING=()
for p in "${EXPECTED[@]}"; do
    in_list "$p" "${BOUND[@]:-}" || MISSING+=("$p")
done

# -------------------------------------------------------------- recording set
# Fails closed too: a missing record line or no demo at all is reported, never
# skipped, so an unreadable demo dir alerts on every proxy instead of passing.
NOW=$(date +%s)
STALE=()
for p in "${EXPECTED[@]}"; do
    # An unbound proxy is already reported as down; listing it twice adds nothing.
    in_list "$p" "${MISSING[@]:-}" && continue
    name=$(record_name "$p")
    if [ -z "$name" ]; then
        STALE+=("port $p: no record line in hltv-$p.cfg, so there is nothing to measure")
        continue
    fi
    newest=$(find "$HLTV_DEMO_DIR" -maxdepth 1 -name "$name-*.dem" -printf '%T@\n' 2>/dev/null | sort -n | tail -1)
    if [ -z "$newest" ]; then
        STALE+=("port $p: no $name-*.dem in $HLTV_DEMO_DIR")
        continue
    fi
    age=$(( NOW - ${newest%.*} ))
    [ "$age" -gt "$STALE_SECONDS" ] && STALE+=("port $p: $name last written $(fmt_age "$age") ago")
done

PREV_FAILS=0
LAST_ALERT=0
if [ -r "$STATE" ]; then
    # shellcheck disable=SC1090
    . "$STATE" 2>/dev/null || true
    PREV_FAILS="${FAILS:-0}"
    LAST_ALERT="${LAST_ALERT:-0}"
fi

send_alert() {
    local title="$1" description="$2" color="$3"
    if [ ! -r "$CONF" ]; then
        echo "$LOG_PREFIX cannot read $CONF — alert NOT sent" >&2
        return 1
    fi
    # shellcheck disable=SC1090
    . "$CONF"
    local footer rc tried=0 first_rc=1
    footer="$(hostname) - $(date '+%Y-%m-%d %H:%M:%S %Z')"
    # :- on every conf key: set -u kills the run mid-send on an unset name, and
    # bash exits 1 doing it — this script's own code for "detected and reported" —
    # so the death reads as a report and FAILS freezes at its last written value.
    for ch in "${CHANNEL_HLTV_STATUS:-}" "${CHANNEL_HLTV_STATUS_EXTERNAL:-}"; do
        [ -z "${ch:-}" ] && continue
        # --fail because without it a 503 from the relay exits 0 and the run records
        # an alert nobody received; -S so curl's own reason reaches the journal.
        curl -sS --fail \
            --connect-timeout "$RELAY_CONNECT_SECONDS" \
            --max-time "$RELAY_MAX_SECONDS" \
            -X POST "${RELAY_URL:-}" \
            -H "X-Relay-Auth: ${AUTH_SECRET:-}" \
            -H "Content-Type: application/json" \
            -d "$(cat <<EOF
{
  "channelId": "$ch",
  "embeds": [{
    "title": "$title",
    "description": "$description",
    "color": $color,
    "footer": { "text": "$footer" }
  }]
}
EOF
)" >/dev/null
        rc=$?
        [ "$tried" -eq 0 ] && first_rc="$rc"
        tried=$((tried + 1))
        [ "$rc" -ne 0 ] && echo "$LOG_PREFIX relay POST to channel $ch FAILED (curl exit $rc) — not delivered there" >&2
    done
    # A set-but-empty channel used to send nothing and return success, so a
    # mis-edited conf silenced the monitor with no trace anywhere.
    if [ "$tried" -eq 0 ]; then
        echo "$LOG_PREFIX no HLTV status channel set in $CONF — alert NOT sent" >&2
        return 1
    fi
    # The first channel ATTEMPTED gates the caller — not the last, or a broken
    # external would re-page the primary every cadence; and not the literally
    # first, because an empty primary is skipped before the counter.
    [ "$first_rc" -eq 0 ]
}

if [ "${#MISSING[@]}" -eq 0 ] && [ "${#STALE[@]}" -eq 0 ]; then
    # Recovered: say so once, then go quiet.
    if [ "$PREV_FAILS" -ge "$FAIL_THRESHOLD" ]; then
        if ! send_alert "✅ HLTV proxies recovered" \
            "All ${#EXPECTED[@]} proxies are bound and recording again." 3066993; then
            # State left alone so the next run retries. Clearing it here would drop
            # the only message that ends a page, and exiting 0 would make a lost
            # all-clear indistinguishable from a delivered one.
            echo "$LOG_PREFIX recovered, but the all-clear was NOT delivered — state kept so the next run retries" >&2
            exit 4
        fi
        echo "$LOG_PREFIX recovered — all ${#EXPECTED[@]} bound and recording"
    fi
    printf 'FAILS=0\nLAST_ALERT=0\n' > "$STATE"
    exit 0
fi

FAILS=$((PREV_FAILS + 1))
if [ "${#MISSING[@]}" -gt 0 ]; then
    echo "$LOG_PREFIX ${#MISSING[@]} of ${#EXPECTED[@]} proxies NOT bound (attempt $FAILS): ${MISSING[*]}" >&2
fi
for s in "${STALE[@]:-}"; do
    [ -n "$s" ] && echo "$LOG_PREFIX NOT recording (attempt $FAILS): $s" >&2
done

# Set here, never defaulted: $CONF and $STATE are both sourced and both
# operator-edited, and a guard that reads 1 from somewhere else would exit 4
# on every healthy run.
ALERT_FAILED=0

if [ "$FAILS" -ge "$FAIL_THRESHOLD" ] && { [ "$LAST_ALERT" -eq 0 ] || [ $((NOW - LAST_ALERT)) -ge "$REMIND_SECONDS" ]; }; then
    desc=""
    if [ "${#MISSING[@]}" -gt 0 ]; then
        # systemd's own opinion is included precisely because it is the thing that
        # lied for 9h48m — seeing "active" next to "not bound" is the whole tell.
        states=""
        for p in "${MISSING[@]}"; do
            # Read by emptiness, not exit status: is-active exits 3 for a genuinely
            # inactive unit, so keying on $? would relabel the state shown here.
            unit_state=$(timeout "$SYSTEMCTL_SECONDS" systemctl is-active "hltv@$p" 2>/dev/null)
            states="$states\\n• port $p — unit: ${unit_state:-unknown (systemctl did not answer)}"
        done
        desc="**${#MISSING[@]} of ${#EXPECTED[@]}** proxies are not bound.$states\\n\\nsystemd may still report \`active\` — the binary can die while the wrapper survives."
    fi
    if [ "${#STALE[@]}" -gt 0 ]; then
        list=""
        for s in "${STALE[@]}"; do list="$list\\n• $s"; done
        [ -n "$desc" ] && desc="$desc\\n\\n"
        desc="$desc**${#STALE[@]} of ${#EXPECTED[@]}** proxies are bound but not recording.$list\\n\\nA proxy that never connected to its game server passes the port check and writes no demo, so matches there go unrecorded."
    fi
    title="🔴 HLTV proxy DOWN"
    [ "${#MISSING[@]}" -eq 0 ] && title="🔴 HLTV proxy NOT RECORDING"
    # LAST_ALERT is left untouched on a failure, so the next run retries at the
    # cadence instead of consuming the 3h remind window on an undelivered page.
    if send_alert "$title" "$desc" "$KTP_RED"; then
        LAST_ALERT="$NOW"
    else
        ALERT_FAILED=1
    fi
fi

printf 'FAILS=%s\nLAST_ALERT=%s\n' "$FAILS" "$LAST_ALERT" > "$STATE"
# Detected but could not say so. Exit 4 sits outside the unit's SuccessExitStatus
# deliberately: 1 and 2 are forgiven because the script reported them itself, and
# reporting is the one thing this case could not do.
[ "${ALERT_FAILED:-0}" -eq 1 ] && exit 4
exit 1
