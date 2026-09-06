#!/usr/bin/env bash
# ktp-tier2-heartbeat — alert if the Tier 2 integration suite has gone quiet.
#
# Tier 2 runs nightly (schedule) + on integration-test PRs, on a self-hosted
# runner. If the runner dies or the schedule breaks, the suite silently stops —
# and "no signal" looks identical to "all green". This watches the last-run
# markers the workflow writes (tier2-integration.yml "Record Tier 2 last-run
# marker" step) and alerts to Discord on a state transition. The watcher must
# NOT share fate with the watched, so this runs as a plain data-server cron, not
# on the GH runner.
#
# TWO markers, watched independently and reported BY NAME:
#   - tier2-last-run.json          (the `main` leg — what the fleet runs)
#   - tier2-last-run-preprod.json  (the `preprod` leg — what staging exercises)
# The workflow's nightly schedule writes both (matrix.target_ref: preprod +
# main), but PR-triggered runs only ever stamp the leg they targeted. Watching
# only one of the two is the exact blind spot this script used to have: it
# watched `tier2-last-run.json` alone, so a false alarm fired claiming the
# runner was offline/broken (65h "since last run") while the runner was
# active/running with 0 restarts and had completed a `preprod` job 35 minutes
# earlier — that run simply never touched the marker this script was reading.
# Fix is structural, not a wider threshold: check both, name both in every
# alert, and let either one going stale be visible as *which one*. Do not
# collapse this back to "either marker is fine" — that reintroduces the same
# blind spot with different marker.
#
# Open question this does NOT resolve: whether `preprod` is a permanent lane
# or folds back into `main` after the pending ABI wave activates. This design
# does not need to know. If preprod stays permanent, both checks keep firing
# forever and that's correct. If preprod is retired, its nightly leg stops
# being scheduled, its marker goes stale, and — left alone — this script would
# alert on that forever, which is now a false alarm about a lane nobody is
# running. At that point set KTP_TIER2_WATCH_PREPROD=0 (one config line, no
# code edit) to stop watching it; don't repoint KTP_TIER2_MARKER_PREPROD at
# the main marker; that silently makes both checks watch the same file, which
# has the same blind spot as watching one marker.
#
# Also watches for runner stack drift vs the fleet (ktp-tier2-stack-drift.py):
# a stale module stack makes green runs certify an environment that exists
# nowhere — caught drifted 06-28→07-10 (.926 engine, never-shipped dev dodx).
#
# And counts Runner.Listener processes. `systemctl restart` only reaches the
# unit's cgroup, so a listener that has been re-parented to PID 1 survives it
# and answers jobs alongside the new one. On 2026-09-03 that raced two workers
# onto one job: the systemd one lost on a shared _diag/pages file and exited
# 102 in two seconds, and every visible symptom pointed elsewhere — the job log
# ended in `Failed to CreateArtifact: (403) Forbidden` (the token had been
# invalidated by the duplicate worker) and the suite step read "The operation
# was canceled", so the innocent PR under it looked like the cause. Nothing
# about a second listener is visible from the unit's status, the job log, or
# the run markers above; the count is the only honest signal, and PPID 1 is the
# tell that names which one is the orphan.
#
# Mirrors scripts/ktp-data-server-health.sh: state-file so we alert on
# transitions only (no chat spam while persistently down), relay creds from
# /etc/ktp/discord-relay.conf.
#
# Install (on the data server):
#   sudo cp scripts/ktp-tier2-heartbeat.sh /usr/local/bin/
#   sudo cp scripts/ktp-tier2-stack-drift.py /usr/local/bin/
#   sudo cp scripts/ktp-tier2-heartbeat.cron /etc/cron.d/ktp-tier2-heartbeat
set -euo pipefail

CONFIG="${KTP_RELAY_CONFIG:-/etc/ktp/discord-relay.conf}"
MARKER="${KTP_TIER2_MARKER:-/opt/ktp-tier2-runner/tier2-last-run.json}"
WATCH_PREPROD="${KTP_TIER2_WATCH_PREPROD:-1}"
MARKER_PREPROD="${KTP_TIER2_MARKER_PREPROD:-$(dirname "$MARKER")/tier2-last-run-preprod.json}"
STATE="${KTP_TIER2_HEARTBEAT_STATE:-/var/lib/ktp-tier2-heartbeat.state}"
# One registered runner on this box today. Raise this if a second is ever
# registered — the assertion is "the number we expect", not "at most one".
WATCH_LISTENERS="${KTP_TIER2_WATCH_LISTENERS:-1}"
EXPECTED_LISTENERS="${KTP_TIER2_EXPECTED_LISTENERS:-1}"
LISTENER_PATTERN="${KTP_TIER2_LISTENER_PATTERN:-Runner.Listener}"
# 36h: nightly cadence (24h) + a full skipped day of margin before we cry wolf.
MAX_AGE_SECONDS="${KTP_TIER2_MAX_AGE:-129600}"
MAX_AGE_SECONDS_PREPROD="${KTP_TIER2_MAX_AGE_PREPROD:-$MAX_AGE_SECONDS}"
# Default to the shared scheduled-report channel (perf-rollup / canary / tier2
# embeds). Override with TIER2_REPORT_CHANNEL in the relay conf.
CHANNEL_DEFAULT="1498813261263405097"

# Relay creds (KEY="value" lines). Same file the workflow embed step reads.
# `if`, not `[ -f x ] && .`: with `set -e` a missing conf made the watcher exit
# 1 before it checked anything, so the one thing that reports silence would
# itself have gone silent. The no-creds path below is the intended behaviour.
# shellcheck disable=SC1090
if [ -f "$CONFIG" ]; then . "$CONFIG"; fi
RELAY_URL="${RELAY_URL:-}"
AUTH_SECRET="${AUTH_SECRET:-}"
CHANNEL="${TIER2_REPORT_CHANNEL:-$CHANNEL_DEFAULT}"

now="$(date +%s)"

# ── Determine one marker's health state — called once per leg ───────────────
# Emits "<state>\x1f<detail>" on stdout; state is one of ok/stale/failed.
check_marker() {
    local path="$1" label="$2" max_age="$3"
    local m_state="ok" m_detail m_ts m_outcome m_run_id m_age
    if [ ! -f "$path" ]; then
        m_state="stale"
        m_detail="$label: no run marker at \`$path\` — has this leg ever run on this runner?"
    else
        m_ts="$(jq -r '.ts // 0' "$path" 2>/dev/null || echo 0)"
        m_outcome="$(jq -r '.outcome // "unknown"' "$path" 2>/dev/null || echo unknown)"
        m_run_id="$(jq -r '.run_id // "?"' "$path" 2>/dev/null || echo '?')"
        m_age=$(( now - m_ts ))
        if [ "$m_ts" -eq 0 ] || [ "$m_age" -gt "$max_age" ]; then
            m_state="stale"
            m_detail="$label: last run $((m_age / 3600))h ago (threshold $((max_age / 3600))h) — offline or schedule broken?"
        elif [ "$m_outcome" != "success" ]; then
            # Anything that is not an explicit success is unhealthy. This used to
            # test `= "failure"`, which let every OTHER non-success outcome read
            # as green: on 2026-08-09 and 08-10 the suite wedged in teardown,
            # GitHub killed the job at its 30m ceiling, the workflow recorded
            # outcome="cancelled" — and this heartbeat reported ok both mornings
            # while the suite had not completed once. An allowlist is the only
            # shape that cannot be widened by a new outcome string upstream.
            m_state="failed"
            m_detail="$label: last run (\`$m_run_id\`) did not succeed (outcome: \`$m_outcome\`), $((m_age / 3600))h ago."
        else
            m_detail="$label: healthy — last run $((m_age / 3600))h ago."
        fi
    fi
    printf '%s\x1f%s\n' "$m_state" "$m_detail"
}

main_result="$(check_marker "$MARKER" "main" "$MAX_AGE_SECONDS")"
main_state="${main_result%%$'\x1f'*}"
main_detail="${main_result#*$'\x1f'}"

if [ "$WATCH_PREPROD" = "1" ]; then
    preprod_result="$(check_marker "$MARKER_PREPROD" "preprod" "$MAX_AGE_SECONDS_PREPROD")"
    preprod_state="${preprod_result%%$'\x1f'*}"
    preprod_detail="${preprod_result#*$'\x1f'}"
else
    preprod_state="ok"
    preprod_detail="preprod: not watched (KTP_TIER2_WATCH_PREPROD=0)"
fi

# Worst-of drives the headline bucket; both lines always ride in the body
# regardless of which one is worse — that's the point of watching two.
rank() { case "$1" in failed) echo 2 ;; stale) echo 1 ;; *) echo 0 ;; esac; }
if [ "$(rank "$main_state")" -ge "$(rank "$preprod_state")" ]; then
    state="$main_state"
else
    state="$preprod_state"
fi
detail="$main_detail"$'\n'"$preprod_detail"

# ── Stack-drift check — runs whatever the last run did ───────────────────────
# The runner's module stack must track the fleet (tier2-runner-architecture);
# this makes drift loud instead of checklist-enforced. Deliberate leads (runner
# ahead of fleet as a pre-activation gate) alert once and self-recover after
# the fleet activates. Checker exit 2 = couldn't check (transient SSH etc.) —
# log only, never flap the state.
#
# This used to be gated on `state = ok`, which meant a red Tier 2 switched the
# wave tripwire off: the suite went red 2026-08-04 and the drift check did not
# run again for four days, with a .930 engine staged the whole time. One check
# quietly disarming another is the failure mode to design against, so the two
# are now independent — a failing run still outranks drift for the headline,
# but drift is always measured and always carried in the body.
DRIFT_CHECKER="${KTP_TIER2_DRIFT_CHECKER:-/usr/local/bin/ktp-tier2-stack-drift.py}"
AGG_ENV="${KTP_AGGREGATOR_ENV:-/opt/ktp-profile-aggregator/.env}"
AGG_PY="${KTP_AGGREGATOR_PY:-/opt/ktp-profile-aggregator/venv/bin/python}"
drifted=0
if [ -x "$AGG_PY" ] && [ -f "$DRIFT_CHECKER" ]; then
    drift_out="$(set -a; . "$AGG_ENV" 2>/dev/null; set +a; "$AGG_PY" "$DRIFT_CHECKER" 2>&1)" && drift_rc=0 || drift_rc=$?
    if [ "$drift_rc" -eq 1 ]; then
        drifted=1
        drift_note="$drift_out — re-sync the runner stack from the fleet (or dismiss if the runner is deliberately leading a staged wave)."
        if [ "$state" = "ok" ]; then
            state="drift"
            detail="$detail"$'\n\n'"$drift_note"
        else
            detail="$detail"$'\n\n'"⚠️ **Stack drift too:** $drift_note"
        fi
    elif [ "$drift_rc" -ge 2 ]; then
        echo "tier2-heartbeat: drift check inconclusive (rc=$drift_rc): $drift_out"
    fi
fi

# ── Runner listener count — the double-dispatch tripwire ─────────────────────
# Both directions are faults, and neither is visible upstream: MORE than
# expected means two workers are racing the same job (and the loser's failure
# gets blamed on whatever PR it was carrying), FEWER means the runner is not
# listening at all — which the marker checks above only notice 36h later.
#
# This overrides the headline rather than joining the body, because a duplicate
# listener MANUFACTURES the failures the other checks report: reading "a leg
# failed" first sends you to bisect a PR that was never at fault.
listener_state="ok"
listener_n="$EXPECTED_LISTENERS"
listener_detail="listeners: not watched (KTP_TIER2_WATCH_LISTENERS=0)"
if [ "$WATCH_LISTENERS" = "1" ]; then
    listener_ps="$(ps -eo pid,ppid,args 2>/dev/null | grep -F "$LISTENER_PATTERN" | grep -v grep || true)"
    if [ -z "$listener_ps" ]; then
        listener_n=0
    else
        listener_n="$(printf '%s\n' "$listener_ps" | wc -l | tr -d ' ')"
    fi
    if [ "$listener_n" -eq "$EXPECTED_LISTENERS" ]; then
        listener_detail="listeners: $listener_n (expected $EXPECTED_LISTENERS)."
    elif [ "$listener_n" -gt "$EXPECTED_LISTENERS" ]; then
        listener_state="duplicate"
        listener_detail="listeners: **$listener_n** running, expected $EXPECTED_LISTENERS — two workers can answer the same job."$'\n'"A \`PPID 1\` line below is a re-parented orphan that outlived a \`systemctl restart\`; kill that pid, then restart the unit."$'\n'"\`\`\`"$'\n'"$listener_ps"$'\n'"\`\`\`"
    else
        listener_state="absent"
        listener_detail="listeners: **$listener_n** running, expected $EXPECTED_LISTENERS — nothing is listening for jobs."
    fi
fi
detail="$listener_detail"$'\n'"$detail"
[ "$listener_state" = "ok" ] || state="listeners"

# State-file key names EVERY input that can change independently: main marker
# state, preprod marker state, drift flag. A single combined "state" bucket
# would hide a change that doesn't move the bucket — e.g. main flips ok->stale
# while preprod is already stale: the worst-of `state` stays "stale" and a
# key built from that alone would never re-alert on the new information. Same
# class of bug the drift check below already had to be pulled out of.
key="main=$main_state,preprod=$preprod_state"
[ "$drifted" = "1" ] && key="$key,drift=1"
[ "$WATCH_LISTENERS" = "1" ] && key="$key,listeners=$listener_n"

# State file is "<key>|<epoch of last alert>". Older files hold a bare
# single-value state (pre-two-marker); those never match the new key format,
# so the first run after this upgrade re-alerts if we are currently down —
# same "treat unrecognized as never-alerted" precedent as before.
raw="$(cat "$STATE" 2>/dev/null || echo "")"
prev="${raw%%|*}"
prev_alert="${raw#*|}"
case "$prev_alert" in (*[!0-9]*|"") prev_alert=0 ;; esac
now="$(date +%s)"

# Transition-only alerting meant a persistent outage was announced exactly once.
# The runner was dead 126h; the alert fired correctly on day one, during LAN
# week, and was never repeated — so it read as background chatter and was missed.
# Re-alert on a slow cadence while still down. `ok` is excluded: there is nothing
# to nag about once recovered.
REALERT_SECONDS="${KTP_TIER2_REALERT_SECONDS:-86400}"
repeat=0
if [ "$key" = "$prev" ]; then
    if [ "$state" = "ok" ]; then
        echo "tier2-heartbeat: state=ok (unchanged) — no alert"
        exit 0
    fi
    if [ "$((now - prev_alert))" -lt "$REALERT_SECONDS" ]; then
        echo "tier2-heartbeat: state=$key (unchanged, last alert $(( (now - prev_alert) / 3600 ))h ago) — no alert"
        exit 0
    fi
    repeat=1
fi

# ── Build + post the transition embed ────────────────────────────────────────
case "$state" in
    ok)     title="✅ KTP Tier 2 — recovered"; desc="Tier 2 integration suite healthy (running + stack in sync)."$'\n\n'"$detail"; color=5763719 ;;
    failed) title="❌ KTP Tier 2 — a leg failed"; desc="$detail"; color=15548997 ;;
    # Leads the embed even over a failed leg: a second listener is the cause a
    # failed leg is the symptom of, and the job log blames the innocent PR.
    listeners)
            if [ "$listener_state" = "duplicate" ]; then
                title="🚨 KTP Tier 2 — DUPLICATE runner listener"
            else
                title="🚨 KTP Tier 2 — no runner listener"
            fi
            desc="$detail"; color=15548997 ;;
    # Say the suite passed. `drift` is only reachable from state=ok, so this is
    # always true here — and after a red spell the state goes failed → drift
    # without passing through ok, so nothing else ever announces the recovery.
    drift)  title="⚠️ KTP Tier 2 — runner stack drifted from fleet"
            desc="**Both legs ran and passed** — this is about the runner's binaries, not the tests."$'\n\n'"$detail"
            color=16763904 ;;
    *)      title="⚠️ KTP Tier 2 — a leg is not running"; desc="$detail"; color=16763904 ;;
esac
if [ "$repeat" = "1" ]; then
    title="$title — STILL DOWN"
    if [ "$prev_alert" -eq 0 ]; then
        # legacy bare state file: there is no alert timestamp to subtract from,
        # and "496151h ago" (epoch 0) is worse than saying we don't know
        note="Still in this state. No previous alert on record — this watcher was upgraded since the last one."
    else
        note="Still in this state; last alerted $(( (now - prev_alert) / 3600 ))h ago. This is a repeat, not a new failure."
    fi
    desc="$desc"$'\n\n'"$note"
fi
footer="ktp-tier2-heartbeat @ $(TZ=America/New_York date '+%Y-%m-%d %H:%M %Z')"

if [ -z "$RELAY_URL" ] || [ -z "$AUTH_SECRET" ]; then
    echo "tier2-heartbeat: relay creds missing in $CONFIG — would have alerted: $title — $desc" >&2
    exit 0
fi

payload="$(jq -n \
    --arg ch "$CHANNEL" --arg title "$title" --arg desc "$desc" \
    --argjson color "$color" --arg footer "$footer" \
    '{channelId: $ch, embeds: [{title: $title, description: $desc, color: $color, footer: {text: $footer}}]}')"

http="$(curl -sS -o /tmp/ktp-tier2-heartbeat-resp.txt -w '%{http_code}' \
    -X POST "$RELAY_URL" \
    -H "X-Relay-Auth: $AUTH_SECRET" \
    -H "Content-Type: application/json" \
    -d "$payload" 2>&1 || echo "000")"

# Consume the edge only once the alert is actually out. Stamping before the
# post — which is what the old code did, despite its comment saying otherwise —
# meant a relay blip silently ate the transition, and a dropped `ok` is gone for
# good because recovery never re-alerts. A persistent relay outage re-posting
# every cycle is the correct louder failure.
case "$http" in
    2*) echo "$key|$now" > "$STATE" 2>/dev/null || true ;;
    *)  echo "tier2-heartbeat: relay POST failed (HTTP $http) — state file NOT advanced, will retry" >&2 ;;
esac
echo "tier2-heartbeat: state $prev -> $key, relay HTTP $http"
