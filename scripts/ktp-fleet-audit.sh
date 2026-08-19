#!/bin/bash
# KTP Fleet Drift Audit — weekly cron wrapper.
#
# Sources /etc/ktp/audit.env (Discord config) and invokes audit-fleet-drift.py
# against the full fleet. Writes markdown report to /var/log/ktp-audit-*.md,
# persists state to /var/lib/ktp-audit-state.json, posts NEW drift items to
# Discord via --alert-discord.
#
# Schedule: /etc/cron.d/ktp-fleet-audit runs this Monday 05:00 ET.
# Run manually for ad-hoc audits: /usr/local/bin/ktp-fleet-audit.sh

set -euo pipefail

INFRA_ROOT=/opt/ktp-infra
STATE_FILE=/var/lib/ktp-audit-state.json
REPORT="/var/log/ktp-audit-$(date +%Y%m%d-%H%M).md"

# Refuse to run unless INFRA_ROOT is a git checkout. A plain directory works fine
# and silently freezes the baselines -- that shape ran for four months reporting
# binary: 30 every week against April pins, and sysctl: 0 because the baseline
# predated the check. A stale baseline does not fail; it stops meaning anything.
if ! git -C "$INFRA_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    echo "FATAL: $INFRA_ROOT is not a git checkout." >&2
    echo "       The audit would compare the fleet against whatever baselines happen" >&2
    echo "       to be sitting there. Refusing rather than reporting fiction." >&2
    exit 3
fi

# Report staleness; never pull. A weekly root cron that self-updates would execute
# whatever last landed on main, with SSH to all five game hosts.
git -C "$INFRA_ROOT" fetch --quiet origin 2>/dev/null     || echo "WARN: could not fetch origin; the staleness below may itself be stale." >&2
INFRA_HEAD="$(git -C "$INFRA_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
INFRA_BEHIND="$(git -C "$INFRA_ROOT" rev-list --count HEAD..origin/main 2>/dev/null || echo '?')"
INFRA_DIRTY="$(git -C "$INFRA_ROOT" status --porcelain 2>/dev/null | grep -c . || true)"
echo "Baselines: $INFRA_HEAD, $INFRA_BEHIND behind origin/main, $INFRA_DIRTY local modification(s)"
[ "$INFRA_BEHIND" != "0" ] && echo "NOTE: baselines are behind origin/main -- drift may be stale, not real." >&2
[ "$INFRA_DIRTY" != "0" ] && echo "WARN: $INFRA_ROOT has local modifications; baselines are not what main says." >&2

# Discord config (reuses relay URL/secret from discord-relay.conf)
[ -f /etc/ktp/audit.env ] && source /etc/ktp/audit.env
export KTP_RELAY_URL KTP_RELAY_SECRET KTP_ALERT_CHANNEL

cd "$INFRA_ROOT"
# The audit exits 2 when it finds drift -- its normal reportable outcome. Under
# `set -e` that aborted the wrapper before the final line, which is why that line
# has never once run. Distinguish "found drift" from "the audit itself broke".
set +e
python3 scripts/audit-fleet-drift.py     --out "$REPORT"     --state "$STATE_FILE"     --alert-discord
AUDIT_RC=$?
set -e

case "$AUDIT_RC" in
    0) echo "Audit clean. Report: $REPORT" ;;
    2) echo "Audit found drift. Report: $REPORT" ;;
    *) echo "FATAL: audit exited $AUDIT_RC -- the audit failed, this is not drift." >&2
       exit "$AUDIT_RC" ;;
esac
exit "$AUDIT_RC"
