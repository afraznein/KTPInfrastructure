#!/bin/bash
# ktp-monitor-guard.sh — run a LinuxGSM `monitor` unless this host's own network is down.
#
# Usage (one crontab line per instance, replacing the bare monitor line):
#   * * * * * /home/dodserver/ktp-monitor-guard.sh /home/dodserver/dod-27015/dodserver monitor > /dev/null 2>&1
#
# LinuxGSM's monitor restarts an instance after five failed gsquery attempts. It
# cannot tell a hung server from a host that lost its link: when the carrier
# drops, networkd removes the static address, every query fails, and the monitor
# restarts the instance into a network where `+ip <addr> -strictportbind` cannot
# bind. The new process dies at startup (EADDRNOTAVAIL -> Sys_Error -> core), and
# the next tick after the link returns restarts it again.
#
# The monitor is skipped for this tick, and nothing else changes, when ANY of:
#   - the instance's configured bind address (`ip=` in its LinuxGSM config) is
#     not assigned to any interface on the host;
#   - the interface carrying that address (or, for a wildcard/unknown address,
#     the default route's interface) reports no carrier;
#   - there is no IPv4 default route.
# Otherwise it execs the wrapped command unchanged, so a hung server on a
# healthy host is restarted exactly as before.
#
# Fails OPEN: if a check cannot be evaluated (no `ip`, unreadable config or
# sysfs), the monitor runs. A guard that suppresses on its own error would turn
# a broken probe into a host with no auto-restart.
#
# Logs one HOLD line when a hold starts and one RESUME line when it ends, to
# $HOME/log/monitor-guard.log and syslog (tag ktp-monitor-guard). Hold state is
# one file per instance under ${KTP_STATE_DIR:-$HOME/.ktp}/monitor-guard/.
#
# The crontab line must still match ktp-scheduled-restart.sh's
# MONITOR_CRON_MATCH ('dodserver.*monitor') and ktp-fleet-health.sh's count
# ('^[^#]*monitor'); keeping the control path and `monitor` as arguments does.
#
# Test hooks: KTP_MONITOR_GUARD_SYS_NET (default /sys/class/net),
# KTP_MONITOR_GUARD_STATE_DIR, KTP_MONITOR_GUARD_LOG.

set -u

if [ $# -lt 1 ]; then
    echo "usage: $0 <linuxgsm-control-script> [command...]" >&2
    exit 2
fi

CTL=$1
shift
[ $# -gt 0 ] || set -- monitor
SELF=$(basename "$CTL")
INSTANCE_DIR=$(cd "$(dirname "$CTL")" 2>/dev/null && pwd) || INSTANCE_DIR=$(dirname "$CTL")

SYS_NET="${KTP_MONITOR_GUARD_SYS_NET:-/sys/class/net}"
STATE_DIR="${KTP_MONITOR_GUARD_STATE_DIR:-${KTP_STATE_DIR:-$HOME/.ktp}/monitor-guard}"
LOG_FILE="${KTP_MONITOR_GUARD_LOG:-$HOME/log/monitor-guard.log}"
# Warmup's control script is also called `dodserver`, so the key needs the directory too.
HELD="$STATE_DIR/$(basename "$INSTANCE_DIR").$SELF.held"

# >>> ktp-monitor-guard-checks
# Last literal ip= in LinuxGSM's own load order; empty for wildcard or anything unparseable.
guard_bind_ip() {
    local instance_dir=$1 self=$2 dir f line v=""
    for dir in "$instance_dir"/lgsm/config-lgsm/*/; do
        [ -f "$dir$self.cfg" ] || continue
        for f in _default.cfg common.cfg secrets-common.cfg "$self.cfg" "secrets-$self.cfg"; do
            [ -r "$dir$f" ] || continue
            line=$(grep -E '^[[:space:]]*ip=' "$dir$f" 2>/dev/null | tail -n 1)
            [ -n "$line" ] && v=${line#*=}
        done
        break
    done
    v=${v%%#*}
    v=$(printf '%s' "$v" | tr -d "\"' \t\r")
    if [[ $v =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]] && [ "$v" != 0.0.0.0 ]; then
        printf '%s' "$v"
    fi
}

# Prints a reason and returns 0 when the host's network is down; returns 1 when
# it is up OR cannot be judged, so every unknown falls through to the monitor.
guard_network_down() {
    local bind_ip=$1 sys_net=$2 route addr dev="" carrier
    command -v ip >/dev/null 2>&1 || return 1
    route=$(ip -4 route show default 2>/dev/null) || return 1
    if [ -n "$bind_ip" ]; then
        # `ip addr show to <absent addr>` exits 0 with no output, so test the output.
        addr=$(ip -o -4 addr show to "$bind_ip" 2>/dev/null) || return 1
        if [ -z "$addr" ]; then
            echo "bind address $bind_ip is not configured on any interface"
            return 0
        fi
        dev=$(printf '%s\n' "$addr" | awk 'NR==1 {sub(":", "", $2); print $2}')
    fi
    if [ -z "$route" ]; then
        echo "no IPv4 default route"
        return 0
    fi
    [ -n "$dev" ] || dev=$(printf '%s\n' "$route" | awk '{for (i = 1; i < NF; i++) if ($i == "dev") {print $(i + 1); exit}}')
    dev=${dev%%@*}
    [ -n "$dev" ] && [ "$dev" != lo ] || return 1
    carrier=$(cat "$sys_net/$dev/carrier" 2>/dev/null)
    if [ "$carrier" = 0 ]; then
        echo "$dev has no carrier"
        return 0
    fi
    # carrier reads EINVAL on an admin-down link; operstate still answers.
    if [ -z "$carrier" ] && [ "$(cat "$sys_net/$dev/operstate" 2>/dev/null)" = down ]; then
        echo "$dev is down"
        return 0
    fi
    return 1
}
# <<< ktp-monitor-guard-checks

note() {
    local msg="$SELF ($INSTANCE_DIR): $*"
    mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null
    printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$msg" >> "$LOG_FILE" 2>/dev/null
    logger -t ktp-monitor-guard -- "$msg" 2>/dev/null || true
}

if reason=$(guard_network_down "$(guard_bind_ip "$INSTANCE_DIR" "$SELF")" "$SYS_NET"); then
    if [ ! -e "$HELD" ]; then
        mkdir -p "$STATE_DIR" 2>/dev/null
        printf '%s %s\n' "$(date +%s)" "$reason" > "$HELD" 2>/dev/null
        note "HOLD monitor: $reason"
    fi
    exit 0
fi

if [ -e "$HELD" ]; then
    since=$(awk 'NR==1 {print $1}' "$HELD" 2>/dev/null)
    [[ $since =~ ^[0-9]+$ ]] || since=$(date +%s)
    rm -f "$HELD"
    note "RESUME monitor: network back after $(( $(date +%s) - since ))s"
fi

exec "$CTL" "$@"
