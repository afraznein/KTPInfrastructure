#!/bin/bash
# Bracket one ktp-reports step with timestamped start/end lines.
#
#   ExecStart=/bin/bash scripts/report_step.sh generate /usr/bin/python3 -m scripts.report_service ...
#
# The journal records only `code=killed` when TimeoutStartSec fires, so without
# these lines a timeout cannot be pinned on generate, aggregate or sync. A start
# with no matching end is the step that was running when the run died.
#
# Exits with the step's own status, so systemd still stops at the first failure.

set -u

if [ "$#" -lt 2 ]; then
    echo "usage: ${0##*/} <step-name> <command> [args...]" >&2
    exit 64
fi

step=$1
shift

stamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }

echo "$(stamp) ktp-reports step=$step start pid=$$"

# Record which step took the TERM, then pass it on. The step runs in the
# background so this fires at once, not after the step has finished; $! rather
# than a variable, because the TERM can land before an assignment would run.
on_term() {
    echo "$(stamp) ktp-reports step=$step killed signal=TERM elapsed=${SECONDS}s"
    if [ -n "${!:-}" ]; then
        kill -TERM "$!" 2>/dev/null
        wait "$!" 2>/dev/null
    fi
    exit 143
}
trap on_term TERM

"$@" &
wait "$!"
rc=$?

echo "$(stamp) ktp-reports step=$step end rc=$rc elapsed=${SECONDS}s"
exit "$rc"
