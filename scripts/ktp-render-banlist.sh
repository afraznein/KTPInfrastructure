#!/bin/bash
# Render the central ban list and hand it to the file distributor.
#
# Source of truth is the AC API. This only transports.
#
# /home/dod/distribute IS A LIVE DEPLOY PATH -- the watcher pushes anything that
# appears there to all 24 instances within ~15s, including files you did not mean to
# leave behind (a sed backup and sed's own temp file were both replicated fleet-wide
# on 2026-08-06). So: build and validate entirely OUTSIDE the tree, and put exactly
# one finished file in, atomically.
set -uo pipefail

API="http://127.0.0.1:8088/api/admin/bans/distribution"
SETTINGS="/opt/ktp-ac-api/appsettings.json"
DEST="/home/dod/distribute/addons/ktpamx/configs/ktp_ac_bans.ini"
WORK="$(mktemp -d /tmp/ktp-banlist.XXXXXX)" || exit 1
trap 'rm -rf "$WORK"' EXIT
TMP="$WORK/list.ini"
LOG="/var/log/ktp-banlist.log"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG"; }

KEY="$(python3 -c "import json;print(json.load(open('$SETTINGS'))['AdminApiKey'])" 2>/dev/null)"
if [ -z "$KEY" ]; then
    log "ABORT: could not read AdminApiKey"
    exit 1
fi

HTTP=$(curl -s -m 15 -o "$TMP" -w '%{http_code}' -H "X-Admin-Key: $KEY" "$API")
if [ "$HTTP" != "200" ]; then
    log "ABORT: API returned HTTP $HTTP -- keeping the previously distributed list"
    exit 1
fi

# VALIDATE BEFORE PUBLISHING. The consumer already refuses a file whose terminator is
# missing or disagrees with the row count, but a truncated list must not be allowed to
# reach 24 instances in the first place: defence in depth, and it keeps the plugin's
# rejection path a genuine last resort rather than the normal case.
END_LINE=$(grep -m1 '^; END rows=' "$TMP")
if [ -z "$END_LINE" ]; then
    log "ABORT: rendered list has no terminator (truncated fetch?) -- not publishing"
    exit 1
fi
DECLARED=$(printf '%s' "$END_LINE" | sed -n 's/^; END rows=\([0-9]*\).*/\1/p')
ACTUAL=$(grep -c '^STEAM_' "$TMP")
if [ "$DECLARED" != "$ACTUAL" ]; then
    log "ABORT: terminator says $DECLARED rows, file has $ACTUAL -- not publishing"
    exit 1
fi

# Only publish on change. The watcher fires on every write, so an unconditional copy
# would push an identical file to 24 instances every single run.
#
# The comparison MASKS rendered_utc: the API stamps it with sub-second precision, so
# every render differs and an unmasked cmp could never match -- the guard was dead and
# published on all ~1440 runs a day. Do NOT "compare on generation" instead: a ban
# aging past expires_at changes the rendered rows while moving neither generation nor
# the revoked count, so that would suppress a real change.
if [ -f "$DEST" ] && cmp -s \
        <(sed 's/ rendered_utc=[^ ]*//' "$TMP") \
        <(sed 's/ rendered_utc=[^ ]*//' "$DEST"); then
    exit 0
fi

GEN=$(sed -n 's/.*generation=\([0-9]*\).*/\1/p' "$TMP" | head -1)
# ONE rename, straight from the work dir into the tree. Do NOT stage inside the tree:
# the watcher fires on anything that appears there, so a two-step copy-then-rename
# distributes the temp file to all 24 instances as well -- observed doing exactly that
# on the first run of this script ("2 file(s) [.ktp_ac_bans.ini.staging, ...]").
# /tmp and /home are the same filesystem here, so this mv is a single atomic rename
# and produces exactly one event.
chmod 0644 "$TMP"
if ! mv -f "$TMP" "$DEST"; then
    log "ABORT: could not publish into the distribute tree"
    exit 1
fi
log "PUBLISHED generation=$GEN rows=$ACTUAL -> $DEST"
