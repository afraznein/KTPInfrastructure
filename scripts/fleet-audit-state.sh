#!/bin/bash
# Two-phase state for fleet-audit.yml: the delta is spent only once it was reported.
#
# WHY
# Every check in the collect job keeps a "since last run" baseline, and each one
# wrote that baseline the moment it ran. So a run whose triage or Discord notice
# failed had already consumed its delta: the next Monday compared against the
# state the failed run left behind and reported nothing. A finding nobody was
# told about became steady state.
#
# HOW
#   seed <run_id>     copy each committed state file into a per-run candidate
#                     directory and record what it was copied from. The collect
#                     steps then read and write the CANDIDATES only.
#   promote <run_id>  copy the candidates over the committed files. The
#                     workflow runs this as its last job, and only when the
#                     reporting it depends on succeeded.
#   dir <run_id>      print the candidate directory.
#
# Promotion is idempotent, so re-running a failed notify and then promote is
# safe. It refuses -- and writes nothing -- when a committed file has moved
# since this run seeded it, because that means a newer run already promoted and
# this one would roll its baseline back.
#
# Env:  KTP_AUDIT_STATE_DIR    committed state (default /var/lib)
#       KTP_AUDIT_PENDING_DIR  candidate root (default <state dir>/ktp-fleet-audit-ci-pending)
# Exit: 0 ok, 1 refused or failed, 64 usage.

set -euo pipefail

STATE_FILES=(
    ktp-audit-state-ci.json
    ktp-distribute-drift-ci.json
    ktp-restart-drift-ci.txt
    ktp-distribute-drift-ci.txt
)

state_dir="${KTP_AUDIT_STATE_DIR:-/var/lib}"
pending_root="${KTP_AUDIT_PENDING_DIR:-$state_dir/ktp-fleet-audit-ci-pending}"

usage() {
    echo "usage: $0 seed|promote|dir <run_id>" >&2
    exit 64
}

[ $# -eq 2 ] || usage
cmd="$1"
run_id="$2"
# The run id becomes a path that `seed` empties, so it must be a plain number.
case "$run_id" in
    ''|*[!0-9]*) echo "run_id must be numeric, got '$run_id'" >&2; exit 64 ;;
esac
pending="$pending_root/$run_id"

fingerprint() {
    if [ -f "$1" ]; then
        sha256sum "$1" | cut -d' ' -f1
    else
        echo ABSENT
    fi
}

seed() {
    rm -rf -- "$pending"
    mkdir -p -- "$pending"
    : > "$pending/BASE.tmp"
    for f in "${STATE_FILES[@]}"; do
        if [ -f "$state_dir/$f" ]; then
            cp -p -- "$state_dir/$f" "$pending/$f"
        fi
        printf '%s %s\n' "$f" "$(fingerprint "$state_dir/$f")" >> "$pending/BASE.tmp"
    done
    mv -f -- "$pending/BASE.tmp" "$pending/BASE"
    echo "Seeded $pending from $state_dir"
}

promote() {
    if [ ! -f "$pending/BASE" ]; then
        echo "REFUSED: $pending/BASE missing -- this run was never seeded." >&2
        exit 1
    fi
    local todo=() f base cur cand refused=0
    for f in "${STATE_FILES[@]}"; do
        base="$(awk -v f="$f" '$1 == f { print $2 }' "$pending/BASE")"
        if [ -z "$base" ]; then
            echo "REFUSED: $f has no recorded base in $pending/BASE." >&2
            refused=1
            continue
        fi
        cur="$(fingerprint "$state_dir/$f")"
        cand="$(fingerprint "$pending/$f")"
        if [ "$cand" = ABSENT ] || [ "$cand" = "$cur" ]; then
            echo "  $f: unchanged or already promoted"
        elif [ "$cur" = "$base" ]; then
            todo+=("$f")
        else
            echo "REFUSED: $state_dir/$f changed since run $run_id seeded it; a newer run promoted first." >&2
            refused=1
        fi
    done
    # All or nothing: a half-promoted set would pair one check's new baseline
    # with another's old one.
    if [ "$refused" -ne 0 ]; then
        exit 1
    fi
    for f in "${todo[@]+"${todo[@]}"}"; do
        cp -p -- "$pending/$f" "$state_dir/$f.promote.$$"
        mv -f -- "$state_dir/$f.promote.$$" "$state_dir/$f"
        echo "  $f: promoted"
    done
    echo "Promoted run $run_id"
}

case "$cmd" in
    seed) seed ;;
    promote) promote ;;
    dir) echo "$pending" ;;
    *) usage ;;
esac
