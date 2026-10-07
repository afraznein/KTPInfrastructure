#!/bin/bash
# KTP Data Server Health Check
#
# Monitors critical services + timers + HLTV instance coverage. Alerts to
# Discord ONLY on state transitions (service goes down → alert; service
# recovers → alert "restored"; persistent-down → silent, no chat spam).
#
# Schedule: hourly via /etc/cron.d/ktp-data-server-health. Issues here are
# background services whose failures aren't player-visible, so a 10-minute
# window felt like overkill.
#
# State file: /var/lib/ktp-data-server-health.json
# Log:        /var/log/ktp-data-server-health.log
# Discord:    sources /etc/ktp/discord-relay.conf (RELAY_URL + AUTH_SECRET)

# -E only so the ERR trap below is inherited into functions; nothing else changes.
set -Eeuo pipefail

STATE_FILE="${STATE_FILE:-/var/lib/ktp-data-server-health.json}"
# #ktp-crashes — consolidated with perf-rollup (PERF_ALERT_CHANNEL in
# /etc/ktp/discord-relay.conf, same channel) per operator decision
# 2026-05-06. Health alerts are crash-class signals (services dying);
# routing them alongside crashes keeps the operational signal in one
# place. Reverses the May 3 "dedicated #ktp-data-server-health" split.
# Override via ALERT_CHANNEL env var if a different routing is needed.
ALERT_CHANNEL="${ALERT_CHANNEL:-1497957091107668070}"
# HLTV port range mirrors game ports: 27020=ATL1, 27021=ATL2, ... 27044=CHI5
HLTV_PORT_START=27020
HLTV_PORT_END=27044
# Intentionally excluded (e.g. hltv@27044 was disabled 2026-04-10 when the
# upstream Chicago 27019 game server was taken offline for the 4-server trial).
# Add a port here if the corresponding game server is disabled on purpose.
HLTV_EXCLUDED_PORTS=(27044)

# Critical services that must be active (systemctl is-active == "active")
CRITICAL_SERVICES=(
    mysql.service
    nginx.service
    hlstatsx.service
    hltv-api.service
    ktp-ac-api.service
    ktp-file-distributor.service
    # A dead renamer silently loses league demos to the 6h auto-cleanup sweep
    # (unrenamed auto-*.dem get purged) — it MUST page promptly.
    hltv-demo-renamer.service
    # A dead aggregator silently suppresses the whole perf-alert tier
    # (perf-rollup exits quietly on an empty day).
    ktp-profile-aggregator.service
)

# Timers that must be enabled + scheduled
CRITICAL_TIMERS=(
    hltv-restart.timer
    # Renders the central ban list into the distribute tree. A stopped timer is
    # silent: the last-published file stays in place and reads as healthy.
    ktp-render-banlist.timer
    # Files renamed demos into the published tree and rebuilds the archive
    # pages. Stopped, it is silent: the site keeps serving yesterday's index.
    ktp-demo-publish.timer
    # The seven below were added 2026-09-16 after ALERT_COVERAGE.md found this
    # list naming 3 of the box's 10 live timers. OnFailure= fires when a unit
    # runs and fails; nothing fires when a timer stops scheduling it at all,
    # and every one of these goes quiet in a way that reads as healthy.
    #
    # The check written after the 9h48m HLTV outage (2026-08-10). If this timer
    # stops, that check stops, and the next dead proxy is found the old way.
    ktp-hltv-liveness.timer
    # Watches the ingest path for the failures that are otherwise silent; a
    # stopped watcher is the most silent failure of all.
    ktp-hlstatsx-ingest-monitor.timer
    # Exports stop; the last file stays in place and reads as current.
    ktp-stats-export.timer
    # Reconciliation stops; identities drift apart with no error anywhere.
    ktp-identity-reconcile.timer
    ktp-roster-history-audit.timer
    # Corpus pushes stop; the offsite copy quietly ages.
    ktp-corpus-push.timer
    ktp-corpus-push-denver.timer
    # The Monday outlier report stops; a quiet Monday reads as a clean week.
    ktp-weekly-outliers.timer
    # Not listed: ktp-monday-reminder.timer. A reminder that fails to arrive is
    # noticed by the people expecting it, which is the alert.
)

# Central ban-list renderer. Checked on three independent legs because each one
# hides the others: the file can be absent, the timer can have stopped, or it can
# be running every minute and failing — the 2026-08-12 case, whose exit timestamp
# stays fresh, so staleness alone misses it.
# Renamer LIVENESS, which is-active cannot answer. The unit is already in
# CRITICAL_SERVICES precisely to stop demo loss, yet on 2026-08-25 it wedged on
# a half-open SSH session and sat "active" for 53h while every match demo in the
# window went unrenamed and was purged by the auto-cleanup. A hung process is
# active. The poll loop rewrites state.json once per 30s cycle, so that file's
# mtime is the cheapest true "work happened" signal available.
RENAMER_STATE_FILE=/var/lib/hltv-demo-renamer/state.json
RENAMER_STALE_SEC=900
# Liveness is not reading. The poll loop can iterate while every SSH session
# fails -- which rewrites state.json on schedule, so the mtime leg above, a
# systemd watchdog and the cleanup interlock all read healthy while no match
# window is ever seen. last_read_ok stamps the last clean pass per game host.
RENAMER_READ_STALE_SEC=1800

# Weekly precache audit, which nothing watched. The audit writes
# /var/log/ktp-precache-audit-<date>.md on every run; the cron's own .log is
# excluded on purpose, because it is appended to even by a run that died before
# auditing anything, so it would certify work that never happened.
PRECACHE_REPORT_GLOB="${PRECACHE_REPORT_GLOB:-/var/log/ktp-precache-audit-*.md}"
# Sunday cadence (7d) plus a day, so a run that starts late does not page while a
# missed Sunday -- 14d before the next one -- does.
PRECACHE_STALE_SEC="${PRECACHE_STALE_SEC:-691200}"

BANLIST_FILE="/home/dod/distribute/addons/ktpamx/configs/ktp_ac_bans.ini"
BANLIST_UNIT="ktp-render-banlist.service"
BANLIST_STALE_SEC=900

[ -f /etc/ktp/discord-relay.conf ] && source /etc/ktp/discord-relay.conf

ts() { date '+%Y-%m-%d %H:%M:%S'; }

# Severity → glyph / colour / lane, decided in one place for every producer
# (docs/runbooks/ALERT_ROUTING.md). Sourced when deployed beside this script.
# Not FATAL when absent, unlike ktp-hltv-liveness.sh: this is the check that
# watches everything else, and a deploy-order slip must not turn it into a
# silent exit under MAILTO=''. The fallback in health_alert_route below is
# today's behaviour, byte for byte.
_routing="$(dirname "${BASH_SOURCE[0]}")/ktp-alert-routing.sh"
if [ -r "$_routing" ]; then
    . "$_routing"
else
    echo "[$(ts)] WARN: $_routing absent -- legacy colours and channel until it is deployed" >&2
fi

# >>> ktp-health-route — extracted verbatim by tests/unit/test_health_alert_route.py
# health_alert_route <count-of-new-down-items>
# Sets KTP_ALERT_SEVERITY, KTP_ALERT_GLYPH, KTP_ALERT_COLOR, KTP_ALERT_LANE,
# KTP_ALERT_CHANNEL, KTP_ALERT_CHANNEL_SOURCE. A run with anything newly down
# is a page; a run that only recovered is a recovery -- both on the page lane,
# because the recovery belongs beside the page it ends. The channel comes from
# the lane's env mapping when the operator has set one, and from ALERT_CHANNEL
# otherwise, so until the mapping exists this posts exactly where it does now.
health_alert_route() {
    local n_new="$1"
    if [ "$n_new" -gt 0 ]; then KTP_ALERT_SEVERITY=page; else KTP_ALERT_SEVERITY=recovery; fi
    if declare -F ktp_alert_route >/dev/null 2>&1; then
        ktp_alert_route "$KTP_ALERT_SEVERITY"
        ktp_alert_channel "$KTP_ALERT_LANE" "$ALERT_CHANNEL"
    else
        # The helper is not deployed: the pre-routing constants, unchanged.
        KTP_ALERT_GLYPH=''
        KTP_ALERT_LANE='legacy'
        KTP_ALERT_CHANNEL="$ALERT_CHANNEL"
        KTP_ALERT_CHANNEL_SOURCE='fallback'
        if [ "$KTP_ALERT_SEVERITY" = page ]; then KTP_ALERT_COLOR=15548997; else KTP_ALERT_COLOR=5763719; fi
    fi
}
# <<< ktp-health-route

# >>> ktp-run-ledger — extracted verbatim by tests/unit/test_health_run_ledger.py
# Nothing watches this check; it IS the watcher, and a watcher that stops looks
# exactly like a quiet estate (ALERT_COVERAGE.md hole 4). From #207 on 2026-08-31
# until #397 it exited before its own report on every one-sided transition — 15
# days during which it could not have said a word, and nothing anywhere noticed.
# #397 removed that particular abort. It did not make an abort visible, and the
# next one will be a different line.
#
# So each run leaves a record of how it ended, and the next completed run reads
# it. Plain key=value written with printf, never jq: the ledger has to survive
# the failures that kill the rest of this script, an unusable jq included.
RUN_LEDGER="${RUN_LEDGER:-/var/lib/ktp-data-server-health.run}"
# Hourly cron, three intervals of slack. Two would fire on the ordinary gap a
# single aborted run leaves behind, which health-check-aborted already reports
# with the line number.
RUN_GAP_SEC="${RUN_GAP_SEC:-10800}"

# ledger_items <ledger-text> <now-epoch> <gap-sec>
# Prints `key<TAB>detail` for what the PREVIOUS run's ledger says went wrong, and
# nothing at all when it completed on time. At most one line: a run that died is
# also a run that did not complete, and two items for one fault double-count it
# in the set diff.
ledger_items() {
    local text=$1 now=$2 gap=$3
    local k v status="" line="" completed=""
    while IFS='=' read -r k v; do
        case "$k" in
            status) status=$v ;;
            line) line=$v ;;
            completed) completed=$v ;;
        esac
    done <<< "$text"
    # No ledger at all is a first run, not a missed one. Alerting here would put
    # one false failure on every fresh install, which is how a reader learns to
    # skip the line.
    if [ -z "$status" ] && [ -z "$completed" ]; then return 0; fi

    local age=-1 silence=""
    if [[ $completed =~ ^[0-9]+$ ]]; then
        age=$(( now - completed ))
        silence=", and the last completed run was $(( age / 3600 ))h ago"
    fi
    if [ "$status" != "ok" ]; then
        # An ERR trap cannot name a line for a run that was signalled rather
        # than errexit'd -- the OOM killer, a systemd stop. Saying "line 0"
        # there would send the reader to the shebang.
        local where="at line $line"
        if [ -z "$line" ] || [ "$line" = "0" ]; then
            where="at no line it could name, so it was signalled rather than failing a command"
        fi
        printf 'health-check-aborted\tthe previous run exited early %s (%s); it posted no alert and saved no state%s\n' \
            "$where" "${status:-unknown}" "$silence"
        return 0
    fi
    if [ "$age" -lt 0 ]; then
        printf 'health-check-aborted\tthe run ledger carries no completion timestamp, so the previous run cannot be accounted for\n'
        return 0
    fi
    if [ "$age" -gt "$gap" ]; then
        printf 'health-check-missed-runs\tno run completed for %sh — this check is hourly, so nothing was watching for that long\n' \
            "$(( age / 3600 ))"
    fi
}

# write_ledger <exit-status> <errexit-line>
# `completed` moves only on a clean exit. A died run carries the previous value
# forward, so the silence keeps accumulating instead of resetting itself every
# hour while the check is broken.
write_ledger() {
    local rc=$1 line=$2 status=died completed=${PREV_COMPLETED:-}
    if [ "$rc" -eq 0 ]; then status=ok; line=0; completed=$(date +%s); fi
    mkdir -p "$(dirname "$RUN_LEDGER")" 2>/dev/null || true
    printf 'status=%s\nrc=%s\nline=%s\nstarted=%s\ncompleted=%s\n' \
        "$status" "$rc" "$line" "${RUN_STARTED:-0}" "$completed" \
        > "$RUN_LEDGER.tmp" 2>/dev/null \
        && mv -f "$RUN_LEDGER.tmp" "$RUN_LEDGER" 2>/dev/null || true
}
# <<< ktp-run-ledger

RUN_STARTED=$(date +%s)
PREV_LEDGER=$(cat "$RUN_LEDGER" 2>/dev/null || true)
PREV_COMPLETED=""
while IFS='=' read -r _k _v; do
    if [ "$_k" = "completed" ]; then PREV_COMPLETED=$_v; fi
done <<< "$PREV_LEDGER"

# Line of the command that tripped errexit, so the next run can name it rather
# than only saying that something went wrong. `set -E` above carries this into
# functions; without it an abort inside save_state would report line 0.
_run_fail_line=0
trap '_run_fail_line=$LINENO' ERR

# One EXIT trap, installed before the first thing that can fail, so that every
# way out is recorded: the clean `exit 0`, an errexit death, and a signal.
PREV_LIST=""
TMP_CURR=""
on_exit() {
    local rc=$?
    # We are leaving either way; errexit here would only truncate the cleanup.
    set +e
    write_ledger "$rc" "$_run_fail_line"
    if [ -n "$PREV_LIST" ]; then rm -f "$PREV_LIST"; fi
    if [ -n "$TMP_CURR" ]; then rm -f "$TMP_CURR"; fi
    rm -f /tmp/ktp-health-resp.txt
    return "$rc"
}
trap on_exit EXIT

# >>> ktp-alert-settle — extracted verbatim by tests/unit/test_health_transition_report.py
# systemd reports `activating`/`deactivating`/`reloading` while a unit is mid-restart, and
# an hourly cron sampling at :00 lands in the same minute as hltv-restart.timer (03:00 and
# 11:00 ET). 252 of the 325 alerts logged over 2026-04-20..09-15 fell in hours 03, 04, 11
# and 12. A transitional state is re-read after a settle delay; a unit still not active
# then is genuinely stuck and still alerts. One sleep per run, not one per unit.
SETTLE_SECONDS="${SETTLE_SECONDS:-20}"
_settle_slept=0
# Answers in $SETTLED rather than on stdout: a caller writing `s=$(settled_state x)`
# runs this in a subshell, where the once-per-run latch below is discarded and every
# transitional unit pays the full delay — 24 proxies, eight minutes.
settled_state() {
    local unit=$1
    SETTLED=$(systemctl is-active "$unit" 2>/dev/null || true)
    case "$SETTLED" in
        activating|deactivating|reloading|refreshing)
            if [ "$_settle_slept" -eq 0 ]; then
                sleep "$SETTLE_SECONDS"
                _settle_slept=1
            fi
            SETTLED=$(systemctl is-active "$unit" 2>/dev/null || true)
            ;;
    esac
}
# <<< ktp-alert-settle

# >>> ktp-alert-join — extracted verbatim by tests/unit/test_health_transition_report.py
# `printf '%s\n' "${arr[@]}" | grep -v '^$' | paste -sd, -` prints one BLANK line for an
# empty array; grep then matches nothing and exits 1, and under `set -e -o pipefail` that
# kills the run before the TRANSITIONS line and before the Discord POST. From #207
# (2026-08-31) until this commit the check could only speak when a failure and a recovery
# landed in the SAME hourly run — 0 of 42 logged transitions were one-sided, against 257
# of 283 in the month before. A first-ever failure alerted nobody.
join_keys() {
    local IFS=,
    printf '%s' "$*"
}
# <<< ktp-alert-join

# ---- Previous "down" set ----
# Read before the checks run, not after, because the disk thresholds below latch
# on it: an item already reported stays reported until it clears the lower bound.
PREV_LIST=$(mktemp)
if [ -f "$STATE_FILE" ]; then
    jq -r '.down[]?' < "$STATE_FILE" 2>/dev/null | sort -u > "$PREV_LIST" || : > "$PREV_LIST"
fi

# ---- Collect current "down" set ----
down=()
# key -> magnitude, shown in the alert body. Deliberately NOT part of the key:
# a number inside a key makes every change of that number read to the set
# comparison as one recovery plus one new failure.
declare -A detail=()

# The check's own last run, read first on purpose: if this script is the thing
# that is broken, that is the most important line in the report and it must not
# depend on a later probe surviving to be printed.
while IFS=$'\t' read -r _key _note; do
    if [ -z "${_key:-}" ]; then continue; fi
    down+=("$_key"); detail[$_key]="$_note"
done <<< "$(ledger_items "$PREV_LEDGER" "$(date +%s)" "$RUN_GAP_SEC")"

for svc in "${CRITICAL_SERVICES[@]}"; do
    settled_state "$svc"; state=$SETTLED
    if [ "$state" != "active" ]; then
        down+=("$svc=$state")
    fi
done

for t in "${CRITICAL_TIMERS[@]}"; do
    state=$(systemctl is-active "$t" 2>/dev/null || true)
    enabled=$(systemctl is-enabled "$t" 2>/dev/null || true)
    if [ "$state" != "active" ] || [ "$enabled" != "enabled" ]; then
        down+=("$t=${state}/${enabled}")
    fi
done

# ---- Any unit systemd itself calls failed ----
# CRITICAL_SERVICES is an allowlist and is blind to a unit it does not name.
# ktp-identity-reconcile.service failed on 2026-09-08; its OnFailure= alert
# fired once, into a channel, and the unit sat failed for over a week with no
# surface anywhere saying so. `systemctl --failed` is the box's own answer to
# "what is broken right now" and costs nothing to ask. Units already reported
# above by name are skipped so one fault is one item, not two.
# FAILED_UNIT_IGNORE: space-separated globs for units whose failure is known
# and accepted (an unused snap hook, say). Empty by default on purpose -- the
# first run after deploy reports everything, once, and the operator decides.
FAILED_UNIT_IGNORE="${FAILED_UNIT_IGNORE:-}"
while read -r unit _; do
    if [ -z "${unit:-}" ]; then continue; fi
    skip=0
    for svc in "${CRITICAL_SERVICES[@]}"; do
        if [ "$unit" = "$svc" ]; then skip=1; fi
    done
    for pat in $FAILED_UNIT_IGNORE; do
        case "$unit" in $pat) skip=1 ;; esac
    done
    if [ "$skip" -eq 0 ]; then
        down+=("failed-unit:${unit}")
    fi
done <<< "$(systemctl --failed --no-legend --plain 2>/dev/null | awk '{print $1}' || true)"

# Keyed on the UNIT's last exit, never on the file's mtime or the renderer's log.
# Both of those go permanently quiet once the list stops changing — which is the
# healthy steady state — so either would read as `stale` forever and get tuned out.
banlist_load=$(systemctl show "$BANLIST_UNIT" -p LoadState --value 2>/dev/null || true)
if [ "$banlist_load" != "loaded" ]; then
    # A nonexistent unit answers Result=success and exits 0, so a Result-only
    # check calls a typo healthy. LoadState is the mandatory guard.
    down+=("$BANLIST_UNIT=not-loaded")
else
    banlist_result=$(systemctl show "$BANLIST_UNIT" -p Result --value 2>/dev/null || true)
    if [ "$banlist_result" != "success" ]; then
        down+=("$BANLIST_UNIT=render-failed")
    fi
    banlist_last=$(systemctl show "$BANLIST_UNIT" -p ExecMainExitTimestamp --value 2>/dev/null || true)
    if [ -z "$banlist_last" ]; then
        # `date -d ''` SUCCEEDS, returning midnight today, so an empty timestamp
        # must be caught here rather than handed to date.
        down+=("$BANLIST_UNIT=never-ran")
    else
        banlist_epoch=$(date -d "$banlist_last" +%s 2>/dev/null || echo 0)
        if [ "$banlist_epoch" -eq 0 ] || \
           [ $(( $(date +%s) - banlist_epoch )) -gt "$BANLIST_STALE_SEC" ]; then
            down+=("$BANLIST_UNIT=stale")
        fi
    fi
fi
# Tokens above are fixed strings, never an age — the report is a set-diff against
# the previous run, so a ticking value would look like a new failure every hour.
if [ ! -f "$BANLIST_FILE" ]; then
    down+=("ktp_ac_bans.ini=absent")
fi

# Renamer liveness. Only meaningful while the unit is up — a stopped unit is
# already reported by CRITICAL_SERVICES, and both legs firing would double-count
# one fault as two set members.
if [ "$(systemctl is-active hltv-demo-renamer.service 2>/dev/null || true)" = "active" ]; then
    if [ ! -f "$RENAMER_STATE_FILE" ]; then
        down+=("hltv-demo-renamer-state=absent")
    else
        renamer_epoch=$(stat -c %Y "$RENAMER_STATE_FILE" 2>/dev/null || echo 0)
        if [ "$renamer_epoch" -eq 0 ] ||            [ $(( $(date +%s) - renamer_epoch )) -gt "$RENAMER_STALE_SEC" ]; then
            # Fixed token, never the age: the report is a set-diff, so a ticking
            # value would read as a fresh failure on every hourly run.
            down+=("hltv-demo-renamer=wedged")
        else
            # Fresh file, but is it reading? One token per stale host, each a
            # fixed string. Silent on a pre-upgrade state.json that has no
            # stamps yet -- the cleanup interlock fails safe on that case, so a
            # page here would be noise, not news.
            for reg in $(python3 - "$RENAMER_STATE_FILE" "$RENAMER_READ_STALE_SEC" <<'PY' 2>/dev/null
import json, sys, time
try:
    stamps = json.load(open(sys.argv[1])).get("last_read_ok", {})
except Exception:
    raise SystemExit
now, limit = time.time(), int(sys.argv[2])
for r in sorted(stamps):
    if now - stamps[r] > limit:
        print(r)
PY
            ); do
                down+=("hltv-demo-renamer-read=$reg")
            done
        fi
    fi
fi

# >>> ktp-precache-freshness — extracted verbatim by tests/unit/test_health_precache_freshness.py
# Alert on work DONE, never on process state. The cron sets MAILTO='' and the
# audit posts only on actionable severity, so a quiet week and an audit that
# stopped running are the same silence -- and a hung process reads as active.
precache_freshness() {  # $1 = report glob, $2 = max age seconds, $3 = now epoch
    local newest=0 f e
    for f in $1; do
        [ -f "$f" ] || continue
        e="$(stat -c %Y "$f" 2>/dev/null || echo 0)"
        if [ "$e" -gt "$newest" ]; then newest="$e"; fi
    done
    if [ "$newest" -eq 0 ]; then
        # No report at all is deliberately the loud direction: if the audit's
        # --output path is ever renamed, this becomes a false alarm rather than
        # the silence it exists to end.
        echo "ktp-precache-audit=no-report"
        return 0
    fi
    # Fixed token, never the age -- the report is a set-diff against the previous
    # run, so a ticking value would read as a fresh failure on every hourly run.
    if [ $(( $3 - newest )) -gt "$2" ]; then echo "ktp-precache-audit=stale"; fi
    return 0
}
# <<< ktp-precache-freshness
precache_item="$(precache_freshness "$PRECACHE_REPORT_GLOB" "$PRECACHE_STALE_SEC" "$(date +%s)")"
if [ -n "$precache_item" ]; then down+=("$precache_item"); fi

# HLTV instance coverage — check each port in the expected set,
# skipping intentionally-excluded ones.
is_excluded() {
    local p="$1"
    for ex in "${HLTV_EXCLUDED_PORTS[@]}"; do
        [ "$ex" = "$p" ] && return 0
    done
    return 1
}
expected_hltv=0
active_hltv=0
missing_hltv=()
up_ports=()
for p in $(seq "$HLTV_PORT_START" "$HLTV_PORT_END"); do
    if is_excluded "$p"; then continue; fi
    expected_hltv=$((expected_hltv + 1))
    settled_state "hltv@$p"; state=$SETTLED
    if [ "$state" = "active" ]; then
        active_hltv=$((active_hltv + 1))
        up_ports+=("$p")
    else
        missing_hltv+=("hltv@$p=$state")
    fi
done
if [ "$active_hltv" -lt "$expected_hltv" ]; then
    # Numberless key, magnitude in the body: a count moving 23/24 -> 22/24 reads to
    # the set comparison as one recovery plus one new failure, the same defect the
    # disk keys carried until #388.
    key="hltv-instance-coverage"
    down+=("$key"); detail[$key]="${active_hltv}/${expected_hltv} proxies active"
    # Name the instance(s) too, so the alert is actionable on its own.
    for m in "${missing_hltv[@]}"; do
        down+=("$m")
    done
fi

# >>> ktp-hltv-crashloop — extracted verbatim by tests/unit/test_health_hltv_coverage.py
# `Restart=always` with `RestartSec=10` outruns systemd's default start-rate limit
# (5 starts per 10s), so a crash-looping proxy never lands in `failed`: it flaps
# active↔activating forever and is-active reads `active` most of the time. That is
# the hung-service shape — unit state answering a question it cannot see — and
# NRestarts is the only leg that sees it. It counts automatic restarts only and an
# explicit restart resets it, so the 03:00/11:00 pass re-arms it twice a day.
HLTV_RESTART_WARN="${HLTV_RESTART_WARN:-3}"
hltv_unit_restarts() { systemctl show "hltv@$1" -p NRestarts --value 2>/dev/null || true; }

# Only for proxies that ARE up — a port already named above is one fault, and a
# second token for it would double-count it in the set diff.
for p in ${up_ports[@]+"${up_ports[@]}"}; do
    nrestarts=$(hltv_unit_restarts "$p")
    if [[ $nrestarts =~ ^[0-9]+$ ]] && [ "$nrestarts" -ge "$HLTV_RESTART_WARN" ]; then
        key="hltv@$p=crash-looping"
        down+=("$key"); detail[$key]="${nrestarts} automatic restarts since its last clean start"
    fi
done
# <<< ktp-hltv-crashloop

# ---- Disk usage + growth ----
# No df history existed anywhere on this box (sysstat is installed but its
# collector never ran), so the 2026-07-30 syslog runaway was reconstructed from
# file mtimes. 49% used trips no ceiling — the 24h rate is what catches it.
DISK_HISTORY="${DISK_HISTORY:-/var/log/ktp-disk-history.log}"
DISK_PCT_WARN="${DISK_PCT_WARN:-75}"
DISK_GROWTH_WARN_GIB="${DISK_GROWTH_WARN_GIB:-3}"
# Extrapolating GiB/day from a 1h window turns every transient into an alert.
DISK_GROWTH_MIN_HOURS="${DISK_GROWTH_MIN_HOURS:-12}"
# Clear levels, always strictly below the warn level. A value parked on a
# threshold crosses it in both directions hour after hour, and every crossing is
# a Discord alert; between warn and clear the previous verdict is held instead.
DISK_PCT_CLEAR="${DISK_PCT_CLEAR:-$(( DISK_PCT_WARN - 3 ))}"
DISK_GROWTH_CLEAR_GIB="${DISK_GROWTH_CLEAR_GIB:-$(( DISK_GROWTH_WARN_GIB * 2 / 3 ))}"

now_epoch=$(date +%s)
now_ts=$(ts)

if [ ! -e "$DISK_HISTORY" ]; then
    install -m 0640 -o root -g root /dev/null "$DISK_HISTORY" 2>/dev/null || true
fi

# delaycompress in the rotate stanza keeps .1 plain text, so the 24h lookback
# still resolves on the day after a rotation.
disk_history() { cat "$DISK_HISTORY" "$DISK_HISTORY.1" 2>/dev/null || true; }

# >>> ktp-alert-latch — extracted verbatim by tests/unit/test_health_disk_deadband.py
# Bucketing the measured value INTO the key was the first attempt at stopping
# hourly spam, and it moved the problem rather than solving it: "3GiB/day+"
# ticking to "5GiB/day+" still reads to the set comparison as one recovery plus
# one new failure, so the channel announced a recovery that never happened. Over
# 2026-04-20..09-15 that was 14 of the 32 disk-growth alerts. The key is now
# constant for as long as the condition holds, and the magnitude rides along in
# `detail` for the alert body only.
prev_down() { grep -qxF "$1" "$PREV_LIST" 2>/dev/null; }

# latched <key> <value> <warn> <clear> -> 0 if the item should be reported.
# Fires at >= warn. Clears below clear. Between the two it holds whatever the
# last run decided, so a value parked on a threshold cannot oscillate.
latched() {
    local key=$1 val=$2 warn=$3 clear=$4
    [[ $val =~ ^-?[0-9]+$ ]] || return 1
    if [ "$val" -ge "$warn" ]; then return 0; fi
    if [ "$val" -ge "$clear" ] && prev_down "$key"; then return 0; fi
    return 1
}
# <<< ktp-alert-latch

growth_cutoff=$(( now_epoch - DISK_GROWTH_MIN_HOURS * 3600 ))
# -k so the arithmetic stays integer KiB; pseudo-filesystems carry no trend.
inode_rows=$(df -P -i -x tmpfs -x devtmpfs -x squashfs -x overlay 2>/dev/null | tail -n +2 || true)
disk_rows=$(df -P -k -x tmpfs -x devtmpfs -x squashfs -x overlay 2>/dev/null | tail -n +2 || true)

while read -r fs size used avail pct mount; do
    if [ -z "${mount:-}" ]; then continue; fi
    pct=${pct%\%}
    ipct=$(printf '%s\n' "$inode_rows" | awk -v m="$mount" '$6==m {gsub(/%/,"",$5); print $5; exit}')
    printf '%s|%s|DF|%s|%s|%s|%s|%s|%s|%s\n' \
        "$now_ts" "$now_epoch" "$fs" "$mount" "$size" "$used" "$avail" "$pct" "${ipct:-0}" \
        >> "$DISK_HISTORY" || true

    rate=""
    base=$(disk_history | awk -F'|' -v m="$mount" -v c="$growth_cutoff" \
        '$3=="DF" && $5==m && ($2+0)<=c && ($2+0)>best {best=$2+0; u=$7+0}
         END {if (best>0) print best" "u}' || true)
    if [ -n "$base" ]; then
        base_epoch=${base% *}
        base_used=${base#* }
        span=$(( now_epoch - base_epoch ))
        if [ "$span" -gt 0 ]; then
            rate=$(( (used - base_used) * 86400 / span / 1048576 ))
        fi
    fi

    echo "[$now_ts] disk $mount ${pct}% used, inodes ${ipct:-?}%, 24h rate ${rate:-n/a} GiB/day"

    key="disk-usage:${mount}"
    if latched "$key" "$pct" "$DISK_PCT_WARN" "$DISK_PCT_CLEAR"; then
        down+=("$key"); detail[$key]="${pct}% used"
    fi
    key="disk-inodes:${mount}"
    if latched "$key" "${ipct:-}" "$DISK_PCT_WARN" "$DISK_PCT_CLEAR"; then
        down+=("$key"); detail[$key]="${ipct}% of inodes used"
    fi
    key="disk-growth:${mount}"
    if latched "$key" "${rate:-}" "$DISK_GROWTH_WARN_GIB" "$DISK_GROWTH_CLEAR_GIB"; then
        down+=("$key"); detail[$key]="${rate} GiB/day over the last ${DISK_GROWTH_MIN_HOURS}h+"
    fi
done <<< "$disk_rows"

# Largest entries directly under /var/log. -a so single runaway FILES are
# caught (the incident was syslog itself, which no directory listing shows);
# timeout so a slow walk can never wedge the service checks above.
log_top=$(timeout 60 du -kax --max-depth=1 /var/log 2>/dev/null | sort -rn | head -6 || true)
while read -r kb path; do
    if [ -z "${path:-}" ]; then continue; fi
    printf '%s|%s|LOG|%s|%s\n' "$now_ts" "$now_epoch" "$path" "$kb" >> "$DISK_HISTORY" || true
done <<< "$log_top"

# ---- Capture health: is the stats daemon rejecting what the fleet sends? ----
# ktp_capture_health is written on every match half and, until this block, was
# read by nothing on a schedule. Between 2026-09-02 and 09-08 the daemon rejected
# 22-34% of every frag the fleet sent and one match on Dallas 1 lost 87% of its
# events; all of it was recorded in full and found six days later by someone
# looking for a trends dataset. Frags feed player rating. A daemon restart on
# 09-08 fixed it -- nothing here would have said so either.
#
# Per event type over a trailing window, as an integer percentage the latch can
# hold. Post-restart normal is 0 for nine types and under 1% for frag (transit
# loss). Warn at 5%, clear at 2%, and only once enough events have arrived that
# a percentage means anything: one rejected frag in a ten-frag warmup is 10%.
#
# >>> ktp-capture-loss — extracted verbatim by tests/unit/test_health_capture_loss.py
CAPTURE_LOSS_WARN_PCT="${CAPTURE_LOSS_WARN_PCT:-5}"
CAPTURE_LOSS_CLEAR_PCT="${CAPTURE_LOSS_CLEAR_PCT:-2}"
CAPTURE_LOSS_MIN_RECEIVED="${CAPTURE_LOSS_MIN_RECEIVED:-200}"
CAPTURE_LOSS_WINDOW_HOURS="${CAPTURE_LOSS_WINDOW_HOURS:-24}"
# stdin:  event_type<TAB>received<TAB>rejected, one row per type (mysql -N -B).
# stdout: event_type<TAB>pct<TAB>received<TAB>rejected for rows at or above the
#         floor, pct rounded to an integer so `latched` can compare it.
capture_loss_rows() {
    awk -F'\t' -v min="$CAPTURE_LOSS_MIN_RECEIVED" '
        NF >= 3 && $2+0 >= min { printf "%s\t%d\t%d\t%d\n", $1, int(100*$3/$2 + 0.5), $2, $3 }'
}
# <<< ktp-capture-loss

# Root socket, same auth as the migrations and ktp-ac-retention.sh. A failed
# query is its own down item rather than a silent skip: mysql itself being down
# is already CRITICAL_SERVICES, but a dropped table or a revoked grant would
# otherwise read as "capture is clean" forever.
if capture_rows=$(mysql hlstatsx -N -B -e "
        SELECT event_type, SUM(daemon_received), SUM(daemon_rejected)
        FROM ktp_capture_health
        WHERE event_time >= NOW() - INTERVAL ${CAPTURE_LOSS_WINDOW_HOURS} HOUR
        GROUP BY event_type" 2>/dev/null); then
    while IFS=$'\t' read -r etype pct received rejected; do
        if [ -z "${etype:-}" ]; then continue; fi
        echo "[$now_ts] capture ${etype}: ${rejected}/${received} rejected (${pct}%) over ${CAPTURE_LOSS_WINDOW_HOURS}h"
        key="capture-loss:${etype}"
        if latched "$key" "$pct" "$CAPTURE_LOSS_WARN_PCT" "$CAPTURE_LOSS_CLEAR_PCT"; then
            down+=("$key"); detail[$key]="${pct}% of ${received} ${etype} events rejected by the daemon in the last ${CAPTURE_LOSS_WINDOW_HOURS}h"
        fi
    done <<< "$(printf '%s\n' "$capture_rows" | capture_loss_rows)"
else
    down+=("capture-loss=query-failed")
fi

# ---- Hit registration: do the server's own trace hits still turn into damage? ----
# The 2026-09 hitreg investigation (coordination: infra-hitreg-diagnostics)
# ended on one number: of the shot rows where the server's trace hit a live
# enemy cleanly, the share with a ktp_damage_events row for the same
# attacker/victim within 300 ms. 99.9% on 12,204 real hits, every half at
# 99.2-100%. Nothing watched it afterwards; a regression in the plugin, the
# daemon or the engine would look exactly like today until someone re-ran
# the analysis by hand -- the same shape as every incident in
# docs/runbooks/ALERT_COVERAGE.md.
#
# Two steps, both against ktp_hitreg_quality (KTPHLStatsX migration 036):
#   1. score every finished (match, half) that carries target state
#      (ktp_stats_shot_detail on -- 12-mans by default) and has no row yet.
#      One INSERT ... SELECT per run, capped at 25 halves so the first run over
#      a backlog is bounded; idx_damage_pair makes each lookup a seek.
#   2. read the trailing window and latch on misses per thousand -- tenths of
#      a percent, because the latch compares integers and the interesting
#      band is 99.0-99.9%. Warn at 10 (1.0% missed), clear at 5 (0.5%), and
#      only once 300 clean hits have landed so one lost row in a short half
#      does not page.
#   A third item, hitreg-reg=stale, fires when 12-mans finished in the last
#   7 days but none produced a scorable half: shot detail off, a build that
#   stopped emitting tgt_* fields, or the daemon dropping them all read as
#   "quiet", never as clean. Rule: a watcher that can go blind must say so.
#
# >>> ktp-hitreg-reg — extracted verbatim by tests/unit/test_health_hitreg.py
HITREG_WARN_PERMILLE="${HITREG_WARN_PERMILLE:-10}"
HITREG_CLEAR_PERMILLE="${HITREG_CLEAR_PERMILLE:-5}"
HITREG_MIN_CLEAN="${HITREG_MIN_CLEAN:-300}"
HITREG_WINDOW_HOURS="${HITREG_WINDOW_HOURS:-48}"
HITREG_STALE_DAYS="${HITREG_STALE_DAYS:-7}"
HITREG_SCORE_LIMIT="${HITREG_SCORE_LIMIT:-25}"
# stdin:  clean<TAB>registered<TAB>halves, one row (mysql -N -B). Empty/NULL
#         sums (no scorable half in the window) read as zeros.
# stdout: missed_permille<TAB>clean<TAB>registered<TAB>halves, only once
#         clean reaches the floor; rounded to an integer for `latched`.
hitreg_reg_rows() {
    awk -F'\t' -v min="$HITREG_MIN_CLEAN" '
        NF >= 3 && $1 != "NULL" && $1+0 >= min {
            printf "%d\t%d\t%d\t%d\n", int(1000*($1-$2)/$1 + 0.5), $1, $2, $3 }'
}
# <<< ktp-hitreg-reg

# Step 1: score unscored halves. Same root socket and the same failure
# posture as capture-loss: a missing table or revoked grant is a down item,
# not a silent skip that reads as healthy forever.
if ! mysql hlstatsx -N -B -e "
        INSERT INTO ktp_hitreg_quality
            (match_id, half, server_id, match_end, clean_hits, registered_300ms,
             registered_1s, dead_target_hits, teammate_hits)
        SELECT c.match_id, c.half, c.server_id, c.match_end,
               SUM(s.tgt_dead = 0 AND s.tgt_team <> s.shooter_team
                   AND (COALESCE(s.trace_flags, 0) & 15) = 0 AND s.tgt_player_id IS NOT NULL),
               SUM(s.tgt_dead = 0 AND s.tgt_team <> s.shooter_team
                   AND (COALESCE(s.trace_flags, 0) & 15) = 0 AND s.tgt_player_id IS NOT NULL
                   AND EXISTS (SELECT 1 FROM ktp_damage_events d
                               WHERE d.match_id = s.match_id AND d.attacker_id = s.player_id
                                 AND d.victim_id = s.tgt_player_id
                                 AND d.game_time BETWEEN s.game_time - 0.30 AND s.game_time + 0.30)),
               SUM(s.tgt_dead = 0 AND s.tgt_team <> s.shooter_team
                   AND (COALESCE(s.trace_flags, 0) & 15) = 0 AND s.tgt_player_id IS NOT NULL
                   AND EXISTS (SELECT 1 FROM ktp_damage_events d
                               WHERE d.match_id = s.match_id AND d.attacker_id = s.player_id
                                 AND d.victim_id = s.tgt_player_id
                                 AND d.game_time BETWEEN s.game_time - 1.0 AND s.game_time + 1.0)),
               SUM(s.tgt_dead <> 0),
               SUM(s.tgt_dead = 0 AND s.tgt_team = s.shooter_team)
        FROM (SELECT m.match_id, m.half, m.server_id, m.end_time AS match_end
              FROM ktp_matches m
              WHERE m.end_time IS NOT NULL
                AND m.end_time >= NOW() - INTERVAL 14 DAY
                AND m.end_time <= NOW() - INTERVAL 10 MINUTE
                AND NOT EXISTS (SELECT 1 FROM ktp_hitreg_quality q
                                WHERE q.match_id = m.match_id AND q.half = m.half)
                AND EXISTS (SELECT 1 FROM ktp_shot_events s0
                            WHERE s0.match_id = m.match_id AND s0.half = m.half
                              AND s0.tgt_dead IS NOT NULL)
              ORDER BY m.end_time LIMIT ${HITREG_SCORE_LIMIT}) c
        JOIN ktp_shot_events s ON s.match_id = c.match_id AND s.half = c.half
        WHERE s.tgt_dead IS NOT NULL
        GROUP BY c.match_id, c.half, c.server_id, c.match_end
        ON DUPLICATE KEY UPDATE id = id" 2>/dev/null; then
    down+=("hitreg-reg=query-failed")
fi

# Step 2: the trailing window, and staleness against the matches that should
# have been scorable. match_type 2 is KTPMatchHandler's 12-man -- the type the
# fleet runs shot detail on (bitmask 4 = 1 << 2).
if hitreg_row=$(mysql hlstatsx -N -B -e "
        SELECT SUM(clean_hits), SUM(registered_300ms), COUNT(*)
        FROM ktp_hitreg_quality
        WHERE match_end >= NOW() - INTERVAL ${HITREG_WINDOW_HOURS} HOUR" 2>/dev/null); then
    while IFS=$'\t' read -r missed clean registered halves; do
        if [ -z "${missed:-}" ]; then continue; fi
        echo "[$now_ts] hitreg: $((clean - registered))/${clean} clean live-enemy hits with no damage row within 300ms (${missed} per 1000) over ${halves} half(s), ${HITREG_WINDOW_HOURS}h"
        key="hitreg-reg"
        if latched "$key" "$missed" "$HITREG_WARN_PERMILLE" "$HITREG_CLEAR_PERMILLE"; then
            down+=("$key"); detail[$key]="${missed} per 1000 clean live-enemy hits produced no damage row within 300ms (${clean} hits, ${halves} half(s), last ${HITREG_WINDOW_HOURS}h) -- normal is under 2"
        fi
    done <<< "$(printf '%s\n' "$hitreg_row" | hitreg_reg_rows)"
    if stale=$(mysql hlstatsx -N -B -e "
            SELECT (SELECT COUNT(*) FROM ktp_matches
                    WHERE match_type = 2 AND end_time >= NOW() - INTERVAL ${HITREG_STALE_DAYS} DAY),
                   (SELECT COUNT(*) FROM ktp_hitreg_quality
                    WHERE clean_hits > 0 AND match_end >= NOW() - INTERVAL ${HITREG_STALE_DAYS} DAY)" 2>/dev/null); then
        IFS=$'\t' read -r twelve_mans scorable <<< "$stale"
        if [ "${twelve_mans:-0}" -gt 0 ] && [ "${scorable:-0}" -eq 0 ]; then
            down+=("hitreg-reg=stale"); detail["hitreg-reg=stale"]="${twelve_mans} 12-man half(s) finished in the last ${HITREG_STALE_DAYS}d and none carried scorable shot detail -- the emitter, the flag, or the daemon stopped, and registration is unmeasured"
        fi
    fi
else
    down+=("hitreg-reg=query-failed")
fi

# ---- ktp_* tables an analytics session cannot read ----
# A missing per-table SELECT grant does NOT read as "denied". information_schema
# hides what the asking account cannot see, so a capability probe reports the table
# ABSENT, and every consumer downstream concludes the migration never ran. That has
# now cost three separate wrong calls: a "036 is not applied" verdict on 2026-09-22,
# five days of the hitreg monitor's own output being unreadable, and a blocked
# move-census verification on 2026-10-05. The trigger is identical every time -- a
# new ktp_* table lands and nobody grants it. ktp_aim_vis arrived ungranted the same
# day the third one was found.
#
# A log line would not fix it: this file is root:root 0640 and nobody reads it. So
# this ALERTS, which it can only afford to do because the reducer filters the tables
# that are ungranted on purpose -- credential stores, and the dated _bak_/_snap_
# copies. Ruling behind that filter: coordination knowledge/access-and-self-service.md.
# A table that is deliberately locked and NOT matched below will page once; add it
# there with a reason rather than widening the pattern.

# >>> ktp-grants -- extracted verbatim by tests/unit/test_health_grants.py
# Ungranted table names on stdin, one per line; prints only the unexpected ones.
# Pure text, no database, so the policy is testable without privileges.
grants_unexpected() {
    grep -vE '(_bak|_snap|_snapshot|_dups_bak)(_tzfix)?_[0-9]{8}$|_snap_[a-z0-9]+_[0-9]{8}$' \
    | grep -vxE 'ktp_ac_download_tokens|ktp_ac_session_tokens|ktp_ac_web_tokens|ktp_ac_first_login_grants|ktp_ac_players|ktp_ac_detector_review_notes|ktp_ac_identity_review_notes' \
    || true
}
# <<< ktp-grants

GRANT_WATCH_USER="${GRANT_WATCH_USER:-'krodssh'@'localhost'}"
if ungranted=$(mysql -N -B -e "
        SELECT t.TABLE_NAME
          FROM information_schema.TABLES t
          LEFT JOIN information_schema.TABLE_PRIVILEGES p
            ON p.TABLE_SCHEMA = t.TABLE_SCHEMA AND p.TABLE_NAME = t.TABLE_NAME
           AND p.GRANTEE = \"${GRANT_WATCH_USER}\" AND p.PRIVILEGE_TYPE = 'SELECT'
         WHERE t.TABLE_SCHEMA = 'hlstatsx' AND t.TABLE_NAME LIKE 'ktp\\_%'
           AND p.TABLE_NAME IS NULL
         ORDER BY t.TABLE_NAME" 2>/dev/null); then
    _ung=$(printf '%s\n' "$ungranted" | grep -v '^[[:space:]]*$' || true)
    _unexp=$(printf '%s\n' "$_ung" | grants_unexpected | grep -v '^[[:space:]]*$' || true)
    _n_all=$(printf '%s\n' "$_ung" | grep -c . || true)
    _n_unexp=$(printf '%s\n' "$_unexp" | grep -c . || true)
    if [ "${_n_unexp:-0}" -gt 0 ]; then
        _list=$(printf '%s\n' "$_unexp" | paste -sd, -)
        down+=("grants-ungranted")
        detail["grants-ungranted"]="${_n_unexp} ktp_* table(s) with no SELECT for ${GRANT_WATCH_USER}: ${_list} -- an analytics session sees these as ABSENT, not denied, so a probe will report the migration missing"
    fi
    echo "[$now_ts] grants: ${_n_all} ktp_* table(s) ungranted for ${GRANT_WATCH_USER}, ${_n_unexp} unexpected"
else
    down+=("grants=query-failed")
fi

# ---- AC evidence bundles that never reached the API ----
# Six session bundles were lost in the fortnight to 2026-09-22 and nothing
# anywhere said a word. Every one was an aborted transfer: the client stopped
# sending mid-body, nginx answered it directly, and `urt=-` records that
# ktp-ac-api was never contacted -- so no AC-side log, table or counter has a
# trace of the upload. The bundle does not exist and nothing knows it was meant
# to. nginx does log the cause, "client prematurely closed connection", at
# `info` -- below the default `error` level, which is why
# api.ktpdod.com.error.log has been 0 bytes since 2026-07-18. The class is
# invisible by configuration, not by absence.
#
# The access log already carries the whole detector, and the discriminator is
# `urt`, never the status. On 2026-09-20 at 21:03:40 the API itself answered 400
# in 16 ms (urt=0.016) to a 34 KB body: a bundle that arrived and was rejected,
# which is a different thing and already visible AC-side. Internet scanners
# produce `400 urt=-` on `/` all day. Both are excluded by construction. Over
# the 14 retained days the rule below matches five lines and every one is a real
# loss -- four 400s and one 408, four of them inside nine minutes of one
# match-end herd while neighbouring uploads in the same second completed.
#
# Keyed on WORK NOT DONE: the evidence is a request that did not finish, not the
# state of any process. nginx, ktp-ac-api and the uploader are all `active`
# throughout, which is precisely why this needed its own producer.
AC_UPLOAD_ACCESS_LOG="${AC_UPLOAD_ACCESS_LOG:-/var/log/nginx/api.ktpdod.com.access.log}"
AC_UPLOAD_URI="${AC_UPLOAD_URI:-/api/session/upload}"
# 6h, and 24h is the ceiling the files below can honestly cover: logrotate runs
# daily with delaycompress, so `.log` is today and `.log.1` is yesterday, both
# plain text. A longer window would silently read short -- the missing hours
# live in a .gz this never opens, and absent lines look exactly like no aborts.
AC_UPLOAD_WINDOW_HOURS="${AC_UPLOAD_WINDOW_HOURS:-6}"
# One aborted upload is one permanently lost bundle, so the floor is one.
# CLEAR must be >= 1: at 0 the mid-band test `val >= clear` is true for every
# count and the item would never clear again. Raise WARN for a real deadband.
AC_UPLOAD_ABORT_WARN="${AC_UPLOAD_ABORT_WARN:-1}"
AC_UPLOAD_ABORT_CLEAR="${AC_UPLOAD_ABORT_CLEAR:-1}"

# >>> ktp-ac-upload-abort — extracted verbatim by tests/unit/test_health_ac_upload_abort.py
# ac_upload_abort_scan <cutoff-epoch> <uri> <file>... -> key<TAB>value rows.
# The cutoff is an argument rather than read from the clock so the caller, and
# the test, decide the window.
#
# `fieldless` is the leg that makes this survivable across a rotation. rt/urt/rl
# only exist from the 2026-09-16 log_format change onward; every line written
# before it structurally cannot carry urt, and a scan of one of those files
# returns zero aborts out of real traffic -- api.ktpdod.com.access.log.10.gz
# holds 127 uploads and scores 0, which is a lie an operator would act on. So a
# line that is inside the window and carries no urt= is counted, never dropped,
# and the caller raises `unmeasurable` instead of reporting a clean zero. Same
# for a line whose timestamp will not parse: it cannot be placed inside or
# outside the window, so it cannot be dismissed.
ac_upload_abort_scan() {
    python3 - "$@" <<'PY'
import re, sys
from datetime import datetime

cutoff, uri, files = float(sys.argv[1]), sys.argv[2], sys.argv[3:]
# nginx escapes a literal quote inside a logged variable as \x22, so the request
# is always delimited by the first pair of bare quotes on the line.
LINE = re.compile(r'^\S+ \S+ \S+ \[([^\]]+)\] "([^"]*)" (\d{3})\b')
URT = re.compile(r'(?:^| )urt=(\S+)')
RL = re.compile(r'(?:^| )rl=(\d+)')

aborted = fieldless = undated = scanned = uploads = 0
codes, biggest, first, last = {}, 0, None, None
first_at = last_at = 0.0

for path in files:
    try:
        fh = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        # Absent .1 on the day of install is normal; an unreadable primary is
        # the caller's own check, made before this runs.
        continue
    with fh:
        for line in fh:
            m = LINE.match(line)
            if not m:
                if line.strip():
                    undated += 1
                continue
            stamp, request, status = m.group(1), m.group(2), int(m.group(3))
            try:
                at = datetime.strptime(stamp, "%d/%b/%Y:%H:%M:%S %z")
                when = at.timestamp()
            except ValueError:
                undated += 1
                continue
            if when < cutoff:
                continue
            scanned += 1
            urt = URT.search(line)
            if urt is None:
                fieldless += 1
                continue
            parts = request.split()
            if len(parts) < 2 or parts[1].split("?", 1)[0] != uri:
                continue
            uploads += 1
            # urt=- is the whole test: nginx answered without ever reaching the
            # upstream, so the body stopped arriving. A status the API produced
            # carries a duration here and is not this class.
            if status < 400 or urt.group(1) != "-":
                continue
            aborted += 1
            codes[status] = codes.get(status, 0) + 1
            rl = RL.search(line)
            if rl:
                biggest = max(biggest, int(rl.group(1)))
            # Rendered from the parsed stamp, never from the epoch:
            # fromtimestamp() uses the READER's zone, so the same abort printed
            # 15:51:32 on a workstation and 19:51:32 on a UTC runner. An operator
            # takes this straight back to the access log, which is in nginx's
            # local time, so that is the only rendering that greps.
            first = at if first is None or when < first_at else first
            if first is at:
                first_at = when
            last = at if last is None or when > last_at else last
            if last is at:
                last_at = when

out = {"aborted": aborted, "fieldless": fieldless, "undated": undated,
       "scanned": scanned, "uploads": uploads}
if codes:
    out["breakdown"] = ", ".join("%dx%d" % (n, c) for c, n in sorted(codes.items()))
    out["bytes"] = biggest
    out["first"] = first.strftime("%Y-%m-%d %H:%M:%S")
    out["last"] = last.strftime("%Y-%m-%d %H:%M:%S")
for k, v in out.items():
    print("%s\t%s" % (k, v))
PY
}
# <<< ktp-ac-upload-abort

if [ "${AC_UPLOAD_WINDOW_HOURS}" -gt 24 ]; then
    # Refused rather than clamped: a window this code cannot cover would report
    # a count that reads complete and is not.
    key="ac-upload-abort=window-unsupported"
    down+=("$key"); detail[$key]="AC_UPLOAD_WINDOW_HOURS is ${AC_UPLOAD_WINDOW_HOURS}, but only today's and yesterday's access log are read, so anything over 24 would read short and look quiet"
elif [ ! -r "$AC_UPLOAD_ACCESS_LOG" ]; then
    # An absent log is the one input whose zero is indistinguishable from
    # perfect health, so it is a down item rather than a skip.
    key="ac-upload-abort=log-unreadable"
    down+=("$key"); detail[$key]="${AC_UPLOAD_ACCESS_LOG} cannot be read, so aborted uploads are unmeasured -- not zero"
elif acu_rows=$(ac_upload_abort_scan \
        "$(( now_epoch - AC_UPLOAD_WINDOW_HOURS * 3600 ))" \
        "$AC_UPLOAD_URI" \
        "$AC_UPLOAD_ACCESS_LOG" "${AC_UPLOAD_ACCESS_LOG}.1" 2>/dev/null); then
    declare -A acu=()
    while IFS=$'\t' read -r _k _v; do
        if [ -n "${_k:-}" ]; then acu[$_k]=$_v; fi
    done <<< "$acu_rows"
    acu_aborted=${acu[aborted]:-0}
    acu_blind=$(( ${acu[fieldless]:-0} + ${acu[undated]:-0} ))
    echo "[$now_ts] ac-upload: ${acu_aborted} of ${acu[uploads]:-0} session uploads aborted before the API was reached over ${AC_UPLOAD_WINDOW_HOURS}h (${acu[scanned]:-0} lines scanned, ${acu_blind} unreadable)"

    key="ac-upload-abort"
    if latched "$key" "$acu_aborted" "$AC_UPLOAD_ABORT_WARN" "$AC_UPLOAD_ABORT_CLEAR"; then
        # The count lives in `detail`, never in the key. During a match-end herd
        # it ticks 1 -> 3 -> 4 within one window, and a key carrying the number
        # would read to the set comparison as a recovery plus a fresh failure on
        # every tick -- the #388 defect. One burst is one alert.
        down+=("$key")
        acu_extra=""
        if [ -n "${acu[breakdown]:-}" ]; then acu_extra=" (${acu[breakdown]})"; fi
        if [ -n "${acu[bytes]:-}" ]; then acu_extra+=", largest $(( (${acu[bytes]} + 524288) / 1048576 )) MiB already sent"; fi
        if [ -n "${acu[last]:-}" ]; then acu_extra+=", latest ${acu[last]}"; fi
        detail[$key]="${acu_aborted} session upload(s) aborted mid-body in the last ${AC_UPLOAD_WINDOW_HOURS}h${acu_extra} -- ktp-ac-api was never contacted, so those evidence bundles exist nowhere"
    fi
    if [ "$acu_blind" -gt 0 ]; then
        # Reported beside the count, not instead of it: the aborts that WERE
        # scored are still real. What this says is that the window also held
        # lines this cannot score, so the count is a floor.
        key="ac-upload-abort=unmeasurable"
        down+=("$key"); detail[$key]="${acu_blind} of ${acu[scanned]:-0} access-log lines in the window carry no usable rt/urt/rl fields, so the abort count above is a lower bound -- the log_format predates 2026-09-16 or has been changed back"
    fi
else
    down+=("ac-upload-abort=scan-failed")
fi

# ---- Can the detector above still see anything? ----
# `ac-upload-abort` reads ONE access log because exactly one server block writes a
# format carrying $upstream_response_time. That is an accident of api.ktpdod.com
# needing rt/urt/rl for its own reasons, not a decision anyone made about alerting,
# and it has two consequences worth separating.
#
# The gap: an aborted transfer on any OTHER vhost is absent from the error log (all
# of them run at the default `error` level, and "client prematurely closed
# connection" is `info`) AND unclassifiable in the access log (`combined` cannot
# express it). Invisible in both at once. That is known and accepted, so it is
# printed every run and never alerts -- an item that can only clear by someone
# editing nginx would latch down forever and train the reader to ignore it.
#
# The regression: if the upload vhost's format is edited back to `combined`, the
# scanner above returns a clean 0 out of real traffic. `unmeasurable` catches that
# only while the window holds upload lines -- on a quiet night scanned=0 and the
# field could have been gone for days. So the format is asserted against a BASELINE
# of the logs that are supposed to carry it, which is a claim that fails loudly and
# can actually be fixed.
AC_UPLOAD_URT_LOGS="${AC_UPLOAD_URT_LOGS:-/var/log/nginx/api.ktpdod.com.access.log}"

# >>> ktp-ac-upload-coverage — extracted verbatim by tests/unit/test_health_ac_upload_coverage.py
# ac_upload_urt_coverage <nginx-T-dump> <expected-log>... -> key<TAB>value rows.
# The dump is a file argument rather than stdin -- stdin already carries this
# program -- so the caller decides what is judged and the test hands it a fixture.
ac_upload_urt_coverage() {
    python3 - "$@" <<'PY'
import re, sys

dump, expected = sys.argv[1], sys.argv[2:]
lines = open(dump, errors="replace").read().splitlines()

# Formats are collected from the whole dump, not per file: a log_format declared
# inside one vhost file is visible to every vhost, which is itself the coupling
# this reports on. `combined` is nginx's built-in and is declared nowhere.
fmts = {"combined": '$remote_addr $time_local "$request" $status $body_bytes_sent'}
for m in re.finditer(r'log_format\s+(\w+)\s+(.*?);', "\n".join(lines), re.S):
    fmts[m.group(1)] = " ".join(m.group(2).split())

def urt_capable(name):
    return "upstream_response_time" in fmts.get(name, "")

def split_log(value):
    parts = value.split()
    return parts[0], (parts[1] if len(parts) > 1 else "combined")

# http{}-level access_log, i.e. the one every vhost without its own inherits.
starts = [i for i, l in enumerate(lines) if re.match(r'\s*server\s*\{', l.split("#", 1)[0])]
in_server = set()
for start in starts:
    depth = 0
    for j in range(start, len(lines)):
        code = lines[j].split("#", 1)[0]
        depth += code.count("{") - code.count("}")
        in_server.add(j)
        if depth <= 0:
            break
http_log = None
for i, line in enumerate(lines):
    m = re.search(r'\baccess_log\s+([^;]+);', line.split("#", 1)[0])
    if m and i not in in_server:
        http_log = m.group(1).strip()

# Each block is counted with a brace counter that starts fresh AT the block, so a
# miscount elsewhere in the dump cannot quietly shift another vhost's verdict.
blocks, covered, uncovered, seen_logs = 0, [], [], {}
for start in starts:
    depth, end = 0, len(lines) - 1
    for j in range(start, len(lines)):
        code = lines[j].split("#", 1)[0]
        depth += code.count("{") - code.count("}")
        if depth <= 0:
            end = j
            break
    body = [l.split("#", 1)[0] for l in lines[start:end + 1]]
    names = " ".join(" ".join(re.findall(r'\bserver_name\s+([^;]+);', "\n".join(body))).split())
    # Only an access_log at server level sets the block's log; one inside a
    # location{} is an addition to it and cannot be the block's answer.
    depth, own = 0, []
    for l in body:
        m = re.search(r'\baccess_log\s+([^;]+);', l)
        if m and depth == 1:
            own.append(m.group(1).strip())
        depth += l.count("{") - l.count("}")
    path, fmt = split_log(own[0]) if own else (split_log(http_log) if http_log else ("(none)", "combined"))
    blocks += 1
    label = "%s->%s" % (names or "(no server_name)", path.rsplit("/", 1)[-1])
    (covered if urt_capable(fmt) else uncovered).append(label)
    seen_logs.setdefault(path, set()).add(fmt)

# A baseline log that no longer resolves to a urt-capable format is the regression.
# An expected log that appears in NO block is reported the same way rather than
# passing quietly: a detector pointed at a log nothing writes scores a clean zero.
lost = []
for want in expected:
    fmts_for = seen_logs.get(want)
    if not fmts_for:
        lost.append("%s (no server block writes it)" % want)
    elif not any(urt_capable(f) for f in fmts_for):
        lost.append("%s (now %s)" % (want, "/".join(sorted(fmts_for))))

rows = {
    "blocks": blocks,
    "covered": len(covered),
    "uncovered": len(uncovered),
    "formats_urt": ",".join(sorted(k for k in fmts if urt_capable(k))),
    "lost": "; ".join(lost),
    # Duplicates carry a multiplier rather than collapsing: two blocks share one
    # label whenever a vhost has a :443 and a :80 half, and a name list shorter
    # than the count it sits beside reads as a parser that lost something.
    "uncovered_names": ", ".join(
        lbl if uncovered.count(lbl) == 1 else "%s x%d" % (lbl, uncovered.count(lbl))
        for lbl in sorted(set(uncovered))),
}
for k, v in rows.items():
    print("%s\t%s" % (k, v))
PY
}
# <<< ktp-ac-upload-coverage

ACC_DUMP=$(mktemp)
nginx -T > "$ACC_DUMP" 2>/dev/null || :
if [ ! -s "$ACC_DUMP" ]; then
    # Same shape as =log-unreadable: a config that cannot be read tells us nothing
    # about coverage, and "nothing" must not render as "covered".
    key="ac-upload-abort=coverage-unmeasurable"
    down+=("$key"); detail[$key]="nginx -T produced nothing, so it is unknown whether any vhost still logs upstream_response_time -- the abort count above cannot be trusted to have an input"
elif acc_rows=$(ac_upload_urt_coverage "$ACC_DUMP" $AC_UPLOAD_URT_LOGS 2>/dev/null); then
    declare -A acc=()
    while IFS=$'\t' read -r _k _v; do
        if [ -n "${_k:-}" ]; then acc[$_k]=$_v; fi
    done <<< "$acc_rows"
    echo "[$now_ts] ac-upload: ${acc[covered]:-0} of ${acc[blocks]:-0} nginx server blocks write a log that can express an aborted transfer; ${acc[uncovered]:-0} cannot (${acc[uncovered_names]:-none})"
    if [ -n "${acc[lost]:-}" ]; then
        key="ac-upload-abort=coverage-regressed"
        down+=("$key"); detail[$key]="${acc[lost]} -- the aborted-upload detector reads that log, so it will now report 0 out of real traffic"
    fi
else
    down+=("ac-upload-abort=coverage-failed")
fi
rm -f "$ACC_DUMP"

# ---- AC weapon-context store ----
# The API keeps each session's weapon timeline here once the database rows behind
# it are swept, so for every old session it is the only copy. Hit records carry
# victim SteamIDs: a root wider than 0750 hands them to the box's non-root
# accounts, and the writer's own CreateDirectory lands 0755 if it ever has to make
# the root itself.
#
# Freshness is keyed on WORK NOT DONE, never on age alone. Players only run the AC
# on match days, so a quiet week or an off-season writes nothing and is healthy.
# What is not healthy is session bundles continuing to arrive with no sidecar
# following them. A single upload can legitimately produce none -- its bundle
# brought its own timeline, or the server holds no rows for it -- so the leg waits
# for a run of bundles, not one.
WEAPON_CONTEXT_DIR="${WEAPON_CONTEXT_DIR:-/opt/ktp-ac-api/weapon-context}"
AC_UPLOADS_DIR="${AC_UPLOADS_DIR:-/opt/ktp-ac-api/uploads}"
# A write is a WriteAllText then a rename. Anything left in tmp/ this long is a
# write that died between the two.
WEAPON_CONTEXT_TMP_MAX_SEC="${WEAPON_CONTEXT_TMP_MAX_SEC:-3600}"
# Both must hold. The days so one weekly match night that writes nothing cannot
# fire it alone; the bundles because many carry their own timeline and need no
# sidecar, and a whole run of them doing so past a working writer is not plausible.
WEAPON_CONTEXT_STALE_DAYS="${WEAPON_CONTEXT_STALE_DAYS:-7}"
WEAPON_CONTEXT_STALE_MIN_BUNDLES="${WEAPON_CONTEXT_STALE_MIN_BUNDLES:-20}"
# Recompute drains an in-memory queue after the upload, so a younger bundle may
# simply not have been processed yet.
WEAPON_CONTEXT_GRACE_SEC="${WEAPON_CONTEXT_GRACE_SEC:-7200}"
WEAPON_CONTEXT_OWNER_UID="${WEAPON_CONTEXT_OWNER_UID:-0}"

# >>> ktp-weapon-context — extracted verbatim by tests/unit/test_health_weapon_context.py
# weapon_context_scan <store> <uploads> <now-epoch> -> key<TAB>detail, one row per
# fault, nothing when healthy. Keys are fixed tokens and every magnitude rides in
# the detail, because the report is a set-diff against the previous run.
weapon_context_scan() {
    local store=$1 uploads=$2 now=$3
    local stat_out mode owner stale_tmp newest anchor what bundles age_days token
    if [ ! -d "$store" ]; then
        printf 'weapon-context-store=absent\t%s does not exist, so no session timeline is kept once its database rows are swept\n' "$store"
        return 0
    fi
    stat_out=$(stat -c '%a %u' "$store" 2>/dev/null || true)
    mode=${stat_out% *}
    owner=${stat_out#* }
    # Any bit outside rwxr-x--- is wider than 0750, setuid/setgid/sticky included.
    if ! [[ $mode =~ ^[0-7]+$ ]] || (( 8#$mode & ~8#0750 )); then
        printf 'weapon-context-store=too-open\t%s is mode %s, wider than 0750 -- these files carry victim SteamIDs\n' "$store" "${mode:-unreadable}"
    fi
    if [ "$owner" != "$WEAPON_CONTEXT_OWNER_UID" ]; then
        printf 'weapon-context-store=not-root-owned\t%s is owned by uid %s, which can change its mode\n' "$store" "${owner:-unreadable}"
    fi

    stale_tmp=$(timeout 60 find "$store/tmp" -maxdepth 1 -type f \
        ! -newermt "@$(( now - WEAPON_CONTEXT_TMP_MAX_SEC ))" 2>/dev/null | wc -l || true)
    if [ "${stale_tmp:-0}" -gt 0 ]; then
        printf 'weapon-context-store=stale-tmp\t%s in-flight write(s) in %s/tmp older than %ss -- a sidecar write died before its rename\n' \
            "$stale_tmp" "$store" "$WEAPON_CONTEXT_TMP_MAX_SEC"
    fi

    newest=$(timeout 60 find "$store" -path "$store/tmp" -prune -o -type f -name '*.weapons.json' \
        -printf '%T@\n' 2>/dev/null | sort -n | tail -1 || true)
    newest=${newest%%.*}
    if [ -n "$newest" ]; then
        anchor=$newest; what="the newest sidecar"; token=stale
    else
        # An enabled store that never writes reads exactly like a working one on a
        # quiet week, so the root's own mtime stands in until the first sidecar.
        anchor=$(stat -c %Y "$store" 2>/dev/null || true)
        what="the store was created"; token=never-written
    fi
    if ! [[ $anchor =~ ^[0-9]+$ ]]; then
        printf 'weapon-context-store=unmeasurable\tno timestamp could be read from %s\n' "$store"
        return 0
    fi
    age_days=$(( (now - anchor) / 86400 ))
    if [ "$age_days" -lt "$WEAPON_CONTEXT_STALE_DAYS" ]; then
        return 0
    fi
    if [ ! -d "$uploads" ]; then
        # Without the input, "no sidecars" cannot be told apart from "no matches".
        printf 'weapon-context-store=unmeasurable\t%s is missing, so whether sidecars keep up with uploads is unknown -- not fine\n' "$uploads"
        return 0
    fi
    bundles=$(timeout 60 find "$uploads" -type f -name '*.zip' -newermt "@$anchor" \
        ! -newermt "@$(( now - WEAPON_CONTEXT_GRACE_SEC ))" 2>/dev/null | wc -l || true)
    if [ "${bundles:-0}" -ge "$WEAPON_CONTEXT_STALE_MIN_BUNDLES" ]; then
        printf 'weapon-context-store=%s\t%s session bundle(s) arrived after %s %sd ago and no sidecar followed them\n' \
            "$token" "$bundles" "$what" "$age_days"
    fi
}
# <<< ktp-weapon-context

if wcs_rows=$(weapon_context_scan "$WEAPON_CONTEXT_DIR" "$AC_UPLOADS_DIR" "$now_epoch"); then
    echo "[$now_ts] weapon-context: ${wcs_rows:-ok}"
    while IFS=$'\t' read -r _key _note; do
        if [ -z "${_key:-}" ]; then continue; fi
        down+=("$_key"); detail[$_key]="$_note"
    done <<< "$wcs_rows"
else
    down+=("weapon-context-store=scan-failed")
fi

# ---- Build sorted lists for set comparison ----
# curr.list: sorted, deduplicated set of currently-down items
# prev.list: read at the top of the run, because the disk checks latch on it
TMP_CURR=$(mktemp) TMP_PREV="$PREV_LIST"

if [ ${#down[@]} -gt 0 ]; then
    printf '%s\n' "${down[@]}" | sort -u > "$TMP_CURR"
else
    : > "$TMP_CURR"
fi

# ---- Compute transitions via comm ----
# comm -23: lines only in curr (new_down)
# comm -13: lines only in prev (recovered)
mapfile -t new_down < <(comm -23 "$TMP_CURR" "$TMP_PREV")
mapfile -t recovered < <(comm -13 "$TMP_CURR" "$TMP_PREV")

# ---- State save (called AFTER a successful alert, or on no-transition runs) ----
# Persisting before the Discord POST permanently consumed the edge on a failed
# delivery (the relay has no queue) — the transition became "known state" and
# never re-alerted. Now a failed POST leaves the previous state intact so the
# next hourly run re-detects the same transitions and retries the alert.
# Accepted trade: a service that flaps down AND back up entirely between a
# failed-POST run and the next run produces no alert for either edge (the
# recovered state matches the stale prev). Sub-hour flap + relay outage
# coinciding — rarer and less important than losing a persistent-down alert.
# >>> ktp-health-state — extracted verbatim by tests/unit/test_health_state_since.py
# health_state_document <down-json-array> <prev-state-json> <detail-json-object> <ts> [fault-json-object]
# `since` is a DETECTION date: the first run of THIS check that saw the item.
# Carried forward while the item stays down, stamped now when it is new, dropped
# when it clears. It is not when the fault started, and a fault older than the
# check that watches it reads as new -- ktp-identity-reconcile failed 2026-09-08
# and was stamped 2026-09-17, the hour the `failed-unit:` producer first ran.
# `fault_since` is the onset where an independent durable signal says so: sparse
# like `detail`, absent rather than null when nothing knows. It is clamped to
# `since` and to its own carried value, so it only ever moves EARLIER while an
# item stays down -- the reported age can grow but never shrink, which keeps a
# consumer's threshold on the safe side of this change.
health_state_document() {
    local down_json="$1" prev_json="$2" detail_json="$3" now="$4" fault_json="${5:-}"
    [ -n "$fault_json" ] || fault_json='{}'
    jq -n --argjson d "$down_json" --argjson prev "$prev_json" \
          --argjson det "$detail_json" --argjson flt "$fault_json" --arg ts "$now" '
        ($prev.since // {}) as $was
        | ($prev.fault_since // {}) as $wasf
        | ($d | map({key: ., value: ($was[.] // $ts)}) | from_entries) as $since
        | {updated_at: $ts,
           down: $d,
           since: $since,
           fault_since: ($d
             | map({key: ., value: ([$wasf[.], $flt[.], $since[.]]
                                    | map(select(. != null and . != "")) | min)})
             | from_entries | with_entries(select(.value != null and .value != $since[.key]))),
           detail: ($d | map({key: ., value: ($det[.] // "")}) | from_entries
                    | with_entries(select(.value != "")))}'
}

# fault_since_probe <down-item> -> an onset timestamp on stdout, or nothing.
# Only `failed-unit:<name>` has a durable independent signal here: systemd's
# InactiveEnterTimestamp, which outlives journald (about two days on this box)
# and syslog rotation (about a week). It resets when a periodic unit re-runs and
# fails again, so it is a LOWER BOUND on the outage, not its start -- the carry
# forward in health_state_document is what keeps the earlier answer once seen.
# Nothing is printed for any other item class; guessing is worse than silence.
fault_since_probe() {
    local item="$1" unit show raw
    case "$item" in failed-unit:*) unit="${item#failed-unit:}" ;; *) return 0 ;; esac
    # One call, parsed BY NAME: systemd returns properties in its own order,
    # never the requested one. LoadState is the mandatory guard -- a unit that
    # does not exist answers inactive/dead, byte-identical to a stopped one, and
    # only not-found vs loaded tells them apart. ActiveState matters because
    # InactiveEnterTimestamp on a RUNNING unit is the last time it stopped,
    # which would date a fault from a healthy restart weeks ago.
    show=$(systemctl show "$unit" -p LoadState -p ActiveState -p InactiveEnterTimestamp 2>/dev/null || true)
    [ "$(sed -n 's/^LoadState=//p' <<< "$show")" = "loaded" ] || return 0
    [ "$(sed -n 's/^ActiveState=//p' <<< "$show")" = "failed" ] || return 0
    raw=$(sed -n 's/^InactiveEnterTimestamp=//p' <<< "$show")
    # `date -d ""` prints TODAY at midnight and exits 0, so an unset property
    # would land as a fresh timestamp -- the one direction that hides a fault.
    # Match systemd's own shape before letting date near it.
    case "$raw" in
        [A-Z][a-z][a-z]" "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]" "[0-9][0-9]:[0-9][0-9]:[0-9][0-9]*) ;;
        *) return 0 ;;
    esac
    date -d "$raw" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || true
}
# <<< ktp-health-state

save_state() {
    mkdir -p "$(dirname "$STATE_FILE")"
    local down_json prev_json detail_json fault_json k onset
    if [ -s "$TMP_CURR" ]; then
        down_json=$(jq -R . < "$TMP_CURR" | jq -s .)
    else
        down_json='[]'
    fi
    # An EMPTY state file makes jq print nothing and exit 0, so the `||` never
    # fires and `--argjson prev ""` below aborts the run. See the redirect at the
    # end of this function for how the file came to be empty.
    prev_json=$(jq -c . < "$STATE_FILE" 2>/dev/null || true)
    [ -n "$prev_json" ] || prev_json='{}'
    detail_json='{}'
    # Guarded: "${!detail[@]}" on an empty associative array is an unbound
    # variable under `set -u` on bash < 4.4.
    if [ ${#detail[@]} -gt 0 ]; then
        for k in "${!detail[@]}"; do
            detail_json=$(jq -c --arg k "$k" --arg v "${detail[$k]}" '. + {($k): $v}' <<< "$detail_json")
        done
    fi
    # One `systemctl show` per currently-down item, on a set that is normally
    # empty and has never been large. Silent for every item class that has no
    # durable signal, which is most of them.
    fault_json='{}'
    while read -r k; do
        [ -n "${k:-}" ] || continue
        onset=$(fault_since_probe "$k")
        [ -n "$onset" ] || continue
        fault_json=$(jq -c --arg k "$k" --arg v "$onset" '. + {($k): $v}' <<< "$fault_json")
    done < "$TMP_CURR"
    # Via a temp file, because `> "$STATE_FILE"` truncates BEFORE jq runs: a jq
    # that fails here left a zero-byte state file, which the read above then
    # turned into an empty --argjson and an abort — on this run and on every run
    # after it, until someone deleted the file by hand. A check that breaks
    # itself permanently on its first bad hour is worse than no check.
    health_state_document "$down_json" "$prev_json" "$detail_json" "$(ts)" "$fault_json" > "$STATE_FILE.tmp"
    mv -f "$STATE_FILE.tmp" "$STATE_FILE"
}

# ---- Alert on transitions only ----
if [ ${#new_down[@]} -eq 0 ] && [ ${#recovered[@]} -eq 0 ]; then
    save_state
    echo "[$(ts)] no transitions (currently down: ${#down[@]})"
    exit 0
fi

# Names alongside the counts — without them, a recovered blip is
# undiagnosable after the fact, since only the Discord embed carries which
# item transitioned.
new_down_names=$(join_keys "${new_down[@]}")
recovered_names=$(join_keys "${recovered[@]}")
echo "[$(ts)] TRANSITIONS: new_down=${#new_down[@]}${new_down_names:+ [${new_down_names}]} recovered=${#recovered[@]}${recovered_names:+ [${recovered_names}]}"

# Build Discord embed body
desc=""
if [ ${#new_down[@]} -gt 0 ]; then
    desc+='⚠️ **Services down:**'$'\n'
    for x in "${new_down[@]}"; do
        desc+="• \`${x}\`${detail[$x]:+ — ${detail[$x]}}"$'\n'
    done
fi
if [ ${#recovered[@]} -gt 0 ]; then
    [ -n "$desc" ] && desc+=$'\n'
    desc+='✅ **Recovered:**'$'\n'
    for x in "${recovered[@]}"; do
        desc+="• \`${x}\`"$'\n'
    done
fi

# Still-down services (persistent, informational footer)
if [ ${#down[@]} -gt 0 ]; then
    mapfile -t down_sorted < <(printf '%s\n' "${down[@]}" | sort -u)
    current_list=$(join_keys "${down_sorted[@]}")
    if [ -n "$current_list" ]; then
        desc+=$'\n''_All currently down: '"${current_list}"'_'
    fi
fi

# Colour, glyph, lane and channel from the shared routing helper; see
# health_alert_route above for what happens when it is not deployed yet.
health_alert_route "${#new_down[@]}"

payload=$(jq -n \
    --arg ch "$KTP_ALERT_CHANNEL" \
    --arg title "${KTP_ALERT_GLYPH:+$KTP_ALERT_GLYPH }<:KTP:1002382703020212245> KTP Data Server Health" \
    --arg desc "$desc" \
    --arg footer "ktp-data-server-health @ $(TZ=America/New_York date '+%Y-%m-%d %H:%M %Z')" \
    --argjson color "$KTP_ALERT_COLOR" \
    '{channelId: $ch, embeds: [{title: $title, description: $desc, color: $color, footer: {text: $footer}}]}')

http=$(curl -sS -o /tmp/ktp-health-resp.txt -w "%{http_code}" \
    -X POST "${RELAY_URL:-}" \
    -H "X-Relay-Auth: ${AUTH_SECRET:-}" \
    -H "Content-Type: application/json" \
    -d "$payload" 2>&1 || echo "000")
if [ "$http" != "200" ] && [ "$http" != "204" ]; then
    echo "[$(ts)] WARN: relay returned HTTP $http: $(cat /tmp/ktp-health-resp.txt 2>/dev/null | head -c 200)" >&2
    echo "[$(ts)] state NOT saved — transitions will re-alert on the next run" >&2
else
    save_state
    # Routing decisions in the log, so "why did that land there" is answerable
    # from this file rather than from Discord.
    echo "[$(ts)] alert posted (HTTP $http) severity=$KTP_ALERT_SEVERITY lane=$KTP_ALERT_LANE channel=$KTP_ALERT_CHANNEL via=$KTP_ALERT_CHANNEL_SOURCE"
fi
