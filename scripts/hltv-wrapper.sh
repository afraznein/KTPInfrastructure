#!/bin/bash
# HLTV wrapper — feeds remote commands in via a FIFO, and refuses to sit on a
# proxy that never came up.
# Usage: hltv-wrapper.sh <port>   (invoked by hltv@<port>.service)
#
# WHY THIS IS NOT JUST `tail -f | hltv`
# On 2026-08-10 hltv@27035 hit `Proxy::Init: Could not create proxy port 27020`,
# printed `*** STOPPING SYSTEM ***` — and did not exit. It sat at the HLTV
# console prompt for 9h48m, because its stdin is this FIFO and `tail -f` never
# EOFs. systemd had a live PID throughout and reported `active (running)`, so
# `Restart=always` never fired. The 12man played on NY 1 that evening was never
# recorded.
#
# WHY THIS WATCHES THE SOCKET AND NOT THE OUTPUT
# Grepping HLTV's output for the FATAL cannot work: HLTV block-buffers into the
# pipe, so the FATAL did not reach the journal until teardown — every line of
# that block carries the identical timestamp 20:48:11.733145. A detector reading
# that stream is blind for exactly as long as the operator was. `stdbuf` cannot
# rescue it either: hltv is 32-bit and the system libstdbuf.so is 64-bit, so it
# fails `wrong ELF class: ELFCLASS64` and is silently ignored.
#
# WHY hltv IS A DIRECT CHILD AND NOT THE MIDDLE OF A PIPELINE
# The first attempt ran `tail -f "$PIPE" | hltv | grep`, so `$!` named **grep**,
# not the proxy. Its gate detected the failure correctly and then could not act
# on it: it killed the proxy, but the wrapper stayed blocked in `wait` on a
# pipeline that never collapsed, and systemd saw nothing. Holding the FIFO open
# on fd 3 gives the same never-EOF stdin with hltv as a direct child, so the
# gate can terminate the wrapper itself.
#
# The FIFO is load-bearing: KTPHLTVRecorder drives `record` / `stoprecording`
# through it. Do not remove it to "fix" stdin.
#
# Gated by tests/hltv_gate/gate-harness.sh — healthy / wedged / wrong-port /
# FIFO-delivery, against fake proxies in /tmp. Run it before changing anything
# here; the previous version passed inspection and failed all three gate cases.
set -u

PORT=$1
PIPE="${HLTV_PIPE_DIR:-/home/hltvserver/cmdpipes}/hltv-${PORT}.pipe"
HLTV="${HLTV_BIN:-/home/hltvserver/hlds/hltv}"
CONFIG="configs/hltv-${PORT}.cfg"
DIAG="${HLTV_DIAG:-/var/log/ktp-hltv-fatal.log}"
STARTUP_GRACE=${STARTUP_GRACE:-45}   # a healthy proxy binds in ~1s
GATE_RC=75                           # distinct from any hltv exit code
SELF=$$

# A stale REGULAR file at the pipe path makes mkfifo fail, and the reader then
# follows a plain file — commands silently never reach HLTV.
if [ -e "$PIPE" ] && [ ! -p "$PIPE" ]; then rm -f "$PIPE"; fi
[ -p "$PIPE" ] || mkfifo "$PIPE"

# Read-write open never EOFs, which is the one thing `tail -f` was here for.
exec 3<>"$PIPE"

"$HLTV" -game dod -port "$PORT" +exec "$CONFIG" <&3 \
    > >(grep -v --line-buffered 'WARNING! System::RunFrame: system time difference') 2>&1 &
HLTV_PID=$!

cleanup() {
    trap - TERM INT USR1 EXIT
    kill -TERM "$HLTV_PID" 2>/dev/null
    # A wedged proxy ignores TERM; it must not outlive the wrapper still holding
    # the port, or the restart races its own corpse.
    ( sleep 3; kill -KILL "$HLTV_PID" 2>/dev/null ) &
}

# USR1 is the gate, deliberately not TERM: systemd sends TERM on an ordinary
# `stop`, and exiting GATE_RC there would report a clean stop as a failure.
trap 'cleanup; exit "$GATE_RC"' USR1
trap 'cleanup; exit 143' TERM INT

bound_by_proxy() {
    # "Is OUR proxy listening", not "is anything listening". A bare port check
    # passes when some *other* process holds the port — which is both the
    # 2026-08-10 scenario (hltv went for 27020, already held by Atlanta 1) and
    # the reason an induced-failure test on an occupied port read as healthy and
    # proved nothing.
    ss -lunpH 2>/dev/null | awk -v want=":${PORT}\$" -v pid="pid=${HLTV_PID}," '
        $4 ~ want && index($0, pid) { found = 1 }
        END { exit !found }'
}

# ---------------------------------------------------------------- startup gate
(
    for _ in $(seq "$STARTUP_GRACE"); do
        sleep 1
        bound_by_proxy && exit 0
        # Died on its own: `wait` below already has it, nothing to escalate.
        kill -0 "$HLTV_PID" 2>/dev/null || exit 0
    done

    # Capture argv BEFORE killing. Why the 2026-08-10 bind targeted 27020 when
    # -port said 27035 is still unexplained, precisely because the wedged
    # process's argv was gone by the time anyone looked.
    {
        echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') port=${PORT} NOT BOUND after ${STARTUP_GRACE}s"
        if [ -r "/proc/$HLTV_PID/cmdline" ]; then
            printf '    argv : '; tr '\0' ' ' < "/proc/$HLTV_PID/cmdline"; echo
            printf '    cwd  : '; readlink "/proc/$HLTV_PID/cwd" 2>/dev/null || echo '?'
        else
            echo "    (proxy pid $HLTV_PID already gone)"
        fi
        echo "    bound in range: $(ss -lunH 2>/dev/null | awk '{print $4}' |
                                    grep -oE '270[0-9][0-9]$' | sort -u | tr '\n' ' ')"
    } >> "$DIAG" 2>/dev/null

    echo "[hltv-wrapper] port ${PORT} not bound after ${STARTUP_GRACE}s — terminating so systemd can restart" >&2
    kill -USR1 "$SELF" 2>/dev/null
) &
GATE_PID=$!

wait "$HLTV_PID"
rc=$?
kill -TERM "$GATE_PID" 2>/dev/null
exit "$rc"
