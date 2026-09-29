#!/bin/bash
# Ask, on a schedule, whether what is installed on this host is what the repo
# holds -- `ktp-install --report --repo DIR --against-ref REF` -- and post only
# when the answer CHANGES.
#
# ⛔ NOT INSTALLED OR ENABLED. This file and its unit pair are a proposal; see
# docs/runbooks/INSTALL_FRESHNESS.md for what turning it on costs and requires.
#
# Two failures in this estate decided the shape, and both invert the obvious
# design:
#
#   1. A hung unit reads as `active`. hltv-demo-renamer sat "healthy" for 53h
#      with every demo in the window lost. So the alert is keyed on a durable
#      artifact this script writes -- $RESULT_FILE and its mtime -- and never on
#      the unit being up. If the run cannot produce that file, it produced
#      nothing, whatever systemd says.
#   2. A standing non-zero count re-fires forever and trains everyone past it.
#      10 paths are in DRIFT on the data server today and will be tomorrow. So
#      the alert is a SET TRANSITION: what entered the non-fresh set, what left
#      it. An unchanged set is silent no matter how large it is.
#
# And one inversion worth stating because it looks like a bug: a dirty estate
# exits 0. `ktp-install --report` exits 1 when anything is stale, and letting
# that fail the unit would fire the OnFailure alert on every single run. Unit
# failure here means the CHECK could not run; the estate's state is carried by
# the transition post and by $RESULT_FILE, not by the exit code.
#
# Exit: 0 the check ran (clean or not), 1 it could not run, 2 misconfigured.

set -Eeuo pipefail

CONF="${KTP_INSTALL_FRESHNESS_CONF:-/etc/ktp/install-freshness.conf}"
[ -r "$CONF" ] && . "$CONF"

STATE_DIR="${STATE_DIR:-/var/lib/ktp-install-freshness}"
RESULT_FILE="${RESULT_FILE:-$STATE_DIR/last-run.json}"
REPORT_FILE="${REPORT_FILE:-$STATE_DIR/last-report.txt}"
STATE_FILE="${STATE_FILE:-$STATE_DIR/non-fresh.txt}"
KTP_INSTALL="${KTP_INSTALL:-/usr/local/bin/ktp-install}"
AGAINST_REF="${AGAINST_REF:-origin/main}"
# A read-only mirror this script owns and fetches. Deliberately NOT a deploy
# checkout: /opt/ktp-infra must not be auto-pulled, and a freshness check that
# moves the tree someone installs from would be changing the thing it measures.
FRESHNESS_REPO="${FRESHNESS_REPO:-$STATE_DIR/mirror.git}"
# Daily timer. Two intervals of slack before a gap counts as "did not run",
# so an ordinary RandomizedDelaySec skew is not news and a missed day is.
MAX_GAP_SEC="${MAX_GAP_SEC:-172800}"
# No channel id in a public repo. The lane mapping supplies it; an unmapped
# lane with no ALERT_CHANNEL set in the conf is a hard error, never a guess.
ALERT_CHANNEL="${ALERT_CHANNEL:-}"

[ -f /etc/ktp/discord-relay.conf ] && . /etc/ktp/discord-relay.conf

ts() { date '+%Y-%m-%d %H:%M:%S'; }
die() { echo "[$(ts)] FATAL: $*" >&2; exit "${2:-1}"; }

case "$FRESHNESS_REPO" in
    /opt/ktp-infra|/opt/ktp-infra/*)
        die "FRESHNESS_REPO is the deploy checkout; this script fetches, and that tree must not be auto-pulled" 2 ;;
esac
[ -x "$KTP_INSTALL" ] || die "$KTP_INSTALL is not executable" 2
grep -q -- '--against-ref' "$KTP_INSTALL" \
    || die "$KTP_INSTALL predates --against-ref; install it before enabling this check" 2

_routing="$(dirname "${BASH_SOURCE[0]}")/ktp-alert-routing.sh"
[ -r "$_routing" ] || _routing=/usr/local/bin/ktp-alert-routing.sh
# FATAL, not a fallback. Unlike ktp-data-server-health.sh this is not the check
# that watches everything else, so a deploy-order slip should stop it rather
# than invent colours and a channel.
[ -r "$_routing" ] || die "alert routing helper not found; not guessing a channel" 2
# shellcheck source=scripts/ktp-alert-routing.sh
. "$_routing"

mkdir -p "$STATE_DIR" || die "cannot create $STATE_DIR"

# ── keep the mirror current ────────────────────────────────────────────────
if [ ! -d "$FRESHNESS_REPO" ]; then
    die "$FRESHNESS_REPO does not exist; create it once with 'git clone --bare' (see the runbook)"
fi
# The configured refspec, not one spelled here: the runbook sets the mirror up
# with +refs/heads/*:refs/remotes/origin/*, so origin/main means the same thing
# here as it does in a working checkout. A --mirror clone maps branches into
# refs/heads instead, where origin/main does not resolve at all.
git -C "$FRESHNESS_REPO" fetch --quiet --prune origin \
    || die "fetch failed; a freshness check that could not update its mirror must not report freshness"
head_sha="$(git -C "$FRESHNESS_REPO" rev-parse --verify "$AGAINST_REF^{commit}")" \
    || die "$AGAINST_REF does not resolve in $FRESHNESS_REPO"

# ── run the report ─────────────────────────────────────────────────────────
# Its own status, not a pipeline's. `cmd | tee` reports tee's exit and every
# drift would read as a clean 0.
set +e
"$KTP_INSTALL" --report --repo "$FRESHNESS_REPO" --against-ref "$AGAINST_REF" > "$REPORT_FILE.partial" 2>&1
report_rc=$?
set -e
if [ "$report_rc" -eq 2 ]; then
    # UNTRUSTED: no manifest, an unreadable one, a ref that will not resolve.
    # A check that could not run must fail the unit, not write a result.
    cat "$REPORT_FILE.partial" >&2
    rm -f "$REPORT_FILE.partial"
    die "report exited 2 (untrusted); no result written"
fi
mv "$REPORT_FILE.partial" "$REPORT_FILE"

# ── the non-fresh set, one "STATE<TAB>path" line each, sorted ──────────────
awk '$1 != "OK" && $1 != "TEMPLATED" && $1 != "CURRENT" && $1 != "OTHER-REPO" \
     { print $1 "\t" $2 }' "$REPORT_FILE" | sort > "$STATE_DIR/non-fresh.new"

previous_exists=0
[ -f "$STATE_FILE" ] && previous_exists=1
[ "$previous_exists" -eq 1 ] || : > "$STATE_FILE"

entered="$(comm -13 "$STATE_FILE" "$STATE_DIR/non-fresh.new")"
left="$(comm -23 "$STATE_FILE" "$STATE_DIR/non-fresh.new")"
n_now="$(wc -l < "$STATE_DIR/non-fresh.new" | tr -d ' ')"

# ── did it run? the leg a process-state check cannot answer ────────────────
gap_note=""
if [ -f "$RESULT_FILE" ]; then
    last_epoch="$(sed -n 's/.*"epoch":[[:space:]]*\([0-9]*\).*/\1/p' "$RESULT_FILE" | head -1)"
    if [ -n "$last_epoch" ]; then
        gap=$(( $(date +%s) - last_epoch ))
        if [ "$gap" -gt "$MAX_GAP_SEC" ]; then
            gap_note="did not run for $(( gap / 3600 ))h before this run"
        fi
    fi
fi

# ── write the durable artifact BEFORE deciding to post ─────────────────────
# The result is the record; a relay outage must not cost us the evidence that
# the check ran. The transition state file is saved only after a post lands,
# so a failed post re-announces rather than swallowing the change.
tally="$(awk '{print $1}' "$REPORT_FILE" | sort | uniq -c | awk '{printf "%s\"%s\":%s", (NR>1?",":""), $2, $1}')"
cat > "$RESULT_FILE.partial" <<EOF
{"iso":"$(date -Is)","epoch":$(date +%s),"ref":"$AGAINST_REF","ref_commit":"$head_sha",
 "report_exit":$report_rc,"non_fresh":$n_now,"entered":$(printf '%s' "$entered" | grep -c . || true),
 "left":$(printf '%s' "$left" | grep -c . || true),"tally":{$tally}}
EOF
mv "$RESULT_FILE.partial" "$RESULT_FILE"

if [ -z "$entered" ] && [ -z "$left" ] && [ -z "$gap_note" ]; then
    echo "[$(ts)] no change: $n_now non-fresh, ref $AGAINST_REF@${head_sha:0:12}; silent"
    cp "$STATE_DIR/non-fresh.new" "$STATE_FILE"
    exit 0
fi
if [ "$previous_exists" -eq 0 ] && [ -z "$gap_note" ]; then
    # First run has nothing to have changed from. Recording the baseline and
    # saying nothing is right; announcing every path once would be the standing
    # count this check exists to avoid.
    echo "[$(ts)] first run: baseline of $n_now non-fresh recorded; silent"
    cp "$STATE_DIR/non-fresh.new" "$STATE_FILE"
    exit 0
fi

# ── build and post the transition ──────────────────────────────────────────
desc=""
if [ -n "$gap_note" ]; then
    desc+="⏱️ **$gap_note**"$'\n\n'
fi
if [ -n "$entered" ]; then
    desc+='⚠️ **No longer matches '"$AGAINST_REF"':**'$'\n'
    while IFS=$'\t' read -r state path; do
        desc+="• \`${path}\` — ${state}"$'\n'
    done <<< "$entered"
fi
if [ -n "$left" ]; then
    [ -n "$desc" ] && desc+=$'\n'
    desc+='✅ **Reconciled:**'$'\n'
    while IFS=$'\t' read -r state path; do
        desc+="• \`${path}\` — was ${state}"$'\n'
    done <<< "$left"
fi
desc+=$'\n''_'"$n_now"' non-fresh in all, against '"$AGAINST_REF"'@'"${head_sha:0:12}"'_'

# A path that fell out of step is "look today", not "wake someone": nothing is
# down, and the file has been wrong for however long it took to notice.
if [ -n "$entered" ] || [ -n "$gap_note" ]; then severity=warn; else severity=recovery; fi
ktp_alert_route "$severity" || die "unknown severity $severity" 2
# A recovery defaults to the page lane, where this producer never posts.
[ "$severity" = recovery ] && KTP_ALERT_LANE="$KTP_LANE_OPS_DAILY"
ktp_alert_channel "$KTP_ALERT_LANE" "$ALERT_CHANNEL" \
    || die "no channel for lane $KTP_ALERT_LANE; map it in /etc/ktp/discord-relay.conf" 2

payload="$(jq -n \
    --arg ch "$KTP_ALERT_CHANNEL" \
    --arg title "${KTP_ALERT_GLYPH} KTP install freshness — $(hostname -s)" \
    --arg desc "$desc" \
    --arg footer "ktp-install-freshness @ $(TZ=America/New_York date '+%Y-%m-%d %H:%M %Z')" \
    --argjson color "$KTP_ALERT_COLOR" \
    '{channelId:$ch, embeds:[{title:$title, description:$desc, color:$color, footer:{text:$footer}}]}')"

http="$(curl -sS -o /tmp/ktp-install-freshness-resp.txt -w '%{http_code}' \
    -X POST "${RELAY_URL:-}" \
    -H "X-Relay-Auth: ${AUTH_SECRET:-}" \
    -H 'Content-Type: application/json' \
    -d "$payload" 2>&1 || echo 000)"
if [ "$http" != "200" ] && [ "$http" != "204" ]; then
    echo "[$(ts)] WARN: relay returned HTTP $http" >&2
    echo "[$(ts)] transition NOT saved — it will be re-announced on the next run" >&2
    exit 0
fi
cp "$STATE_DIR/non-fresh.new" "$STATE_FILE"
echo "[$(ts)] posted (HTTP $http) severity=$severity lane=$KTP_ALERT_LANE via=$KTP_ALERT_CHANNEL_SOURCE" \
     "entered=$(printf '%s' "$entered" | grep -c . || true) left=$(printf '%s' "$left" | grep -c . || true) total=$n_now"
