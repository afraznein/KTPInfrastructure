#!/bin/bash
# Publish newly recorded demos: file them, then rebuild the archive pages.
#
# Both halves, in this order, or it does nothing useful: the organizer moves
# demos out of the recording root into demos/<SERVER>/<TYPE>/, and the index
# generator only ever describes what is already filed. Running just the second
# rebuilds the same pages.
#
# Before this existed both ran once a day (04:00 and 04:45), so a demo that
# finished at 21:00 was invisible until the next morning -- and on 2026-08-06
# the organizer silently stopped filing anything, which nobody saw for five
# days because the only signal was in a once-daily log.
set -u

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] publish: $*"; }

log "start"

if ! /usr/local/bin/ktp-organize-hltv-demos.sh; then
    log "ERROR: organizer exited non-zero; rebuilding pages anyway so the site is not left stale"
fi

# --apply is not optional. Without it the generator prints a full, plausible
# list of pages, says "DRY RUN - nothing written", and exits 0 -- a silent no-op
# that reads exactly like success.
if /usr/bin/python3 /usr/local/bin/ktp-fastdl-indexes.py --apply; then
    log "done"
else
    log "ERROR: index generation failed"
    exit 1
fi
