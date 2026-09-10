#!/bin/bash
# Verify the KTP patch to LinuxGSM's command_monitor.sh on every instance of one
# game host. Read-only: it parses files and starts, stops and restarts nothing.
#
# WHY THIS EXISTS. The patch neutralises a monitor branch that pkills live
# servers mid-match, and `./dodserver update-lgsm` overwrites the patched file.
# Nothing verified the patch was still there, and nothing verified it landed
# right: the line range it is applied by is version-specific, and on LinuxGSM
# v26.2.0 the same range orphans an `elif` and leaves a command_monitor.sh that
# does not parse. Monitor then exits 2 every minute, silently, because the cron
# redirects to /dev/null -- the Philly LAN box ran nine days that way and sat
# through a three-hour outage. See docs/LINUXGSM.md.
#
# Run it after every `update-lgsm`, on any new host before enabling the monitor
# cron, and weekly via audit-fleet-drift.py, which uploads this file alongside
# fleet-drift-snapshot.sh and parses the section below as ordinary snapshot facts.
#
# Usage:  bash ktp-monitor-patch-check.sh
# Exit:   0 = every instance parses AND its old-type check is not armed
#         1 = at least one instance is broken or dangerous
#
# DOD_HOME overrides the instance root (tests only). Absolute by default so the
# audit can run this as root, the way it runs the snapshot.

DOD_HOME="${DOD_HOME:-/home/dodserver}"

# The three `pgrep -f` conditions in fn_monitor_check_session, by the literal
# text of each. Anchoring on content rather than a line number is the whole
# point: LinuxGSM renumbers this file between releases, which is what made the
# original 203,212 patch dangerous.
NEEDLE_DUPPID='tmux -L ${socketname} new-session'
NEEDLE_SAMESOCKET='tmux -L ${sessionname} new-session'
NEEDLE_OLDTYPE='"tmux new-session'

# A check is armed if its condition survives on an uncommented line. Absent is
# reported as its own state, never folded into "disabled": a needle that has
# vanished may mean the canonical `if false` patch replaced the line, or may
# mean LinuxGSM rewrote the branch and this script is now looking for the wrong
# thing. Those want different responses, so they get different words.
check_state() {
    local file="$1" needle="$2" marker="$3"
    # `pgrep -f` narrows to the CONDITION line. Each branch also names the same
    # tmux pattern in its `pkill` body, and the canonical patch rewrites only
    # the condition -- matching the body too would read every canonically
    # patched instance as armed.
    if grep -F -- "$needle" "$file" | grep -F -- 'pgrep -f' | grep -qv '^[[:space:]]*#'; then
        echo armed
    elif grep -F -- "$needle" "$file" | grep -qF -- 'pgrep -f'; then
        echo disabled
    elif grep -qF -- "KTP-DISABLED: $marker" "$file"; then
        echo disabled
    else
        echo absent
    fi
}

faults=0
lines=()
versions=()
instances=0

for d in "$DOD_HOME"/dod-2701*; do
    [ -d "$d" ] || continue
    instances=$((instances + 1))
    name="$(basename "$d")"
    file="$d/lgsm/modules/command_monitor.sh"

    if [ ! -f "$file" ]; then
        lines+=("$name: parse=MISSING oldtype=? samesocket=? duppid=?")
        faults=$((faults + 1))
        continue
    fi

    if bash -n "$file" 2>/dev/null; then
        parse=OK
    else
        parse=BROKEN
        faults=$((faults + 1))
    fi

    oldtype="$(check_state "$file" "$NEEDLE_OLDTYPE" 'old-type check')"
    samesocket="$(check_state "$file" "$NEEDLE_SAMESOCKET" 'same socket+session check')"
    duppid="$(check_state "$file" "$NEEDLE_DUPPID" 'duplicate-PID check')"

    # Only the old-type branch is a fault. The other two are reported and
    # compared across the fleet, but production deliberately leaves them armed:
    # duplicate-PID detection is correct upstream, and the same-socket branch is
    # dead only because LinuxGSM suffixes the socket with a hash. Converging
    # prod to the canonical `if false` form is a provisioning decision, not an
    # incident -- so it must not make this check exit 1 every week.
    [ "$oldtype" = armed ] && faults=$((faults + 1))

    lines+=("$name: parse=$parse oldtype=$oldtype samesocket=$samesocket duppid=$duppid")

    v="$(grep -hm1 '^version=' "$d"/dodserver* 2>/dev/null | cut -d= -f2 | tr -d '"')"
    [ -z "$v" ] && v="$(grep -hm1 '^version=' "$d/lgsm/modules/core_functions.sh" 2>/dev/null | cut -d= -f2 | tr -d '"')"
    [ -n "$v" ] && versions+=("$v")
done

echo "=== LINUXGSM MONITOR ==="
echo "instances: $instances"
# Joined and de-duplicated so one key carries the answer for the whole host: two
# LinuxGSM versions side by side on one box is itself the finding.
if [ "${#versions[@]}" -gt 0 ]; then
    echo "lgsm-versions: $(printf '%s
' "${versions[@]}" | sort -u | paste -sd, -)"
fi
[ "${#lines[@]}" -gt 0 ] && printf '%s
' "${lines[@]}"

# Finding no instances is a failure, not a clean run. A sweep that quietly
# matched nothing renders as a healthy host, which is the exact shape of the
# silence this script exists to break.
if [ "$instances" -eq 0 ]; then
    echo "no dod-2701* instances under $DOD_HOME" >&2
    exit 1
fi

[ "$faults" -eq 0 ] || exit 1
