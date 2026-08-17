#!/usr/bin/env bash
# Assemble a runnable hlstats.pl tree for Lane B.
#
# ## Why this exists
#
# KTPHLStatsX is a delta-only fork. It tracks exactly three files —
# `hlstats.pl`, `HLstats.plib`, `HLstats_EventHandlers.plib` — because those
# are the only ones KTP modifies, and vendoring the rest would invite someone
# to "fix" upstream code in a fork that has to stay rebasable. `deploy.ps1`
# says as much: it stages those three into `/opt/hlstatsx/scripts/` alongside
# whatever is already there.
#
# That is correct for deployment and fatal for a test container, where nothing
# is already there. `hlstats.pl` requires seven more files by absolute path
# (lines 72-79) and dies at the first one:
#
#     Can't locate .//ConfigReaderSimple.pm at hlstats.pl line 72
#
# So Lane B has to reproduce production's composition: upstream libs, with the
# fork's three files laid over them. That is what this does.
#
# ## Provenance, and why it is written to disk
#
# Two sources, in order of fidelity:
#
#   1. `--from-production` — scp from the data server. This is what production
#      actually runs, so it is the only source that cannot be wrong. Read-only;
#      it copies out and never writes back.
#   2. Pinned upstream (default) — HLStatsX:CE at a fixed commit. A
#      reconstruction. It is almost certainly identical, because the fork does
#      not touch these files, but "almost certainly" is not "verified" and a
#      Lane B run that quietly used the wrong daemon libs would be worse than
#      one that failed.
#
# Either way a PROVENANCE file lands in the output directory naming the source,
# so a run report can say which was used instead of leaving it to be inferred.
#
# Usage:
#   scripts/assemble_daemon_tree.sh <fork-repo> <out-dir> [--from-production]
set -euo pipefail

FORK="${1:?usage: assemble_daemon_tree.sh <fork-repo> <out-dir> [--from-production]}"
OUT="${2:?usage: assemble_daemon_tree.sh <fork-repo> <out-dir> [--from-production]}"
MODE="${3:-}"

# Pinned deliberately. Upstream is effectively dormant (HEAD dates to 2023), so
# this is stable rather than a moving target — but pinning means a Lane B
# result stays reproducible even if that changes.
UPSTREAM_REPO="${LANE_B_UPSTREAM_REPO:-https://github.com/NomisCZ/hlstatsx-community-edition}"
UPSTREAM_REF="${LANE_B_UPSTREAM_REF:-0b5af0963186f6bbca4f1eaf2fac37fe9a138a64}"
PROD_HOST="${LANE_B_PROD_HOST:-krodssh@api.ktpdod.com}"
PROD_DIR="${LANE_B_PROD_DIR:-/opt/hlstatsx/scripts}"

# Required by hlstats.pl:72-79. Not a guess — if this list drifts, the daemon
# says which file it wanted.
UPSTREAM_FILES=(
    ConfigReaderSimple.pm
    TRcon.pm
    BASTARDrcon.pm
    HLstats_Server.pm
    HLstats_Player.pm
    HLstats_Game.pm
    HLstats_GameConstants.plib
)
# The fork's delta. These are laid down LAST and win any collision.
FORK_FILES=(
    hlstats.pl
    HLstats.plib
    HLstats_EventHandlers.plib
)

mkdir -p "$OUT"

if [ "$MODE" = "--from-production" ]; then
    echo "fetching upstream libs from production ($PROD_HOST:$PROD_DIR)"
    for f in "${UPSTREAM_FILES[@]}"; do
        scp -q "$PROD_HOST:$PROD_DIR/$f" "$OUT/$f"
    done
    SOURCE="production $PROD_HOST:$PROD_DIR"
else
    echo "fetching upstream libs from $UPSTREAM_REPO @ ${UPSTREAM_REF:0:12}"
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    git -C "$tmp" init -q .
    git -C "$tmp" remote add origin "$UPSTREAM_REPO"
    git -C "$tmp" fetch -q --depth 1 origin "$UPSTREAM_REF"
    git -C "$tmp" checkout -q FETCH_HEAD
    for f in "${UPSTREAM_FILES[@]}"; do
        src="$tmp/scripts/$f"
        [ -f "$src" ] || { echo "upstream is missing $f — the pinned ref is wrong" >&2; exit 1; }
        cp "$src" "$OUT/$f"
    done
    SOURCE="upstream $UPSTREAM_REPO @ $UPSTREAM_REF (RECONSTRUCTION, not production)"
fi

for f in "${FORK_FILES[@]}"; do
    [ -f "$FORK/scripts/$f" ] || { echo "fork is missing scripts/$f" >&2; exit 1; }
    cp "$FORK/scripts/$f" "$OUT/$f"
done

# ---------------------------------------------------------------------------
# Diagnostic: make printEvent talk in --stdin mode.
#
# `printEvent` is gated on `(($g_debug > 0) && ($g_stdin == 0)) || (($g_stdin ==
# 1) && ($force_output == 1))` — so under --stdin, which is the only mode Lane B
# uses, `--debug` does nothing and per-event output is unreachable. That output
# is where the daemon says WHY it dropped an event: `(IGNORED) BOT:`,
# `(IGNORED) NOTMINPLAYERS:`, `(IGNORED) NOPLAYERINFO:`. Without it a zero row
# count carries no explanation at all, and the question "is capture broken or is
# the daemon configured wrong?" costs a debugging session every time.
#
# Safe because printEvent only prints. It has no effect on what is recorded, and
# this is a scratch tree that is never deployed — `deploy.ps1` stages three files
# and this is not one of them. Recorded in PROVENANCE so a run is never quietly
# using a modified daemon.
#
# Set LANE_B_NO_DIAGNOSTICS=1 to skip, if you want a byte-exact daemon.
DIAGNOSTIC="none"
if [ "${LANE_B_NO_DIAGNOSTICS:-0}" != "1" ]; then
    python3 - "$OUT/HLstats.plib" <<'PY'
import sys
path = sys.argv[1]
lines = open(path).read().split("\n")
for i, line in enumerate(lines):
    if "force_output == 1" in line and line.strip().startswith("if"):
        lines[i] = "\tif ( 1 ) {  # LANE B DIAGNOSTIC: print events under --stdin"
        break
else:
    raise SystemExit("printEvent gate not found — upstream changed shape")
open(path, "w").write("\n".join(lines))
PY
    DIAGNOSTIC="printEvent forced on (diagnostic; print-only, not deployed)"
fi

fork_rev=$(git -C "$FORK" rev-parse HEAD 2>/dev/null || echo unknown)
{
    echo "upstream_libs: $SOURCE"
    echo "fork_rev:      $fork_rev"
    echo "fork_files:    ${FORK_FILES[*]}"
    echo "diagnostic:    $DIAGNOSTIC"
    echo ""
    echo "md5:"
    (cd "$OUT" && md5sum "${UPSTREAM_FILES[@]}" "${FORK_FILES[@]}")
} > "$OUT/PROVENANCE"

echo "assembled $(ls -1 "$OUT" | wc -l) files in $OUT"
sed -n '1,3p' "$OUT/PROVENANCE"
