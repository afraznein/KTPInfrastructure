#!/usr/bin/env bash
# Exercise ktp-tier2-heartbeat's state machine. Every dependency is stubbed in a
# temp dir -- marker, drift checker, relay, jq -- so this needs no network, no
# data server, and posts nothing to Discord.
#
# It exists because the heartbeat is the thing that reports silence, and it went
# silent itself: the suite was red 2026-08-04..07 and a red run also switched off
# the stack-drift tripwire it gates. Cases 2, 3 and 5 are that bug and its
# neighbours. Run it against the DEPLOYED copy as well as the repo one -- the
# deploy had drifted four weeks behind the repo, which is how the re-alert fix
# sat written-but-not-running:
#
#   ./test-tier2-heartbeat.sh ./ktp-tier2-heartbeat.sh          # repo   -> 20/20
#   ./test-tier2-heartbeat.sh /usr/local/bin/ktp-tier2-heartbeat.sh   # deployed
set -uo pipefail
HB="${1:?path to ktp-tier2-heartbeat.sh}"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT

mkdir -p "$T/bin"
# stub "aggregator python": runs the stub checker, exits with its code
cat > "$T/bin/py" <<'EOF'
#!/usr/bin/env bash
exec "$1"
EOF
chmod +x "$T/bin/py"
: > "$T/agg.env"

# jq stub — the script uses exactly two shapes, and Git Bash ships no jq.
cat > "$T/bin/jq" <<'EOF'
#!/usr/bin/env python
import json, sys
a = sys.argv[1:]
if "-n" in a:                                   # build: -n --arg k v ... '<shape>'
    out, i = {}, 0
    while i < len(a):
        if a[i] in ("--arg", "--argjson"):
            v = a[i + 2]
            out[a[i + 1]] = json.loads(v) if a[i] == "--argjson" else v
            i += 3
        else:
            i += 1
    print(json.dumps({"channelId": out.get("ch"), "embeds": [{
        "title": out.get("title"), "description": out.get("desc"),
        "color": out.get("color"), "footer": {"text": out.get("footer")}}]}))
    sys.exit(0)
filt = a[a.index("-r") + 1] if "-r" in a else a[-2]
path = a[-1]
key = filt.split("//")[0].strip().lstrip(".")
dflt = filt.split("//")[1].strip().strip('"') if "//" in filt else ""
try:
    print(json.load(open(path)).get(key, dflt))
except Exception:
    print(dflt)
EOF
chmod +x "$T/bin/jq"

mk_checker() {  # $1 = exit code, $2 = message
    cat > "$T/checker" <<EOF
#!/usr/bin/env bash
echo "$2"
exit $1
EOF
    chmod +x "$T/checker"
}
mk_marker() {   # $1 = outcome, $2 = age seconds
    printf '{"ts": %s, "outcome": "%s", "run_id": "R1", "event": "schedule"}' \
        "$(( $(date +%s) - $2 ))" "$1" > "$T/marker"
}

run_hb() {      # env: STATE preloaded by caller
    KTP_RELAY_CONFIG="$T/relay.conf" \
    KTP_TIER2_MARKER="$T/marker" \
    KTP_TIER2_HEARTBEAT_STATE="$T/state" \
    KTP_TIER2_DRIFT_CHECKER="$T/checker" \
    KTP_AGGREGATOR_ENV="$T/agg.env" \
    KTP_AGGREGATOR_PY="$T/bin/py" \
    PATH="$T/bin:$PATH" \
    bash "$HB" 2>&1
}

# relay conf with a curl stub so nothing leaves the box
cat > "$T/relay.conf" <<EOF
RELAY_URL="http://127.0.0.1:1/relay"
AUTH_SECRET="stub"
EOF
cat > "$T/bin/curl" <<EOF
#!/usr/bin/env bash
# emulate curl -w '%{http_code}': echo the code the test asked for
cat > "$T/last-payload.json" <<< "\$(printf '%s' "\${@: -1}")"
printf '%s' "\$(cat "$T/http_code" 2>/dev/null || echo 200)"
EOF
chmod +x "$T/bin/curl"
echo 200 > "$T/http_code"

pass=0; fail=0
check() { # $1 label, $2 expected-substring, $3 actual
    if [[ "$3" == *"$2"* ]]; then echo "  ok   $1"; pass=$((pass+1));
    else echo "  FAIL $1"; echo "        want: $2"; echo "        got : $3"; fail=$((fail+1)); fi
}

echo "== 1. green run, no drift =="
mk_marker success 3600; mk_checker 0 "runner stack in sync"; rm -f "$T/state"
out="$(run_hb)"; check "alerts ok on first sight" "-> ok" "$out"
check "state file records ok" "ok|" "$(cat "$T/state")"
out="$(run_hb)"; check "silent while still ok" "state=ok (unchanged)" "$out"

echo "== 2. THE BUG: drift while the run is RED must still be detected =="
mk_marker failure 3600; mk_checker 1 "runner stack DRIFTED: engine_i486.so"; rm -f "$T/state"
out="$(run_hb)"
check "headline still leads with the failure" "last run failed" "$(cat "$T/last-payload.json")"
check "drift carried in the body anyway"      "Stack drift too" "$(cat "$T/last-payload.json")"
check "state key records both"                "failed+drift|" "$(cat "$T/state")"

echo "== 3. drift ARRIVING during an already-red run is its own edge =="
mk_marker failure 3600; mk_checker 0 "in sync"; rm -f "$T/state"
run_hb >/dev/null                                   # first: failed, no drift
before="$(cat "$T/state")"
mk_checker 1 "runner stack DRIFTED: dodx"
out="$(run_hb)"
check "not swallowed as unchanged" "failed -> failed+drift" "$out"
check "state advanced"             "failed+drift|"          "$(cat "$T/state")"
check "prev was plain failed"      "failed|"                "$before"

echo "== 4. persistent failure re-alerts on the slow cadence =="
mk_marker failure 3600; mk_checker 0 "in sync"; rm -f "$T/state"
run_hb >/dev/null
out="$(run_hb)"; check "quiet inside the window" "(unchanged, last alert" "$out"
printf 'failed|%s' "$(( $(date +%s) - 90000 ))" > "$T/state"
out="$(run_hb)"; check "re-alerts after 25h" "STILL DOWN" "$(cat "$T/last-payload.json")"

echo "== 5. a dropped relay post must NOT consume the edge =="
mk_marker failure 3600; mk_checker 0 "in sync"; rm -f "$T/state"
echo 500 > "$T/http_code"
out="$(run_hb)"; check "says it will retry" "NOT advanced" "$out"
check "state file untouched" "" "$(cat "$T/state" 2>/dev/null || echo '')"
[ -s "$T/state" ] && { echo "  FAIL state file was written on a failed post"; fail=$((fail+1)); } \
                  || { echo "  ok   state file was not written on a failed post"; pass=$((pass+1)); }
echo 200 > "$T/http_code"
out="$(run_hb)"; check "edge survives to the next run" "-> failed" "$out"

echo "== 5b. a green-but-drifted run must SAY the suite passed =="
# failed -> drift never passes through ok, so without this line the embed reads
# as "still broken" to anyone who watched the red spell.
mk_marker failure 3600; mk_checker 1 "runner stack DRIFTED: engine_i486.so"; rm -f "$T/state"
out="$(run_hb)"                                   # red + drift -> state failed+drift
mk_marker success 3600                            # suite recovers, drift remains
out="$(run_hb)"
check "state advances to drift"       "-> drift" "$out"
check "embed says the suite passed"   "The suite ran and passed" "$(cat "$T/last-payload.json")"
check "and still names the drift"     "re-sync the runner stack" "$(cat "$T/last-payload.json")"

echo "== 6. inconclusive drift check never flaps the state =="
mk_marker success 3600; mk_checker 2 "ssh timeout"; rm -f "$T/state"
out="$(run_hb)"; check "logged, not alerted" "drift check inconclusive" "$out"
check "state stays ok" "ok|" "$(cat "$T/state")"

echo "== 7. legacy bare state file re-alerts once after upgrade =="
mk_marker failure 3600; mk_checker 0 "in sync"
printf 'failed' > "$T/state"
out="$(run_hb)"; check "treats bare state as never-alerted" "STILL DOWN" "$(cat "$T/last-payload.json")"

echo "== 8. stale marker (runner dead) =="
mk_marker success 200000; mk_checker 0 "in sync"; rm -f "$T/state"
out="$(run_hb)"; check "reports not running" "not running" "$(cat "$T/last-payload.json")"

echo "== 9. recovery from red =="
mk_marker success 3600; mk_checker 0 "in sync"
printf 'failed|%s' "$(date +%s)" > "$T/state"
out="$(run_hb)"; check "recovered embed" "recovered" "$(cat "$T/last-payload.json")"

echo "== 10. a non-success outcome that is not the literal 'failure' =="
# The 2026-08-09/10 blind spot. The suite wedged in teardown, GitHub killed the
# job at its 30m ceiling, and the workflow wrote outcome="cancelled". The old
# `= "failure"` test matched none of it, so the heartbeat reported OK on two
# consecutive mornings while the suite had not completed once. Every case above
# uses success/failure only, which is exactly why nothing caught this.
for bad in cancelled timed_out unknown ""; do
    mk_marker "$bad" 3600; mk_checker 0 "in sync"; rm -f "$T/state"
    out="$(run_hb)"
    check "outcome '${bad:-<empty>}' is unhealthy" "failed" "$(cat "$T/state")"
done
# Control: the allowlist must still let a real success through, or "everything
# is unhealthy" would pass this block for the wrong reason.
mk_marker success 3600; mk_checker 0 "in sync"; rm -f "$T/state"
out="$(run_hb)"; check "control: success is still ok" "ok|" "$(cat "$T/state")"

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
