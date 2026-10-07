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
#   ./test-tier2-heartbeat.sh ./ktp-tier2-heartbeat.sh                # repo
#   ./test-tier2-heartbeat.sh /usr/local/bin/ktp-tier2-heartbeat.sh   # deployed
#
# Exit status is the verdict; the printed tally is not a target to match. It
# used to say "-> 20/20" here, which stopped being true the moment a case was
# added, and a stale number reads as a failing suite.
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
#
# Only installed where jq is genuinely missing. It goes on the front of PATH, so
# installing it unconditionally SHADOWS a real jq — and its `python` shebang does
# not resolve on the data server, which has python3 only. That combination made
# every case fail there, including the control, on the one box whose whole
# purpose is validating the DEPLOYED copy (see the invocation note at the top).
if command -v jq >/dev/null 2>&1; then
    : # real jq on PATH — use it
else
# Pick an interpreter that RUNS, not merely one that resolves: `command -v
# python3` on Windows hits the Microsoft Store shim, which exists, exits 0 for
# `command -v`, and then prints "Python was not found" for every real call.
_PYBIN=""
for _cand in python3 python; do
    if command -v "$_cand" >/dev/null 2>&1 && "$_cand" -c 'import json,sys' >/dev/null 2>&1; then
        _PYBIN="$(command -v "$_cand")"; break
    fi
done
[ -n "$_PYBIN" ] || { echo "no working python for the jq stub, and no real jq"; exit 2; }
printf '#!%s\n' "$_PYBIN" > "$T/bin/jq"
cat >> "$T/bin/jq" <<'EOF'
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
fi

mk_checker() {  # $1 = exit code, $2 = message
    cat > "$T/checker" <<EOF
#!/usr/bin/env bash
echo "$2"
exit $1
EOF
    chmod +x "$T/checker"
}
_write_marker() {  # $1 = path, $2 = outcome, $3 = age seconds
    printf '{"ts": %s, "outcome": "%s", "run_id": "R1", "event": "schedule"}' \
        "$(( $(date +%s) - $3 ))" "$2" > "$1"
}
# Both legs by default: the script watches two markers, so a case that stages
# only `main` is really testing "main X, preprod never ran" -- which is a
# different case, and the one case 11 covers deliberately.
mk_marker() {   # $1 = outcome, $2 = age seconds
    _write_marker "$T/marker" "$1" "$2"
    _write_marker "$T/marker-preprod" success 3600
}
mk_marker_preprod() {  # $1 = outcome, $2 = age seconds
    _write_marker "$T/marker-preprod" "$1" "$2"
}

# `ps` stub: one line per listener the case wants to exist. The script counts
# lines matching the pattern, so the count is what these fixtures control.
mk_listeners() {  # $1 = count, $2 = ppid of the first one (default 4242)
    local n="$1" ppid="${2:-4242}" i
    {
        echo "  PID  PPID COMMAND"
        for i in $(seq 1 "$n"); do
            echo "$((1000 + i)) $ppid /opt/ktp-tier2-runner/actions-runner/bin/Runner.Listener run"
            ppid=1
        done
    } > "$T/ps-out"
}
# Two shapes, one fixture file each: the listener scan (-eo pid,ppid,args) and
# the write gate's parent-name probe (-o comm=). A single fixture would answer the
# gate with the listener table, which is not a cron name, so the gate would read
# "not under cron" for a reason the case never set.
cat > "$T/bin/ps" <<EOF
#!/usr/bin/env bash
case " \$* " in
    *" comm= "*) cat "$T/ps-parent" ;;
    *)           cat "$T/ps-out" ;;
esac
EOF
chmod +x "$T/bin/ps"
mk_listeners 1
mk_parent() { echo "${1:-bash}" > "$T/ps-parent"; }   # what launched us
mk_parent bash

# $1 = KTP_TIER2_HEARTBEAT_WRITE, or "-" to leave it unset; rest = argv.
# `env` so the var can be genuinely ABSENT -- a case that needs the unset default
# cannot express it by assigning an empty string, because the script tells those
# two apart and that is the whole subject of cases 13*.
run_hb_env() {  # env: STATE preloaded by caller
    local w="$1"; shift
    local -a pre
    if [ "$w" = "-" ]; then pre=(env); else pre=(env "KTP_TIER2_HEARTBEAT_WRITE=$w"); fi
    "${pre[@]}" \
    KTP_RELAY_CONFIG="$T/relay.conf" \
    KTP_TIER2_MARKER="$T/marker" \
    KTP_TIER2_MARKER_PREPROD="$T/marker-preprod" \
    KTP_TIER2_HEARTBEAT_STATE="$T/state" \
    KTP_TIER2_DRIFT_CHECKER="$T/checker" \
    KTP_AGGREGATOR_ENV="$T/agg.env" \
    KTP_AGGREGATOR_PY="$T/bin/py" \
    PATH="$T/bin:$PATH" \
    bash "$HB" "$@" 2>&1
}
# The cron-shaped invocation: every case below 13 is about the state machine, and
# the state machine only runs when the write is armed, which is what cron does.
run_hb() { run_hb_env 1 "$@"; }
# What a human gets: no cron env line, no flag.
run_hb_bare() { run_hb_env - "$@"; }
mtime() { stat -c %Y "$1" 2>/dev/null || echo 0; }
# Push the state file into the past so a write shows up as a moved mtime; whole
# -second granularity would otherwise hide a write inside the same second.
backdate_state() { touch -d "@$(( $(date +%s) - 3600 ))" "$T/state"; }

# Rewrite only the timestamp half of whatever key the script wrote. Tests must
# not spell the key format out -- it has changed twice (bare state, then two
# markers) and every literal in here went stale silently when it did.
age_state() {   # $1 = seconds to backdate the last-alert stamp by
    local raw; raw="$(cat "$T/state")"
    printf '%s|%s' "${raw%%|*}" "$(( $(date +%s) - $1 ))" > "$T/state"
}
strip_state_timestamp() { printf '%s' "$(cut -d'|' -f1 < "$T/state")" > "$T/state"; }

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

HEALTHY_MARKER="Tier 2 integration suite healthy"

pass=0; fail=0
check() { # $1 label, $2 expected-substring, $3 actual
    if [[ "$3" == *"$2"* ]]; then echo "  ok   $1"; pass=$((pass+1));
    else echo "  FAIL $1"; echo "        want: $2"; echo "        got : $3"; fail=$((fail+1)); fi
}

echo "== 1. green run, no drift =="
mk_marker success 3600; mk_checker 0 "runner stack in sync"; rm -f "$T/state"
out="$(run_hb)"; check "alerts ok on first sight" "$HEALTHY_MARKER" "$(cat "$T/last-payload.json")"
check "state file records ok" "main=ok" "$(cat "$T/state")"
out="$(run_hb)"; check "silent while still ok" "state=ok (unchanged)" "$out"

echo "== 2. THE BUG: drift while the run is RED must still be detected =="
mk_marker failure 3600; mk_checker 1 "runner stack DRIFTED: engine_i486.so"; rm -f "$T/state"
out="$(run_hb)"
check "headline still leads with the failure" "a leg failed" "$(cat "$T/last-payload.json")"
check "drift carried in the body anyway"      "Stack drift too" "$(cat "$T/last-payload.json")"
check "state key records the failure"         "main=failed" "$(cat "$T/state")"
check "state key records the drift"           "drift=1"     "$(cat "$T/state")"

echo "== 3. drift ARRIVING during an already-red run is its own edge =="
mk_marker failure 3600; mk_checker 0 "in sync"; rm -f "$T/state"
run_hb >/dev/null                                   # first: failed, no drift
before="$(cat "$T/state")"
mk_checker 1 "runner stack DRIFTED: dodx"
out="$(run_hb)"
check "not swallowed as unchanged" " -> "   "$out"
check "state advanced to include drift" "drift=1" "$(cat "$T/state")"
check "prev had no drift"          "main=failed,preprod=ok,listeners=1|" "$before"

echo "== 4. persistent failure re-alerts on the slow cadence =="
mk_marker failure 3600; mk_checker 0 "in sync"; rm -f "$T/state"
run_hb >/dev/null
out="$(run_hb)"; check "quiet inside the window" "(unchanged, last alert" "$out"
age_state 90000
out="$(run_hb)"; check "re-alerts after 25h" "STILL DOWN" "$(cat "$T/last-payload.json")"

echo "== 5. a dropped relay post must NOT consume the edge =="
mk_marker failure 3600; mk_checker 0 "in sync"; rm -f "$T/state"
echo 500 > "$T/http_code"
out="$(run_hb)"; check "says it will retry" "NOT advanced" "$out"
check "state file untouched" "" "$(cat "$T/state" 2>/dev/null || echo '')"
[ -s "$T/state" ] && { echo "  FAIL state file was written on a failed post"; fail=$((fail+1)); } \
                  || { echo "  ok   state file was not written on a failed post"; pass=$((pass+1)); }
echo 200 > "$T/http_code"
out="$(run_hb)"; check "edge survives to the next run" "-> main=failed" "$out"

echo "== 5b. a green-but-drifted run must SAY the suite passed =="
# failed -> drift never passes through ok, so without this line the embed reads
# as "still broken" to anyone who watched the red spell.
mk_marker failure 3600; mk_checker 1 "runner stack DRIFTED: engine_i486.so"; rm -f "$T/state"
out="$(run_hb)"                                   # red + drift -> state failed+drift
mk_marker success 3600                            # suite recovers, drift remains
out="$(run_hb)"
check "state advances to drift"       "drift=1"  "$(cat "$T/state")"
check "embed says the suite passed"   "Both legs ran and passed" "$(cat "$T/last-payload.json")"
check "and still names the drift"     "re-sync the runner stack" "$(cat "$T/last-payload.json")"

echo "== 6. inconclusive drift check never flaps the state =="
mk_marker success 3600; mk_checker 2 "ssh timeout"; rm -f "$T/state"
out="$(run_hb)"; check "logged, not alerted" "drift check inconclusive" "$out"
check "state stays ok" "main=ok" "$(cat "$T/state")"

echo "== 7. legacy bare state file re-alerts once after upgrade =="
mk_marker failure 3600; mk_checker 0 "in sync"; rm -f "$T/state"
run_hb >/dev/null
strip_state_timestamp
out="$(run_hb)"; check "treats bare state as never-alerted" "STILL DOWN" "$(cat "$T/last-payload.json")"
check "and says why it cannot date it" "No previous alert on record" "$(cat "$T/last-payload.json")"

echo "== 8. stale marker (runner dead) =="
mk_marker success 200000; mk_checker 0 "in sync"; rm -f "$T/state"
out="$(run_hb)"; check "reports not running" "not running" "$(cat "$T/last-payload.json")"

echo "== 9. recovery from red =="
mk_marker failure 3600; mk_checker 0 "in sync"; rm -f "$T/state"
run_hb >/dev/null
mk_marker success 3600
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
out="$(run_hb)"; check "control: success is still ok" "main=ok" "$(cat "$T/state")"

echo "== 11. a leg that has NEVER run is named, not folded into the other =="
mk_marker success 3600; mk_checker 0 "in sync"; rm -f "$T/marker-preprod" "$T/state"
out="$(run_hb)"
check "preprod named by name"     "preprod: no run marker" "$(cat "$T/last-payload.json")"
check "and main still reported ok" "main: healthy"          "$(cat "$T/last-payload.json")"
check "worst-of drives the bucket" "preprod=stale"          "$(cat "$T/state")"

echo "== 12. A RE-PARENTED LISTENER SURVIVES A SERVICE RESTART — two answer one job =="
# The 2026-09-03 incident. `systemctl restart` reaches only the unit's cgroup,
# so the Aug-31 orphan on PPID 1 kept listening; the systemd worker lost a race
# on _diag/pages, exited 102 in 2s, and the job log blamed a 403 on an innocent
# PR. Nothing upstream of the count sees this: the unit is active, the markers
# are fresh, and the stack is in sync.
mk_marker success 3600; mk_checker 0 "in sync"; mk_listeners 2; rm -f "$T/state"
out="$(run_hb)"
p="$(cat "$T/last-payload.json")"
check "headline names the duplicate"   "DUPLICATE runner listener" "$p"
check "says how many are running"      "**2** running"             "$p"
check "names PPID 1 as the tell"       "PPID 1"                    "$p"
check "shows the offending processes"  "Runner.Listener run"       "$p"
check "count is in the state key"      "listeners=2"               "$(cat "$T/state")"

echo "== 12b. the duplicate OUTRANKS a failed leg — it is the cause, not a peer =="
# A duplicate listener manufactures the failure the marker reports. Leading with
# "a leg failed" is what sent the last investigation at the PR under the job.
mk_marker failure 3600; mk_checker 1 "runner stack DRIFTED: dodx"; mk_listeners 2; rm -f "$T/state"
out="$(run_hb)"
p="$(cat "$T/last-payload.json")"
check "duplicate is the headline"      "DUPLICATE runner listener" "$p"
check "the failed leg still rides along" "did not succeed"         "$p"
check "so does the drift"              "Stack drift too"           "$p"

echo "== 12c. ZERO listeners is the other direction, and 36h earlier than the marker =="
mk_marker success 3600; mk_checker 0 "in sync"; mk_listeners 0; rm -f "$T/state"
out="$(run_hb)"
p="$(cat "$T/last-payload.json")"
check "headline names the absence"     "no runner listener" "$p"
check "says nothing is listening"      "nothing is listening for jobs" "$p"
check "markers are still green"        "main: healthy"      "$p"

echo "== 12d. control: the expected count is not 'any count' =="
# Without this, "everything alerts" would pass 12/12b/12c for the wrong reason.
mk_marker success 3600; mk_checker 0 "in sync"; mk_listeners 1; rm -f "$T/state"
out="$(run_hb)"
check "exactly one is healthy"     "$HEALTHY_MARKER" "$(cat "$T/last-payload.json")"
check "and the count is reported"  "listeners: 1" "$(cat "$T/last-payload.json")"

echo "== 12e. a listener count returning to normal RE-ALERTS as recovered =="
mk_marker success 3600; mk_checker 0 "in sync"; mk_listeners 2; rm -f "$T/state"
run_hb >/dev/null
mk_listeners 1
out="$(run_hb)"
check "recovery is announced" "recovered" "$(cat "$T/last-payload.json")"

echo "== 12f. watching can be turned off without pretending the count is 1 =="
mk_marker success 3600; mk_checker 0 "in sync"; mk_listeners 2; rm -f "$T/state"
out="$(KTP_TIER2_WATCH_LISTENERS=0 run_hb)"
check "not watched, so no alert" "$HEALTHY_MARKER" "$(cat "$T/last-payload.json")"
check "and the body says so"     "not watched" "$(cat "$T/last-payload.json")"

echo "== 12g. a second registered runner is expressible as config, not a code edit =="
mk_marker success 3600; mk_checker 0 "in sync"; mk_listeners 2; rm -f "$T/state"
out="$(KTP_TIER2_EXPECTED_LISTENERS=2 run_hb)"
check "two is healthy when two are expected" "$HEALTHY_MARKER" "$(cat "$T/last-payload.json")"
mk_listeners 1
out="$(KTP_TIER2_EXPECTED_LISTENERS=2 run_hb)"
check "and one is then the fault" "no runner listener" "$(cat "$T/last-payload.json")"
mk_listeners 1

echo "== 13. A BARE RUN MUST NOT MOVE THE ALERTER'S EDGE =="
# Running this by hand recomputes the verdict under an environment the cron run
# never had: cron env lines reach only cron's own child, so KTP_TIER2_WATCH_PREPROD=0
# is back at its default of 1 and the retired leg re-engages. Saving that is the
# fault. The alerter keys on transitions, so a stored verdict for a program nobody
# is running can mask the next real change as a return to normal.
mk_marker success 3600; mk_checker 0 "in sync"; mk_parent bash
rm -f "$T/marker-preprod" "$T/state"                 # retired leg: marker frozen
KTP_TIER2_WATCH_PREPROD=0 run_hb >/dev/null          # cron's own verdict, armed
armed_state="$(cat "$T/state")"; armed_key="${armed_state%%|*}"   # the file keeps a stamp too
backdate_state; was="$(mtime "$T/state")"
# Cleared BEFORE the one bare run under test. Checking a second bare run instead
# reads the unchanged-key early exit, which posts nothing even when the gate is
# missing -- so that assertion passed in both directions and proved nothing.
rm -f "$T/last-payload.json"
out="$(run_hb_bare)"                                 # now by hand, no cron env
check "says it is a dry run"            "DRY RUN"       "$out"
check "and prints the verdict anyway"   "this run   : " "$out"
check "names the stored key it read"    "$armed_key"    "$out"
check "the re-engaged leg shows in it"  "preprod=stale" "$out"
if [ "$(mtime "$T/state")" = "$was" ]; then echo "  ok   state file mtime did not move"; pass=$((pass+1));
else echo "  FAIL state file mtime moved on a bare run"; fail=$((fail+1)); fi
check "state file is untouched"        "$armed_state"  "$(cat "$T/state")"
if [ -f "$T/last-payload.json" ]; then echo "  FAIL a bare run posted to the relay"; fail=$((fail+1));
else echo "  ok   nothing was posted"; pass=$((pass+1)); fi

echo "== 13b. the other direction: an armed run still writes and still posts =="
# Same fixtures, same second. Without this, case 13 passes for a script that
# writes nothing ever, which is a broken alerter rather than a safe one.
mk_marker failure 3600; mk_checker 0 "in sync"; mk_parent bash; rm -f "$T/state"
run_hb >/dev/null; backdate_state; was="$(mtime "$T/state")"
mk_marker success 3600
out="$(run_hb)"
if [ "$(mtime "$T/state")" != "$was" ]; then echo "  ok   state file mtime moved on an armed run"; pass=$((pass+1));
else echo "  FAIL armed run did not write the state file"; fail=$((fail+1)); fi
check "state advanced"      "main=ok"   "$(cat "$T/state")"
check "and it posted"       "recovered" "$(cat "$T/last-payload.json")"

echo "== 13c. --write arms an interactive run explicitly =="
# The unsafe thing has to be askable for, or the next operator edits the script.
mk_marker failure 3600; mk_checker 0 "in sync"; mk_parent bash; rm -f "$T/state"
out="$(run_hb_bare --write)"
check "no dry-run banner"   "a leg failed" "$(cat "$T/last-payload.json")"
check "state was written"   "main=failed"  "$(cat "$T/state" 2>/dev/null || echo MISSING)"

echo "== 13d. --dry-run refuses even when the cron env says write =="
mk_marker failure 3600; mk_checker 0 "in sync"; mk_parent bash; rm -f "$T/state"
out="$(run_hb --dry-run)"
check "flag beats the env" "DRY RUN" "$out"
if [ -e "$T/state" ]; then echo "  FAIL --dry-run wrote the state file"; fail=$((fail+1));
else echo "  ok   --dry-run created no state file"; pass=$((pass+1)); fi

echo "== 13e. a cron PARENT arms it, so a stale /etc/cron.d copy is not silence =="
# The deployed cron file has drifted weeks behind this repo before. Arming on the
# env line alone would turn that drift into a watcher that never writes, which is
# the failure this whole script exists to report.
mk_marker failure 3600; mk_checker 0 "in sync"; rm -f "$T/state"
mk_parent cron
out="$(run_hb_bare)"
check "cron parent is armed" "main=failed" "$(cat "$T/state" 2>/dev/null || echo MISSING)"
# Two controls, because "it wrote" on its own only proves the run happened: the
# gate has to be reading the parent NAME and nothing else in the probe's output.
for notcron in bash sshd; do
    mk_parent "$notcron"; rm -f "$T/state"
    out="$(run_hb_bare)"
    check "parent '$notcron' is not armed" "DRY RUN" "$out"
    if [ -e "$T/state" ]; then echo "  FAIL parent '$notcron' wrote state"; fail=$((fail+1));
    else echo "  ok   parent '$notcron' wrote nothing"; pass=$((pass+1)); fi
done
mk_parent bash

echo "== 13f. an unknown flag is refused, not treated as a bare run =="
# A typo'd flag falling through to the default would be the quiet half of this bug
# wearing a different hat.
mk_marker success 3600; mk_checker 0 "in sync"; rm -f "$T/state"
out="$(run_hb_bare --dryrun || true)"
check "usage, not a run" "usage:" "$out"

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
