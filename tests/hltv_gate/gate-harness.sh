#!/bin/bash
# Reproduction harness for the hltv-wrapper startup gate.
#
# Runs entirely in /tmp with fake hltv binaries on unused ports. Touches no
# systemd unit, no live wrapper, no proxy. Measures the WRAPPER's own exit
# code -- the earlier attempt read `tail`'s status and proved nothing.
set -u

BASE=/tmp/ktp-hltv-gate-test
WRAPPER=${1:?usage: gate-harness.sh <wrapper-under-test>}
GRACE=${GRACE:-8}
PORT_OK=29901      # scenario ports; asserted free below
PORT_SQUAT=29902
PORT_FIFO=29903

mkdir -p "$BASE/cmdpipes" "$BASE/logs"
rm -f "$BASE/logs"/*.log

# --------------------------------------------------------------- preconditions
for p in $PORT_OK $PORT_SQUAT $PORT_FIFO; do
    if ss -lunH | awk '{print $4}' | grep -qE "[:.]$p\$"; then
        echo "ABORT: test port $p is already in use"; exit 2
    fi
done

# ------------------------------------------------------------- fake hltv modes
# healthy  : binds its own port, then consumes stdin forever (like a live proxy)
# wedged   : binds NOTHING, prints the FATAL, consumes stdin forever -- the
#            2026-08-10 state that systemd reported as active(running)
# wrongport: its port is held by a squatter, so it binds nothing and wedges --
#            the actual incident, where 27035 went for 27020
cat > "$BASE/fake-hltv" <<'FAKE'
#!/bin/bash
# `exec` so the binding process IS the wrapper's direct child. Verified against
# the live fleet: for every real proxy the socket-owning pid is `hltv` with
# ppid == the wrapper, so a fake that binds in a CHILD is unfaithful -- it made
# a correct wrapper look like it was false-tripping on a healthy proxy.
MODE=$FAKE_MODE
PORT=""
prev=""
for a in "$@"; do
    if [ "$prev" = "-port" ]; then PORT=$a; fi
    prev=$a
done
exec python3 -c '
import socket, sys
mode, port = sys.argv[1], int(sys.argv[2])
sock = None
if mode != "wedged":
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("0.0.0.0", port))
        print("Proxy bound", flush=True)
    except OSError:
        sock = None
if sock is None:
    print("ERROR! Network::CreateSocket: WSAEADDRINUSE.", flush=True)
    print("Proxy::Init: Could not create proxy port %d." % port, flush=True)
    print("*** STOPPING SYSTEM ***", flush=True)
    print("Type \x27help\x27 for a list of commands.", flush=True)
# The wedge: stdin never EOFs, so this never exits -- what made the outage
# invisible to systemd. Echo what arrives so FIFO delivery is observable.
for line in sys.stdin:
    print("CMD:" + line.rstrip("\n"), flush=True)
' "$MODE" "$PORT" ktpfake -port "$PORT"
FAKE
chmod +x "$BASE/fake-hltv"

pass=0; fail=0
verdict() {
    if [ "$1" = PASS ]; then pass=$((pass + 1)); else fail=$((fail + 1)); fi
}

run_case() {
    local name=$1 mode=$2 port=$3 expect=$4
    local pipe="$BASE/cmdpipes/hltv-${port}.pipe"
    local log="$BASE/logs/${name}.log"
    rm -f "$pipe"

    FAKE_MODE=$mode STARTUP_GRACE=$GRACE \
    HLTV_BIN="$BASE/fake-hltv" HLTV_PIPE_DIR="$BASE/cmdpipes" HLTV_DIAG="$BASE/logs/fatal.log" \
        timeout $((GRACE + 12)) "$WRAPPER" "$port" > "$log" 2>&1
    local rc=$? v
    # 124 == the harness timeout killed it, i.e. the wrapper never exited.
    if [ "$expect" = exit ]; then
        if [ $rc -ne 0 ] && [ $rc -ne 124 ]; then v=PASS; else v=FAIL; fi
    else
        if [ $rc -eq 124 ]; then v=PASS; else v=FAIL; fi
    fi
    printf '%-11s mode=%-10s expect=%-5s rc=%-4s %s\n' "$name" "$mode" "$expect" "$rc" "$v"
    [ "$v" = FAIL ] && sed 's/^/      | /' "$log" | tail -4
    verdict "$v"
    pkill -f "ktpfake -port $port" 2>/dev/null
    pkill -f "tail -f $BASE/cmdpipes/hltv-${port}.pipe" 2>/dev/null
}

# The gate is only half the contract. KTPHLTVRecorder drives record /
# stoprecording through this FIFO, so a wrapper that exits correctly but breaks
# command delivery reproduces the original damage by another route.
run_fifo_case() {
    local port=$PORT_FIFO
    local pipe="$BASE/cmdpipes/hltv-${port}.pipe"
    local log="$BASE/logs/fifo.log"
    rm -f "$pipe"

    FAKE_MODE=healthy STARTUP_GRACE=$GRACE \
    HLTV_BIN="$BASE/fake-hltv" HLTV_PIPE_DIR="$BASE/cmdpipes" HLTV_DIAG="$BASE/logs/fatal.log" \
        "$WRAPPER" "$port" > "$log" 2>&1 &
    local wpid=$!
    sleep 3
    echo "record test_demo" > "$pipe"
    echo "stoprecording"    > "$pipe"
    sleep 2

    local v=FAIL
    if grep -q 'CMD:record test_demo' "$log" && grep -q 'CMD:stoprecording' "$log"; then v=PASS; fi
    printf '%-11s mode=%-10s expect=%-5s rc=%-4s %s\n' fifo healthy delivered - "$v"
    [ "$v" = FAIL ] && sed 's/^/      | /' "$log" | tail -6
    verdict "$v"
    kill -TERM $wpid 2>/dev/null; sleep 1; kill -KILL $wpid 2>/dev/null
    pkill -f "ktpfake -port $port" 2>/dev/null
}

echo "=== wrapper under test: $WRAPPER (grace=${GRACE}s) ==="

# Squatter for the wrongport case: hold PORT_SQUAT so the fake cannot bind it.
python3 -c "
import socket, time
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(('0.0.0.0', $PORT_SQUAT))
time.sleep(600)
" &
SQUAT=$!
sleep 1

run_case healthy   healthy   $PORT_OK    stay
run_case wedged    wedged    $PORT_OK    exit
run_case wrongport wrongport $PORT_SQUAT exit
run_fifo_case

kill $SQUAT 2>/dev/null
pkill -f ktpfake 2>/dev/null
echo "=== $pass passed, $fail failed ==="
[ $fail -eq 0 ]
