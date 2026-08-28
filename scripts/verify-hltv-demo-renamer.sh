#!/bin/bash
# Verify the hltv-demo-renamer guards are LIVE, not merely installed.
# Run as root on the data server. Read-only: changes nothing, restarts nothing.
#
#   /usr/local/bin/verify-hltv-demo-renamer.sh
#
# Exits non-zero if any check fails.
#
# Why this exists: on 2026-08-25 the renamer wedged on a half-open SSH session
# and sat "active" for 53h while every match demo in the window went unrenamed
# and was purged by the 6h cleanup. Four controls -- Restart=on-failure,
# OnFailure=, the health check's CRITICAL_SERVICES, and the cleanup interlock --
# were all keyed on `systemctl is-active`, and a hung process is active. The
# guards added in KTPInfrastructure#179/#180 are only worth anything if they are
# actually in effect, and "the file is on disk" does not establish that.

set -uo pipefail

UNIT=hltv-demo-renamer.service
STATE=/var/lib/hltv-demo-renamer/state.json
CLEANUP=/usr/local/bin/ktp-demo-cleanup-auto.sh
HEALTH=/usr/local/bin/ktp-data-server-health.sh
READ_STALE_SEC="${READ_STALE_SEC:-1800}"
STATE_STALE_SEC="${STATE_STALE_SEC:-900}"

fails=0
check() {  # description, condition-already-evaluated as $2 = "y"/"n", detail
    if [ "$2" = "y" ]; then
        printf '  [PASS] %-52s %s\n' "$1" "${3:-}"
    else
        printf '  [FAIL] %-52s %s\n' "$1" "${3:-}"
        fails=$((fails + 1))
    fi
}
yn() { if [ "$1" = "0" ] || [ "$1" = "true" ]; then echo y; else echo n; fi; }

echo "=== unit configuration ==="
state=$(systemctl is-active "$UNIT" 2>/dev/null || true)
# Type=notify means systemd reports active ONLY after the process sends READY=1,
# so this single word also proves the sd_notify path works end to end.
check "unit active (Type=notify => READY=1 was received)" \
      "$([ "$state" = "active" ] && echo y || echo n)" "$state"

t=$(systemctl show "$UNIT" -p Type --value 2>/dev/null || true)
check "Type=notify" "$([ "$t" = "notify" ] && echo y || echo n)" "$t"

wd=$(systemctl show "$UNIT" -p WatchdogUSec --value 2>/dev/null || true)
case "$wd" in
    ""|0|infinity) wdok=n ;;
    *)             wdok=y ;;
esac
check "WatchdogSec set (kills a loop that stops progressing)" "$wdok" "$wd"

rs=$(systemctl show "$UNIT" -p Restart --value 2>/dev/null || true)
check "Restart=always" "$([ "$rs" = "always" ] && echo y || echo n)" "$rs"

echo
echo "=== script guards present ==="
for pat in set_keepalive settimeout "sd_notify" "except socket.timeout" last_read_ok; do
    n=$(grep -c -- "$pat" /usr/local/bin/hltv-demo-renamer.py 2>/dev/null || echo 0)
    check "renamer carries: $pat" "$([ "$n" -gt 0 ] && echo y || echo n)" "x$n"
done
# The stat handler must catch socket.timeout ABOVE FileNotFoundError:
# socket.timeout subclasses OSError, so a lower clause would file a wedged
# session as "log absent" and skip the port silently, forever.
to_line=$(grep -n 'except socket.timeout' /usr/local/bin/hltv-demo-renamer.py 2>/dev/null | head -1 | cut -d: -f1)
fnf_line=$(grep -n 'except FileNotFoundError' /usr/local/bin/hltv-demo-renamer.py 2>/dev/null | head -1 | cut -d: -f1)
if [ -n "$to_line" ] && [ -n "$fnf_line" ]; then
    check "timeout handler ordered above FileNotFoundError" \
          "$([ "$to_line" -lt "$fnf_line" ] && echo y || echo n)" "L$to_line < L$fnf_line"
else
    check "timeout handler ordered above FileNotFoundError" n "handler(s) missing"
fi

echo
echo "=== liveness: is the poll loop doing work? ==="
if [ ! -f "$STATE" ]; then
    check "state.json exists" n "$STATE"
else
    age=$(( $(date +%s) - $(stat -c %Y "$STATE") ))
    check "state.json fresh (loop is completing cycles)" \
          "$([ "$age" -le "$STATE_STALE_SEC" ] && echo y || echo n)" "${age}s old"

    # Liveness is NOT reading: the loop can iterate while every SSH session
    # fails, rewriting state.json on schedule and so looking healthy to the
    # watchdog and the mtime check alike, while seeing no match window at all.
    read_out=$(python3 - "$STATE" "$READ_STALE_SEC" <<'PY' 2>/dev/null || echo "ERROR unreadable"
import json, sys, time
try:
    stamps = json.load(open(sys.argv[1])).get("last_read_ok", {})
except Exception as e:
    print("ERROR %s" % type(e).__name__); raise SystemExit
if not stamps:
    print("ERROR no-last_read_ok"); raise SystemExit
now, limit = time.time(), int(sys.argv[2])
stale = sorted(r for r, t in stamps.items() if now - t > limit)
print("STALE %s" % ",".join(stale) if stale else "OK %d hosts" % len(stamps))
PY
)
    check "every game host read recently (liveness != reading)" \
          "$(case "$read_out" in OK*) echo y ;; *) echo n ;; esac)" "$read_out"
fi

echo
echo "=== cleanup interlock ==="
bash -n "$CLEANUP" 2>/dev/null && cn=y || cn=n
check "cleanup script parses" "$cn"
n=$(grep -c last_read_ok "$CLEANUP" 2>/dev/null || echo 0)
check "cleanup requires a clean read before deleting" \
      "$([ "$n" -gt 0 ] && echo y || echo n)" "x$n"
# DRY_RUN changes nothing. A healthy system must NOT report SKIPPED here -- if it
# does, the interlock is stuck on and demos will pile up instead of being filed.
dry=$(DRY_RUN=1 "$CLEANUP" 2>&1 | tail -1)
check "interlock passes when healthy" \
      "$(case "$dry" in *SKIPPED*) echo n ;; *) echo y ;; esac)" "$(echo "$dry" | cut -c1-70)"

echo
echo "=== health-check legs ==="
for pat in 'hltv-demo-renamer=wedged' 'hltv-demo-renamer-read' 'ktp-demo-publish.timer'; do
    n=$(grep -c -- "$pat" "$HEALTH" 2>/dev/null || echo 0)
    check "health check reports: $pat" "$([ "$n" -gt 0 ] && echo y || echo n)" "x$n"
done

echo
echo "=== recent runtime ==="
log=$(journalctl -u "$UNIT" -n 200 --no-pager -o cat 2>/dev/null || true)
check "no traceback in recent log" \
      "$(echo "$log" | grep -q Traceback && echo n || echo y)"
hosts=$(echo "$log" | grep -c 'SSH connected' || true)
check "hosts connected since start" "$([ "${hosts:-0}" -gt 0 ] && echo y || echo n)" "${hosts:-0}"
# A failed `mv` never consumes its source, so a leftover .new is the durable
# evidence of a partial deploy.
stray=$(ls /usr/local/bin/*.new /etc/systemd/system/*.new 2>/dev/null | wc -l)
check "no stray .new files (partial-deploy evidence)" \
      "$([ "$stray" -eq 0 ] && echo y || echo n)" "$stray"

echo
echo "=============================================================="
if [ "$fails" -gt 0 ]; then
    echo "RESULT: $fails check(s) FAILED"
    exit 1
fi
echo "RESULT: all guards verified live."
exit 0
