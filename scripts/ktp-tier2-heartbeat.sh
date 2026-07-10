#!/usr/bin/env bash
# ktp-tier2-heartbeat — alert if the Tier 2 integration suite has gone quiet.
#
# Tier 2 runs nightly (schedule) + on integration-test PRs, on a self-hosted
# runner. If the runner dies or the schedule breaks, the suite silently stops —
# and "no signal" looks identical to "all green". This watches the last-run
# marker the workflow writes (tier2-integration.yml "Record Tier 2 last-run
# marker" step) and alerts to Discord on a state transition. The watcher must
# NOT share fate with the watched, so this runs as a plain data-server cron, not
# on the GH runner.
#
# Also watches for runner stack drift vs the fleet (ktp-tier2-stack-drift.py):
# a stale module stack makes green runs certify an environment that exists
# nowhere — caught drifted 06-28→07-10 (.926 engine, never-shipped dev dodx).
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
STATE="${KTP_TIER2_HEARTBEAT_STATE:-/var/lib/ktp-tier2-heartbeat.state}"
# 36h: nightly cadence (24h) + a full skipped day of margin before we cry wolf.
MAX_AGE_SECONDS="${KTP_TIER2_MAX_AGE:-129600}"
# Default to the shared scheduled-report channel (perf-rollup / canary / tier2
# embeds). Override with TIER2_REPORT_CHANNEL in the relay conf.
CHANNEL_DEFAULT="1498813261263405097"

# Relay creds (KEY="value" lines). Same file the workflow embed step reads.
# shellcheck disable=SC1090
[ -f "$CONFIG" ] && . "$CONFIG"
RELAY_URL="${RELAY_URL:-}"
AUTH_SECRET="${AUTH_SECRET:-}"
CHANNEL="${TIER2_REPORT_CHANNEL:-$CHANNEL_DEFAULT}"

now="$(date +%s)"

# ── Determine current health state ───────────────────────────────────────────
state="ok"
detail=""
if [ ! -f "$MARKER" ]; then
    state="stale"
    detail="no Tier 2 run marker at \`$MARKER\` — has the suite ever run on this runner?"
else
    ts="$(jq -r '.ts // 0' "$MARKER" 2>/dev/null || echo 0)"
    outcome="$(jq -r '.outcome // "unknown"' "$MARKER" 2>/dev/null || echo unknown)"
    run_id="$(jq -r '.run_id // "?"' "$MARKER" 2>/dev/null || echo '?')"
    age=$(( now - ts ))
    if [ "$ts" -eq 0 ] || [ "$age" -gt "$MAX_AGE_SECONDS" ]; then
        state="stale"
        detail="last Tier 2 run was $((age / 3600))h ago (threshold $((MAX_AGE_SECONDS / 3600))h) — runner offline or schedule broken?"
    elif [ "$outcome" = "failure" ]; then
        state="failed"
        detail="last Tier 2 run (\`$run_id\`) FAILED, $((age / 3600))h ago."
    fi
fi

# ── Stack-drift check (only when otherwise healthy — dead/failed outranks) ───
# The runner's module stack must track the fleet (tier2-runner-architecture);
# this makes drift loud instead of checklist-enforced. Deliberate leads (runner
# ahead of fleet as a pre-activation gate) alert once and self-recover after
# the fleet activates. Checker exit 2 = couldn't check (transient SSH etc.) —
# log only, never flap the state.
DRIFT_CHECKER="${KTP_TIER2_DRIFT_CHECKER:-/usr/local/bin/ktp-tier2-stack-drift.py}"
AGG_ENV="${KTP_AGGREGATOR_ENV:-/opt/ktp-profile-aggregator/.env}"
AGG_PY="${KTP_AGGREGATOR_PY:-/opt/ktp-profile-aggregator/venv/bin/python}"
if [ "$state" = "ok" ] && [ -x "$AGG_PY" ] && [ -f "$DRIFT_CHECKER" ]; then
    drift_out="$(set -a; . "$AGG_ENV" 2>/dev/null; set +a; "$AGG_PY" "$DRIFT_CHECKER" 2>&1)" && drift_rc=0 || drift_rc=$?
    if [ "$drift_rc" -eq 1 ]; then
        state="drift"
        detail="$drift_out — re-sync the runner stack from the fleet (or dismiss if the runner is deliberately leading a staged wave)."
    elif [ "$drift_rc" -ge 2 ]; then
        echo "tier2-heartbeat: drift check inconclusive (rc=$drift_rc): $drift_out"
    fi
fi

prev="$(cat "$STATE" 2>/dev/null || echo "")"
echo "$state" > "$STATE" 2>/dev/null || true

if [ "$state" = "$prev" ]; then
    echo "tier2-heartbeat: state=$state (unchanged) — no alert"
    exit 0
fi

# ── Build + post the transition embed ────────────────────────────────────────
case "$state" in
    ok)     title="✅ KTP Tier 2 — recovered"; desc="Tier 2 integration suite healthy (running + stack in sync)."; color=5763719 ;;
    failed) title="❌ KTP Tier 2 — last run failed"; desc="$detail"; color=15548997 ;;
    drift)  title="⚠️ KTP Tier 2 — runner stack drifted from fleet"; desc="$detail"; color=16763904 ;;
    *)      title="⚠️ KTP Tier 2 — not running"; desc="$detail"; color=16763904 ;;
esac
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
echo "tier2-heartbeat: state $prev -> $state, relay HTTP $http"
