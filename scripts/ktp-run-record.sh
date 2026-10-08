#!/bin/bash
# Keep one scheduled run's output, exit code and completion on disk.
#
# Wrap a oneshot unit's command:
#
#   [Service]
#   Type=oneshot
#   StateDirectory=ktp-stats-export
#   TimeoutStartSec=15min
#   ExecStart=/usr/local/bin/ktp-run-record.sh /usr/local/bin/ktp-stats-export.py --hours 48
#
# Which of the estate's three run-record shapes this is, and when each applies:
# docs/runbooks/UNIT_RUN_RECORDS.md. The short version -- StateDirectory is the
# only writable path a unit is guaranteed under ProtectSystem=strict, so it is
# the one shape that needs no second unit-file decision later.
#
# This does not replace OnFailure=ktp-systemd-alert@%n.service. That posts the
# embed somebody reads; this keeps the copy somebody can go back to.
#
# Reads STATE_DIRECTORY from systemd. Pure bash + coreutils, no network, no
# credentials: it has to work on the run where everything else did not.

set -uo pipefail

# ---- where the records go -------------------------------------------------

# systemd joins multiple StateDirectory= entries with ':'; the first is ours.
RECORD_ROOT="${KTP_RUN_RECORD_DIR:-${STATE_DIRECTORY:-}}"
RECORD_ROOT="${RECORD_ROOT%%:*}"
# Dated records live long enough that last season's are readable during the next.
KEEP_DAYS="${KTP_RUN_RECORD_KEEP_DAYS:-400}"
# 1 = keep a dated record only when the run fails, and stamp last-ok.txt when it
# does not. For a per-minute unit, a dated file per run is 1440 files a day and
# the healthy runs are the ones nobody will ever open.
ONLY_FAILURES="${KTP_RUN_RECORD_ONLY_FAILURES:-0}"

if [ "$#" -eq 0 ]; then
    echo "usage: ${0##*/} <command> [args...]" >&2
    exit 64
fi

# Refusing to run beats running without a record: that is the whole point of the
# wrapper, and a unit that names it in ExecStart can declare StateDirectory in
# the same file. EX_CONFIG, so the cause is distinguishable from the command's
# own exit codes.
if [ -z "$RECORD_ROOT" ]; then
    echo "FATAL: no STATE_DIRECTORY and no KTP_RUN_RECORD_DIR -- add StateDirectory= to this unit" >&2
    exit 78
fi
case "$KEEP_DAYS" in
    ''|*[!0-9]*)
        echo "FATAL: KTP_RUN_RECORD_KEEP_DAYS must be a whole number of days, got '$KEEP_DAYS'" >&2
        exit 78 ;;
esac

RUNS="$RECORD_ROOT/runs"
if ! mkdir -p "$RUNS"; then
    echo "FATAL: cannot create $RUNS" >&2
    exit 78
fi

STAMP="$(date -u +%Y-%m-%dT%H%M%SZ)"
PART="$RUNS/$STAMP.txt.part"
# Two fires inside one second would otherwise share a path and interleave.
if [ -e "$PART" ]; then PART="$RUNS/$STAMP-$$.txt.part"; fi
RECORD="${PART%.part}"

# ---- what the record says -------------------------------------------------

# systemd exports no unit name, so take it from the cgroup path and fall back to
# the wrapped command. Cosmetic: the record is identified by its directory.
unit_name() {
    local u
    u="$(sed -n 's#.*/\([^/]*\.service\)$#\1#p' /proc/self/cgroup 2>/dev/null | head -1)"
    printf '%s' "${u:-${1##*/}}"
}

UNIT="$(unit_name "$1")"
START_EPOCH="$(date -u +%s)"
SIGNAL=""

if ! {
    printf 'unit: %s\n' "$UNIT"
    printf 'command: %s\n' "$*"
    printf 'host: %s\n' "$(uname -n)"
    printf 'started: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'record: %s\n' "$RECORD"
    printf -- '---\n'
} > "$PART"; then
    echo "FATAL: cannot write $PART" >&2
    exit 78
fi

# A run killed outright leaves its last words in a kernel buffer rather than in
# the record, which is exactly the run worth reading. Costs a wedge-free unit
# nothing.
export PYTHONUNBUFFERED=1

# A promoted record always carries a `finished:` line, so its absence is never
# ambiguous: a footer that cannot be written is a failed promotion, not a
# record that quietly looks complete.
promote() {
    local rc="$1" dest="$2"
    if ! {
        printf -- '---\n'
        printf 'finished: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        printf 'duration: %ss\n' "$(( $(date -u +%s) - START_EPOCH ))"
        if [ -n "$SIGNAL" ]; then printf 'killed: SIG%s\n' "$SIGNAL"; fi
        printf 'rc: %s\n' "$rc"
    } >> "$PART"; then
        return 1
    fi
    mv -f "$PART" "$dest"
}

on_exit() {
    local rc=$?
    local dest="$RECORD" dated=1
    # A clean run of a per-minute unit is stamped, not archived.
    if [ "$ONLY_FAILURES" = "1" ] && [ "$rc" -eq 0 ] && [ -z "$SIGNAL" ]; then
        dest="$RUNS/last-ok.txt"
        dated=0
    fi
    if ! promote "$rc" "$dest"; then
        # The journal line is itself durable: OnFailure hands it to
        # ktp-systemd-alert, which appends it to /var/log/ktp-systemd-alert.log.
        echo "FATAL: could not keep $dest -- this run left no durable record" >&2
        if [ "$rc" -eq 0 ]; then exit 70; fi
        exit "$rc"
    fi
    if [ "$dated" = "1" ]; then
        # Only when a dated file was written, so the healthy path of a
        # per-minute unit does no directory walk at all. last-ok.txt is spared:
        # it is the newest success even when that success is old, and losing it
        # would turn a long outage into "this unit has never worked".
        find "$RUNS" -maxdepth 1 -type f \( -name '*.txt' -o -name '*.txt.part' \) \
            ! -name 'last-ok.txt' -mtime "+$KEEP_DAYS" -delete 2>/dev/null || true
    fi
    exit "$rc"
}

# A promoted record naming a signal is a wedge systemd cut short. An orphan
# .part is a wedge SIGKILLed outright -- nothing ran to promote it, and the file
# that is still there is the evidence.
on_signal() { SIGNAL="$1"; }
trap 'on_signal TERM' TERM
trap 'on_signal INT' INT
trap 'on_signal HUP' HUP
trap on_exit EXIT

# ---- run it ---------------------------------------------------------------

# Both streams, so stdout-is-the-report units keep their report and the journal
# tail the Discord embed carries is unchanged. The merge costs the journal's
# per-line priority, which is why `journalctl -p err` is not a check here.
{ "$@" 2>&1; } | tee -a "$PART"
exit "${PIPESTATUS[0]}"
