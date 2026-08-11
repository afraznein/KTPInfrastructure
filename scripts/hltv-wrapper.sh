#!/bin/bash
# HLTV wrapper — feeds remote commands in via a FIFO, and refuses to sit on a
# proxy that never came up.
# Usage: hltv-wrapper.sh <port>
#
# WHY THIS IS NOT JUST `tail -f | hltv`
# On 2026-08-10 hltv@27035 hit `Proxy::Init: Could not create proxy port 27020`,
# printed `*** STOPPING SYSTEM ***` — and did not exit. It sat at the HLTV
# console prompt for 9h48m, because its stdin is this FIFO and `tail -f` never
# EOFs. systemd had a live PID throughout and reported `active (running)`, so
# `Restart=always` never fired. The 12man played on NY 1 that evening was never
# recorded.
#
# WHY THIS WATCHES THE PORT AND NOT THE OUTPUT
# The obvious fix is to grep HLTV's output for the FATAL and kill it. That does
# not work here, and the reason is the same reason the incident lasted nine
# hours: HLTV block-buffers into the pipe, so the FATAL did not reach the
# journal until teardown — every line of that block carries the identical
# timestamp 20:48:11.733145. A detector reading that stream is blind for exactly
# as long as the operator was.
#
# stdbuf cannot rescue it either: hltv is a 32-bit binary and the system
# libstdbuf.so is 64-bit, so `stdbuf` fails with `wrong ELF class: ELFCLASS64`
# and is ignored. Verified 2026-08-11 — it emits an LD_PRELOAD error and buys
# nothing.
#
# So the check is the socket, which no amount of buffering can hide: if the port
# is not bound within STARTUP_GRACE, the proxy did not come up. Exit non-zero and
# let the existing Restart=always do the recovery it could not do before.
#
# The FIFO is load-bearing: KTPHLTVRecorder drives `record` / `stoprecording`
# through it. Do not remove it to "fix" stdin.
set -u

PORT=$1
PIPE="/home/hltvserver/cmdpipes/hltv-${PORT}.pipe"
HLTV="/home/hltvserver/hlds/hltv"
CONFIG="configs/hltv-${PORT}.cfg"
DIAG="/var/log/ktp-hltv-fatal.log"
STARTUP_GRACE=45      # seconds to bind; a healthy proxy binds in ~1s

[ -p "$PIPE" ] || mkfifo "$PIPE"

# Unchanged from the original except for backgrounding: same FIFO, same args,
# same RunFrame spam filter (grep --line-buffered, which does work).
tail -f "$PIPE" | "$HLTV" -game dod -port "$PORT" +exec "$CONFIG" 2>&1 |
    grep -v --line-buffered 'WARNING! System::RunFrame: system time difference' &
PIPELINE=$!

# ---------------------------------------------------------------- startup gate
(
    for _ in $(seq "$STARTUP_GRACE"); do
        sleep 1
        if ss -lunH 2>/dev/null | grep -q ":${PORT}\b"; then
            exit 0            # bound — nothing to do
        fi
        kill -0 "$PIPELINE" 2>/dev/null || exit 0   # already gone; systemd handles it
    done

    # Not bound after the grace period. Capture argv BEFORE killing: the
    # 2026-08-10 root cause — why the bind targeted 27020 when -port said 27035
    # — is still unexplained precisely because the wedged process's argv was
    # gone by the time anyone looked. This makes a recurrence self-diagnosing.
    pid=$(pgrep -f "hltv -game dod -port ${PORT}\b" | head -1)
    {
        echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') port=${PORT} NOT BOUND after ${STARTUP_GRACE}s"
        if [ -n "${pid:-}" ] && [ -r "/proc/$pid/cmdline" ]; then
            printf '    argv : '; tr '\0' ' ' < "/proc/$pid/cmdline"; echo
            printf '    cwd  : '; readlink "/proc/$pid/cwd" 2>/dev/null || echo '?'
        else
            echo "    (no hltv process found for this port)"
        fi
        echo "    bound in range: $(ss -lunH 2>/dev/null | grep -oE ':270[0-9][0-9]' | tr -d ':' | sort -u | tr '\n' ' ')"
    } >> "$DIAG" 2>/dev/null

    echo "[hltv-wrapper] port ${PORT} not bound after ${STARTUP_GRACE}s — terminating so systemd can restart" >&2
    [ -n "${pid:-}" ] && { kill -TERM "$pid" 2>/dev/null; sleep 2; kill -KILL "$pid" 2>/dev/null; }
    kill -TERM "$PIPELINE" 2>/dev/null
) &

wait "$PIPELINE"
rc=$?
# Non-zero propagates to systemd, which restarts. Previously the wrapper could
# only ever end when someone intervened.
exit "$rc"
