#!/usr/bin/env bash
# Tier-2 runner off root: runbook TIER2_RUNNER_NONROOT_CUTOVER.md section B, as one guarded script.
#
#   Preflight only (changes nothing):  ssh root@<DATA_SERVER_IP> "bash -s" < scripts/tier2-runner-cutover.sh
#   Cutover:                           ssh root@<DATA_SERVER_IP> "bash -s -- --go" < scripts/tier2-runner-cutover.sh
#
# Re-running after a failure in steps 2-6 is safe; after a failure in step 7, use the rollback block.
# Everything runs inside main() with stdin from /dev/null: under `bash -s` the script IS stdin,
# so any child that reads stdin would otherwise eat the rest of the script.
# It never runs ktp-tier2-heartbeat.sh (a hand run writes the alerter's state); it re-derives
# what the heartbeat would see instead.

# ps lines are matched on uid plus full args, the EXIT trap calls on_exit, and the sed pattern is a literal.
# shellcheck disable=SC2009,SC2012,SC2016,SC2329
main() {
set -euo pipefail

RUN=/opt/ktp-tier2-runner
AR=$RUN/actions-runner
SF=$RUN/serverfiles
MARKER=$RUN/tier2-last-run.json
U=actions.runner.afraznein-KTPInfrastructure.ktp-tier2-neindataatl.service
UNIT=/etc/systemd/system/$U
DROPIN=/etc/systemd/system/$U.d/10-restart.conf
LISTENER=$AR/bin/Runner.Listener
WORKER_TAG=$AR/bin
NEWU=ktp-tier2
RCON=/etc/ktp/tier2-test-rcon.env
RELAY=/etc/ktp/discord-relay.conf
HB=/usr/local/bin/ktp-tier2-heartbeat.sh
HBCRON=/etc/cron.d/ktp-tier2-heartbeat
HBSTATE=/var/lib/ktp-tier2-heartbeat.state
HBLOG=/var/log/ktp-tier2-heartbeat.log
GO=0
[ "${1:-}" = "--go" ] && GO=1
STEP=0
B=""
T0=$(date +%s)

say()  { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
ok()   { printf '    PASS  %s\n' "$*"; }
die()  { printf '\n    FAIL  %s\n' "$*" >&2; exit 1; }
assert_eq() { if [ "$2" = "$3" ]; then ok "$1 = $2"; else die "$1: got '$2', expected '$3'"; fi; }
assert_ge() { if [ "$2" -ge "$3" ]; then ok "$1 = $2 (>= $3)"; else die "$1: got $2, expected >= $3"; fi; }

# ps truncates user names longer than 8 chars ("ktp-tie+"), so match on uid, never the name column.
listeners() { ps -eo uid=,pid=,ppid=,args= | grep -F "$LISTENER" | grep -v grep || true; }
workers()   { ps -eo uid=,pid=,ppid=,args= | grep -F "$WORKER_TAG" | grep -F 'Runner.Worker' | grep -v grep || true; }
nlines()    { if [ -z "$1" ]; then echo 0; else printf '%s\n' "$1" | wc -l | tr -d ' '; fi; }
as_new()    { runuser -u "$NEWU" -- "$@"; }

print_rollback() {
    cat <<ROLLBACK

================================ ROLLBACK (about 5 minutes) ================================
# If PR #847 (refuse-root) has merged, REVERT IT FIRST, or every tier-2 run fails and main is blocked.
RUN=$RUN; U=$U
cd "\$RUN/actions-runner" && ./svc.sh stop; ./svc.sh uninstall; ./svc.sh install root && ./svc.sh start
chmod 750 /etc/ktp                                   # was root:ktpreports 750
chown root:root $RCON $RELAY
chmod 600 $RCON $RELAY
systemctl show \$U -p User                           # must print User=root
ps -eo uid=,ppid=,args= | grep -F "$LISTENER" | grep -v grep   # one line, uid 0, PPID not 1
# Ownership in the tree may stay as it is (root reads everything; the marker is safe because the
# heartbeat validates ts). Full restore of previous owners and modes, if wanted:
#   while read -r og m p; do chown -h "\$og" "\$p"; [ -L "\$p" ] || chmod "\$m" "\$p"; done < ${B:-<backup dir>}/owners.txt
# Snapshot of the unit, drop-in, /etc/ktp modes and heartbeat state: ${B:-<not taken yet>}
# The ktp-tier2 user may stay; it owns nothing that runs once the unit is User=root again.
=============================================================================================
ROLLBACK
}

on_exit() {
    local rc=$?
    [ "$rc" -eq 0 ] && return 0
    printf '\n!!! stopped at step %s (exit %s)\n' "$STEP" "$rc" >&2
    if [ "$STEP" -ge 3 ] && [ "$STEP" -lt 7 ]; then
        printf '!!! the runner is STOPPED. Fix the cause and re-run with --go (steps 2-6 are safe to repeat), or roll back:\n' >&2
        print_rollback >&2
    elif [ "$STEP" -ge 7 ]; then
        printf '!!! the service was being reinstalled or verified. Do not re-run; roll back, or fix by hand and re-run the preflight:\n' >&2
        print_rollback >&2
    elif [ "$STEP" -eq 2 ]; then
        printf '!!! only the snapshot directory %s was written; the runner was not touched.\n' "$B" >&2
    else
        printf '!!! nothing on the box was changed.\n' >&2
    fi
}
trap on_exit EXIT

say "tier-2 runner cutover -- mode: $([ $GO = 1 ] && echo 'GO (makes changes)' || echo 'PREFLIGHT ONLY (changes nothing)')"

# ---------------------------------------------------------------- preflight
STEP=0
say "PREFLIGHT"
assert_eq "running as uid" "$(id -u)" 0
assert_eq "host" "$(hostname -s)" neindataatl
for f in "$AR/svc.sh" "$AR/.runner" "$UNIT" "$DROPIN" "$MARKER" "$RCON" "$RELAY" "$HB" "$HBCRON"; do
    [ -e "$f" ] || die "missing: $f"
done
ok "runner tree, unit, drop-in, marker, both /etc/ktp files, heartbeat + cron present"
assert_eq "svc.sh targets this unit" "$(grep -c "^SVC_NAME=\"$U\"" "$AR/svc.sh")" 1

CUR_USER=$(systemctl show "$U" -p User --value)
if [ "$CUR_USER" = "$NEWU" ]; then
    say "unit is already User=$NEWU -- nothing to cut over; running the verify block only."
    ALREADY=1
else
    assert_eq "unit User= before cutover" "$CUR_USER" root
    ALREADY=0
fi

say "step 1 (heartbeat #844) must be installed before anything is chowned"
assert_ge "is_epoch in installed heartbeat" "$(grep -c 'is_epoch' "$HB")" 2
assert_eq "KTP_TIER2_LISTENER_PATTERN lines in cron" "$(grep -c '^KTP_TIER2_LISTENER_PATTERN=' "$HBCRON")" 1
assert_eq "cron pattern value" "$(sed -n 's/^KTP_TIER2_LISTENER_PATTERN=//p' "$HBCRON")" "$LISTENER"
assert_eq "nonsense control in heartbeat" "$(grep -c 'zqwbw1110' "$HB" || true)" 0

say "time window"
ET_H=$((10#$(TZ=America/New_York date +%H))); ET_M=$((10#$(TZ=America/New_York date +%M)))
SINCE=$(( (ET_H % 6) * 60 + ET_M )); TONEXT=$(( 360 - SINCE ))
UTC_HM=$((10#$(date -u +%H%M)))
say "  ET $(TZ=America/New_York date +%a\ %H:%M), heartbeat cron (00/06/12/18 ET) next in ${TONEXT} min, last ${SINCE} min ago; UTC $(date -u +%H:%M)"
[ "$TONEXT" -ge 40 ] || die "the heartbeat cron fires in ${TONEXT} min; with the runner down it would record listeners=0 and alert. Start at least 40 min before a 00/06/12/18 ET slot."
[ "$SINCE" -ge 5 ]   || die "the heartbeat cron fired ${SINCE} min ago and may still be running; wait 5 min."
if [ "$UTC_HM" -ge 830 ] && [ "$UTC_HM" -le 945 ]; then die "inside the nightly tier-2 window (09:00 UTC +/- 30 min)"; fi
ok "outside the heartbeat slot and the nightly tier-2 run"

say "no tier-2 job may be running (local signal: a Runner.Worker process under $WORKER_TAG)"
L=$(listeners); W=$(workers)
if [ "$ALREADY" = 0 ]; then
    if [ "$(nlines "$L")" = 0 ] && [ "$(systemctl is-active "$U" || true)" = inactive ]; then
        say "  runner already stopped and still User=root: resuming an interrupted --go (earlier snapshot: ls -d /root/runner-deroot-bak-*)"
    else
        assert_eq "tier-2 listeners (positive control for the same probe)" "$(nlines "$L")" 1
    fi
fi
assert_eq "tier-2 Runner.Worker processes" "$(nlines "$W")" 0
LASTW=$(ls -t "$AR/_diag"/Worker_*.log 2>/dev/null | head -1 || true)
if [ -n "$LASTW" ]; then
    AGE=$(( $(date +%s) - $(stat -c %Y "$LASTW") ))
    [ "$AGE" -ge 120 ] || die "newest worker log $LASTW was written ${AGE}s ago; a job may be finishing. Wait 2 min."
    ok "newest worker log last written ${AGE}s ago"
fi
say "  also confirm from the workstation:  gh api repos/afraznein/KTPInfrastructure/actions/runners/21 -q .busy   (false)"

HB_STATE_BEFORE=$(cat "$HBSTATE" 2>/dev/null || echo '<none>')
say "  heartbeat state file now: $HB_STATE_BEFORE"

if [ "$GO" != 1 ]; then
    say "PREFLIGHT PASSED. Nothing was changed. Re-run with:  ssh root@<DATA_SERVER_IP> \"bash -s -- --go\" < scripts/tier2-runner-cutover.sh"
    exit 0
fi

if [ "$ALREADY" = 0 ]; then
# ---------------------------------------------------------------- step 2: snapshot
STEP=2
B=/root/runner-deroot-bak-$(date +%Y%m%dT%H%M%S)
say "STEP 2 snapshot -> $B"
mkdir -m 700 "$B"
cp -a "$UNIT" "$UNIT.d" "$B"/
cp -a "$AR/.service" "$B/dot-service"
find "$RUN" -xdev -printf '%u:%g %m %p\n' > "$B/owners.txt"
stat -c '%U:%G %a %n' /etc/ktp "$RCON" "$RELAY" > "$B/etc-ktp.txt"
printf '%s\n' "$HB_STATE_BEFORE" > "$B/heartbeat.state"
assert_eq "owners.txt lines vs a fresh find" "$(wc -l < "$B/owners.txt")" "$(find "$RUN" -xdev | wc -l)"
assert_eq "snapshot dir mode" "$(stat -c %a "$B")" 700

# ---------------------------------------------------------------- step 3: stop
STEP=3
say "STEP 3 stop the runner"
( cd "$AR" && ./svc.sh stop ) || true
for _ in $(seq 1 30); do [ -z "$(listeners)" ] && break; sleep 1; done
[ -z "$(workers)" ] || die "a Runner.Worker appeared during stop -- a job was picked up. Do not chown; start the unit again (./svc.sh start) and retry later."
L=$(listeners)
if [ -n "$L" ]; then
    say "  a listener survived the stop (the KillMode=process orphan) -- killing it:"
    printf '%s\n' "$L"
    printf '%s\n' "$L" | awk '{print $2}' | xargs -r kill -TERM
    sleep 10
    L=$(listeners); [ -z "$L" ] || { printf '%s\n' "$L" | awk '{print $2}' | xargs -r kill -KILL; sleep 2; }
fi
assert_eq "tier-2 listeners after stop" "$(nlines "$(listeners)")" 0
assert_eq "unit state after stop" "$(systemctl is-active "$U" || true)" inactive
fi

# ---------------------------------------------------------------- step 4: user
STEP=4
say "STEP 4 user $NEWU (no supplementary groups, no shell)"
if getent passwd "$NEWU" >/dev/null; then
    say "  $NEWU already exists (resumed run) -- verifying it instead of creating it"
else
    useradd --system --user-group --create-home --home-dir "$RUN/home" --shell /usr/sbin/nologin "$NEWU"
fi
assert_eq "groups of $NEWU" "$(id -nG "$NEWU")" "$NEWU"
assert_eq "shell of $NEWU" "$(getent passwd "$NEWU" | cut -d: -f7)" /usr/sbin/nologin
assert_eq "home of $NEWU" "$(getent passwd "$NEWU" | cut -d: -f6)" "$RUN/home"
assert_eq "sudo -l -U $NEWU says not allowed" "$(sudo -l -U "$NEWU" 2>&1 | grep -c 'is not allowed to run sudo' || true)" 1
NEWUID=$(id -u "$NEWU")
ok "$NEWU uid $NEWUID"

if [ "$ALREADY" = 0 ]; then
# ---------------------------------------------------------------- step 5: ownership
STEP=5
say "STEP 5 ownership of actions-runner/, serverfiles/ and the marker"
chown -R "$NEWU:$NEWU" "$AR" "$SF"
chown "$NEWU:$NEWU" "$MARKER"
chmod -R g-w,o-w "$SF"
assert_eq "entries under actions-runner/ not owned by $NEWU (haystack $(find "$AR" -xdev | wc -l))" "$(find "$AR" -xdev ! -user "$NEWU" | wc -l)" 0
assert_eq "entries under serverfiles/ not owned by $NEWU (haystack $(find "$SF" -xdev | wc -l))" "$(find "$SF" -xdev ! -user "$NEWU" | wc -l)" 0
assert_eq "group/other-writable non-symlinks under serverfiles/" "$(find "$SF" -xdev ! -type l -perm /022 | wc -l)" 0
assert_eq "marker owner" "$(stat -c %U "$MARKER")" "$NEWU"
assert_eq "$RUN itself" "$(stat -c %U:%G "$RUN")" root:root
STRAY=$(find "$RUN" -mindepth 1 -maxdepth 1 ! -user root ! -path "$AR" ! -path "$SF" ! -path "$MARKER" ! -path "$RUN/home" -printf '%f\n')
assert_eq "top-level entries that must stay root but are not" "${STRAY:-none}" none
assert_eq "toolchain/ entries not root (haystack $(find "$RUN/toolchain" | wc -l))" "$(find "$RUN/toolchain" ! -user root | wc -l)" 0

# ---------------------------------------------------------------- step 6: two secret files
STEP=6
say "STEP 6 /etc/ktp: traversal, and read on exactly two files"
chmod o+x /etc/ktp
chgrp "$NEWU" "$RCON" "$RELAY"
chmod 640 "$RCON" "$RELAY"
assert_eq "/etc/ktp" "$(stat -c '%U:%G %a' /etc/ktp)" "root:ktpreports 751"
assert_eq "$RCON" "$(stat -c '%U:%G %a' "$RCON")" "root:$NEWU 640"
assert_eq "$RELAY" "$(stat -c '%U:%G %a' "$RELAY")" "root:$NEWU 640"
assert_eq "files in /etc/ktp with group $NEWU" "$(find /etc/ktp -maxdepth 1 -group "$NEWU" | wc -l)" 2

# ---------------------------------------------------------------- step 7: reinstall as the new user
STEP=7
say "STEP 7 reinstall the service as $NEWU (unit name and drop-in kept)"
( cd "$AR" && ./svc.sh uninstall )
( cd "$AR" && ./svc.sh install "$NEWU" )
( cd "$AR" && ./svc.sh start ) || true
fi

# ---------------------------------------------------------------- verify
STEP=8
say "VERIFY"
assert_eq "a. unit User=" "$(systemctl show "$U" -p User --value)" "$NEWU"
assert_eq "a. drop-in still applied" "$(systemctl show "$U" -p DropInPaths --value)" "$DROPIN"
assert_eq "a. unit active" "$(systemctl is-active "$U" || true)" active
for _ in $(seq 1 60); do [ "$(nlines "$(listeners)")" -ge 1 ] && break; sleep 1; done
L=$(listeners)
assert_eq "a. tier-2 listeners" "$(nlines "$L")" 1
assert_eq "a. listener uid" "$(printf '%s\n' "$L" | awk '{print $1}')" "$NEWUID"
[ "$(printf '%s\n' "$L" | awk '{print $3}')" != 1 ] || die "listener PPID is 1 -- an orphan, not the unit's child"
ok "a. listener PPID $(printf '%s\n' "$L" | awk '{print $3}') (not 1)"
LJ=0
for _ in $(seq 1 90); do
    LJ=$(journalctl -u "$U" --since "@$T0" -o cat --no-pager 2>/dev/null | grep -c 'Listening for Jobs' || true)
    [ "$LJ" -ge 1 ] && break; sleep 1
done
assert_ge "b. 'Listening for Jobs' in the unit journal since this script started" "$LJ" 1
assert_eq "b. Runner.Worker processes (no job yet)" "$(nlines "$(workers)")" 0

say "c/d. what $NEWU can and cannot do (c means nothing without d)"
assert_eq "c. write /usr/local/bin"        "$(as_new test -w /usr/local/bin && echo W || echo -)" -
assert_eq "c. read /etc/ktp/audit-fleet.json" "$(as_new test -r /etc/ktp/audit-fleet.json && echo R || echo -)" -
assert_eq "c. read /etc/ktp/telemetry-export.conf" "$(as_new test -r /etc/ktp/telemetry-export.conf && echo R || echo -)" -
assert_eq "c. sudo -n true"                "$(as_new sudo -n true >/dev/null 2>&1 && echo YES || echo refused)" refused
assert_eq "c. write /var/lib (heartbeat state dir)" "$(as_new test -w /var/lib && echo W || echo -)" -
assert_eq "c. write $RUN (stays root)"     "$(as_new test -w "$RUN" && echo W || echo -)" -
assert_eq "c. write $RUN/toolchain"        "$(as_new test -w "$RUN/toolchain" && echo W || echo -)" -
assert_eq "d. read $RCON"                  "$(as_new test -r "$RCON" && echo R || echo -)" R
assert_eq "d. read $RELAY"                 "$(as_new test -r "$RELAY" && echo R || echo -)" R
assert_eq "d. write $RELAY (must not)"     "$(as_new test -w "$RELAY" && echo W || echo -)" -
assert_eq "d. write serverfiles plugins"   "$(as_new test -w "$SF/dod/addons/ktpamx/plugins" && echo W || echo -)" W
assert_eq "d. write the marker"            "$(as_new test -w "$MARKER" && echo W || echo -)" W
assert_eq "d. execute toolchain amxxpc"    "$(as_new test -x "$RUN/toolchain/amxxpc" && echo X || echo -)" X
assert_eq "d. write _work/_tool"           "$(as_new test -w "$AR/_work/_tool" && echo W || echo -)" W

say "g. what the heartbeat will read at its next run (derived, NOT by running it)"
TS=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('ts',''))" "$MARKER")
OUTCOME=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('outcome',''))" "$MARKER")
case "$TS" in ''|0*|*[!0-9]*) die "marker ts '$TS' is not a plain integer";; esac
MAXAGE=$(sed -n 's/^MAX_AGE_SECONDS="\${KTP_TIER2_MAX_AGE:-\([0-9]*\)}"$/\1/p' "$HB"); MAXAGE=${MAXAGE:-129600}
assert_eq "g. marker outcome" "$OUTCOME" success
[ $(( $(date +%s) - TS )) -lt "$MAXAGE" ] || die "marker is older than the heartbeat window ($MAXAGE s)"
ok "g. marker age $(( $(date +%s) - TS ))s < ${MAXAGE}s"
assert_eq "g. listeners counted with the cron's own pattern" "$(ps -eo pid,ppid,args | grep -F "$(sed -n 's/^KTP_TIER2_LISTENER_PATTERN=//p' "$HBCRON")" | grep -vc grep)" 1
assert_eq "g. heartbeat state file untouched by this script" "$(cat "$HBSTATE" 2>/dev/null || echo '<none>')" "$HB_STATE_BEFORE"
say "  expected key at the next slot: main=ok,preprod=ok,...,listeners=1 -> 'no alert'. Check after it fires:"
say "  tail -n 2 $HBLOG"

say "CUTOVER DONE on the box in $(( $(date +%s) - T0 ))s. Snapshot: ${B:-<none: resumed run>}"
cat <<NEXT

Next, from the workstation (the box has no gh):
  b. gh api repos/afraznein/KTPInfrastructure/actions/runners/21 -q '.status,.busy'        # online, false
  e. gh workflow run tier2-integration.yml -R afraznein/KTPInfrastructure --ref main
     green AND the passed/failed/skipped counts in tier2-report.json match the last root run
     (a permission problem shows up as extra skips, which still reads green); log shows the plugin
     install, the KTPWitness build and the HUD observer staging; the Discord embed posted.
  f. on the box: stat -c '%U %y' $MARKER   -> $NEWU, fresh mtime, outcome success
  h. #847 proof: push an EMPTY commit to its branch (never gh run rerun):
       git -C KTPInfrastructure fetch origin ci/tier2-refuse-root
       git -C KTPInfrastructure worktree add C:/ktp-wt-847 origin/ci/tier2-refuse-root --detach
       git -C C:/ktp-wt-847 commit --allow-empty -m "ci: re-run tier 2 against the ktp-tier2 runner"
       git -C C:/ktp-wt-847 push origin HEAD:ci/tier2-refuse-root
     The 'Refuse to run as root' step must print "Running as ktp-tier2, uid $NEWUID." and integration go green.
     Then mark #847 ready and merge it.
  After every sync-runner-stack.py / stage-runner.py run:  chown -R $NEWU:$NEWU $SF
NEXT
print_rollback
}

main "$@" < /dev/null
exit $?
