#!/bin/bash
# Decide whether this week's fleet audit needs a human -- or the model that
# writes for one. Run by fleet-audit.yml after the collect steps; reads their
# three output files from the working directory and prints GITHUB_OUTPUT lines.
#
# WHY THIS IS A FILE AND NOT A run: BLOCK
# The gate is the thing that keeps the audit from becoming wallpaper. It was a
# 40-line bash block inside YAML, which nothing could test, and its third leg
# was wrong in a way a test would have caught: it treated ktp-restart-drift.py's
# nonzero exit as news. That script reports DIVERGES for as long as the tracked
# .example runs ahead of the fleet -- which is the normal state between a merge
# and a redeploy, and was true on every run. So needs_triage was always true,
# every Monday woke the model, and every triage said "known, no action". That
# is the exact failure ALERT_COVERAGE.md records five times.
#
# WHAT COUNTS AS NEWS
#   1. Repo-vs-fleet drift NEW since last run, per the audit's own delta line.
#   2. A LinuxGSM monitor patch fault, on any run -- this has cost a match
#      window before and does not depend on state.
#   3. A CHANGE in what the restart-drift check reports: a new divergence, a
#      host that dropped off, or a resolution. Not the level -- the change.
#      This is how ktp-data-server-health.sh already treats persistent-down,
#      and it is the estate's settled answer to repeat alerts.
#   4. The restart-drift check failing to complete at all. That is a broken
#      instrument, not drift, and it is always news.
#   5. A data-server health item open longer than KTP_GATE_LONG_OPEN_DAYS
#      (default 3). The hourly check pages once when an item appears and never
#      again while it persists -- that is correct for a channel and wrong for
#      a week: ktp-identity-reconcile.service sat failed for ten days after its
#      one post. Age, not presence, is the signal, and it nags weekly by design:
#      the triage comments on the one open issue until someone closes it.
#   6. The health check itself not having written for KTP_GATE_HEALTH_STALE_H
#      (default 6) hours. Nothing else watches the watcher.
#
# Inputs (cwd):  audit-stdout.txt  audit-report.md  restart-drift.txt  health-state.json
# State:         $KTP_GATE_STATE_DIR/ktp-restart-drift-ci.txt (default /var/lib)
# Output:        needs_triage=true|false and reason=... on stdout, one per line,
#                in GITHUB_OUTPUT form. Exit 0 always; a gate that crashes
#                would skip triage silently, which is the worst outcome here.

set -uo pipefail

state_dir="${KTP_GATE_STATE_DIR:-/var/lib}"
prev="$state_dir/ktp-restart-drift-ci.txt"
reasons=""

# 1. New repo drift. The audit prints no delta on its very first run against a
#    fresh state file, so this leg is quiet then by construction -- the
#    alternative is triaging every long-standing item at once on run one.
new_count="$(sed -n 's/.*Repo-drift delta vs last run: +\([0-9]\+\) new.*/\1/p' audit-stdout.txt 2>/dev/null | head -1)"
new_count="${new_count:-0}"
if [ "$new_count" -gt 0 ]; then
    reasons="${reasons}${new_count} new repo-drift item(s). "
fi

# 2. Monitor patch. These three states are the ones that kill live servers or
#    leave a monitor that parses nothing and restarts nothing, silently.
if grep -qE 'parse=BROKEN|parse=MISSING|oldtype=armed' audit-report.md 2>/dev/null; then
    reasons="${reasons}LinuxGSM monitor patch fault. "
fi

# 3 and 4. Restart-drift, as a transition. Reduce the report to its stable
#    lines: DRIFT findings verbatim, UNREACHABLE trimmed to host and exception
#    class -- the redacted detail after it can differ between two identical
#    outages and must not read as a change.
if ! grep -q '^hosts reached:' restart-drift.txt 2>/dev/null; then
    reasons="${reasons}Restart-drift check did not complete. "
else
    cur="$(grep -E 'DRIFT:|UNREACHABLE' restart-drift.txt \
           | sed -E 's/(UNREACHABLE \([^)]*\)).*/\1/' | sort || true)"
    if [ -f "$prev" ]; then
        if [ "$cur" != "$(cat "$prev")" ]; then
            reasons="${reasons}Restart-script drift changed since last run. "
        fi
    fi
    # Save the baseline whether or not it changed. The write can fail on a
    # read-only checkout (tests, a dry local run); that must not fail the gate.
    printf '%s\n' "$cur" > "$prev" 2>/dev/null || true
fi

# 5 and 6. Long-open health items, and a health check that stopped writing.
#    python3 rather than jq: the runner and every test host have it, and the
#    audit this gate serves is python3 already.
# The first interpreter that actually runs: a Windows workstation's `python3`
# can be a Store stub that prints an install hint and exits 9009, and `|| true`
# below would read that as "nothing to say".
py=python3
for cand in python3 python; do
    if "$cand" -c pass >/dev/null 2>&1; then py=$cand; break; fi
done
health_reason="$("$py" - "${KTP_GATE_LONG_OPEN_DAYS:-3}" "${KTP_GATE_HEALTH_STALE_H:-6}" <<'PY' 2>/dev/null || true
import json, sys, time
from datetime import datetime
days, stale_h = float(sys.argv[1]), float(sys.argv[2])
try:
    doc = json.load(open("health-state.json", encoding="utf-8"))
except Exception:
    sys.exit(0)                      # absent or unreadable: nothing to say
fmt = "%Y-%m-%d %H:%M:%S"
now = time.time()
try:
    updated = datetime.strptime(doc.get("updated_at", ""), fmt).timestamp()
except ValueError:
    sys.exit(0)
if now - updated > stale_h * 3600:
    print("Health check has not written for %dh. " % ((now - updated) // 3600))
    sys.exit(0)
old = []
for key, since in (doc.get("since") or {}).items():
    try:
        age = (now - datetime.strptime(since, fmt).timestamp()) / 86400
    except (TypeError, ValueError):
        continue
    if age >= days:
        old.append("%s (%dd)" % (key, age))
if old:
    print("%d health item(s) open over %gd: %s. " % (len(old), days, ", ".join(sorted(old))))
PY
)"
if [ -n "$health_reason" ]; then
    reasons="${reasons}${health_reason}"
fi

if [ -n "$reasons" ]; then
    echo "needs_triage=true"
else
    echo "needs_triage=false"
    reasons="Nothing new."
fi
echo "reason=$reasons"
