#!/bin/bash
# KTP backup watchdog.
#
# WHY THIS EXISTS. /opt/ktp-backup.sh guards everything about the dump it takes --
# it gates the retention prune on a verified-good dump, rejects a suspiciously small
# file, and keeps the password out of `ps`. None of that guards a run that never
# happens: cron firing nothing produces no output, so a silence and a success were
# indistinguishable. A scheduled run went missing on 2026-08-16 and nothing noticed
# until the archive was measured by hand five days later.
#
# It also checks that EVERY database landed, not just that something did. The old
# script named one database out of three, exited 0, and logged "Backup complete" --
# so "a backup ran" was never evidence that a given database was in it.

set -uo pipefail

HEARTBEAT="/var/lib/ktp-backup-lastrun"
BACKUP_DIR="/opt/backups"
CONF="/etc/ktp/discord-relay.conf"
MAX_AGE_HOURS=192          # weekly schedule + 24h grace
DATABASES="hlstatsx hlstatsx_lan ktp_lan"

problems=()

# --- 1. did the job run at all? ---
if [ ! -f "$HEARTBEAT" ]; then
    problems+=("Heartbeat file is missing entirely -- the backup has not completed successfully since the watchdog was installed.")
else
    age_h=$(( ( $(date +%s) - $(stat -c %Y "$HEARTBEAT") ) / 3600 ))
    if [ "$age_h" -gt "$MAX_AGE_HOURS" ]; then
        problems+=("Last successful backup was ${age_h}h ago (limit ${MAX_AGE_HOURS}h). Expected weekly, Sundays 03:00.")
    fi
fi

# --- 2. does every database have a recent dump? ---
# Checked per database, because a partial run is the failure that reads as success.
# ${db}_[0-9]* NOT ${db}_*: the dump names are <db>_<YYYYMMDD>_<HHMMSS>, and
# `hlstatsx_*` also matches `hlstatsx_lan_*`. With `ls -t | head -1` that
# silently returned the LAN dump when checking hlstatsx -- so the check passed
# on a file belonging to a different database. The date anchor is what makes
# the prefix unambiguous.
for db in $DATABASES; do
    newest=$(ls -t "$BACKUP_DIR"/${db}_[0-9]*.sql.gz 2>/dev/null | head -1)
    if [ -z "$newest" ]; then
        problems+=("No dump of any age exists for \`${db}\`.")
        continue
    fi
    d_age_h=$(( ( $(date +%s) - $(stat -c %Y "$newest") ) / 3600 ))
    if [ "$d_age_h" -gt "$MAX_AGE_HOURS" ]; then
        problems+=("Newest \`${db}\` dump is ${d_age_h}h old ($(basename "$newest")).")
    fi
    # A dump that exists but is a stub passes every -f/-s test.
    sz=$(stat -c %s "$newest")
    if [ "$sz" -lt 1024 ]; then
        problems+=("Newest \`${db}\` dump is only ${sz} bytes -- almost certainly empty.")
    fi
done

# --- 3. did the offsite copy actually land? ---
# This replaced a standing note that said nothing leaves the host. That stopped
# being true on 2026-08-22, and a note describing a fixed gap is worse than no
# note: it reads as a known limitation rather than a stale line.
#
# Checked by ASKING THE FAR SIDE for the newest dump by name. A local success
# says the dump exists here; only the remote answers whether it exists there.
OFFSITE_CONF="/etc/ktp/offsite.conf"
if [ ! -f "$OFFSITE_CONF" ]; then
    problems+=("Offsite config \`$OFFSITE_CONF\` is missing -- nothing is being shipped off this host.")
else
    # shellcheck source=/dev/null
    . "$OFFSITE_CONF"
    for H in ${KTP_OFFSITE_HOSTS:-}; do
        if ! ssh -o BatchMode=yes -o ConnectTimeout=8 "$H" true 2>/dev/null; then
            # Unreachable is its own finding. A target we cannot reach is not a
            # target that has the data -- do not let it read as "no news".
            problems+=("Offsite target \`${H##*@}\` is UNREACHABLE -- cannot confirm anything is there.")
            continue
        fi
        for db in $DATABASES; do
            newest=$(ls -t "$BACKUP_DIR"/${db}_[0-9]*.sql.gz 2>/dev/null | head -1)
            [ -n "$newest" ] || continue   # already reported by check 2
            base=$(basename "$newest")
            if ! ssh -o BatchMode=yes -o ConnectTimeout=8 "$H"                  "[ -f '${KTP_OFFSITE_DB_DIR:-/nonexistent}/$base' ]" 2>/dev/null; then
                problems+=("Newest \`${db}\` dump (\`$base\`) is NOT on \`${H##*@}\`.")
            fi
        done
    done
fi

if [ ${#problems[@]} -eq 0 ]; then
    echo "$(date -Is) backup watchdog: OK (all ${DATABASES// /, } current)"
    exit 0
fi

echo "$(date -Is) backup watchdog: ${#problems[@]} PROBLEM(S)"
for p in "${problems[@]}"; do echo "  - $p"; done

# --- alert ---
if [ ! -f "$CONF" ]; then
    echo "  (cannot alert: $CONF missing)"
    exit 1
fi
# shellcheck disable=SC1090
source "$CONF"

CHANNEL="${PERF_ALERT_CHANNEL:-}"
if [ -z "$CHANNEL" ] || [ -z "${RELAY_URL:-}" ] || [ -z "${AUTH_SECRET:-}" ]; then
    echo "  (cannot alert: relay URL, secret or channel unset)"
    exit 1
fi

desc=""
for p in "${problems[@]}"; do desc="${desc}- ${p}\\n"; done

payload=$(cat <<EOF
{
  "channelId": "$CHANNEL",
  "embeds": [{
    "title": "Backup watchdog: ${#problems[@]} problem(s)",
    "description": "$desc",
    "color": 16711680,
    "footer": { "text": "neindataatl - $(date -u +%Y-%m-%dT%H:%M:%SZ)" }
  }]
}
EOF
)

curl -s -X POST "$RELAY_URL" \
    -H "X-Relay-Auth: $AUTH_SECRET" \
    -H "Content-Type: application/json" \
    -d "$payload" >/dev/null
echo "  (alert sent)"
exit 1
