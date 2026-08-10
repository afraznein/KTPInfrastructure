#!/usr/bin/env bash
# Lane B, driven locally against Docker. Companion to the CI workflow
# (.github/workflows/lane-b-stats-e2e.yml) for iterating without a push.
#
# Usage:
#   scripts/lane_b_local.sh build-image      # build ktp-lane-b:dev
#   scripts/lane_b_local.sh build-artifacts  # compile the plugin + collect SQL
#   scripts/lane_b_local.sh spike-db         # Phase 0, database half (no bot)
#   scripts/lane_b_local.sh spike-full       # Phase 0, needs a bot kit
#   scripts/lane_b_local.sh unit             # unit tests inside the image
#   scripts/lane_b_local.sh shell            # interactive poke-around
#
# ---------------------------------------------------------------------------
# Three environment traps this script exists to avoid. All three were hit for
# real, and each one failed in a way that looked like a different problem.
# ---------------------------------------------------------------------------
#
# 1. RUN IT FROM A REAL LINUX SHELL, not Git Bash / MSYS.
#    Git Bash rewrites POSIX-looking argv entries into Windows paths when it
#    invokes a Windows .exe (wsl.exe, docker.exe). That turned
#        -v "$PWD/scripts:/work/scripts:ro"
#    into a bind of `G:\GIT\scripts`, so /work/scripts came up EMPTY and python
#    reported "can't open file .../build_stats_lane_artifacts.py" — which reads
#    as a missing file, not a mangled mount.
#
# 2. NOTHING UNDER /tmp, if docker came from the snap.
#    The docker snap has a PRIVATE /tmp. A `-v /tmp/out:/work/build` bind sees
#    nothing on the host: docker creates an empty dir inside its own namespace,
#    the run writes there, and every artifact vanishes when the container exits
#    — a green-looking run that produced nothing. $HOME works because
#    `snap connections docker` shows the `home` interface connected.
#    (`removable-media` is NOT connected, which is why /mnt/<drive> is
#    unreachable and the repos have to be cloned onto ext4 first.)
#
# 3. KEEP THE WSL DISTRO ALIVE.
#    WSL shuts the distro down once no process is attached, taking dockerd with
#    it. Back-to-back invocations then race a restarting daemon and fail with
#    "cannot connect to the Docker daemon" or a missing socket. Hold it open:
#        wsl -d Ubuntu -- bash -lc "sleep 21600" &
set -euo pipefail

REPO="${LANE_B_REPO:-$HOME/ktp/KTPInfrastructure}"
REPOS="${LANE_B_REPOS:-$HOME/ktp}"
OUT="${LANE_B_OUT:-$HOME/lane-b-out}"          # see trap 2 — never /tmp
IMAGE="${LANE_B_IMAGE:-ktp-lane-b:dev}"
BASE_IMAGE="${LANE_B_BASE_IMAGE:-ghcr.io/afraznein/ktp-runtime-test-base:latest}"
BOT_KIT="${LANE_B_BOT_KIT:-$HOME/bot-kit}"
DOCKER="${LANE_B_DOCKER:-docker}"

AMXX_REF="${AMXX_REF:-origin/feat/stats-positions}"
DAEMON_REF="${DAEMON_REF:-origin/feat/seed-cap-break-action}"
MAP_NAME="${MAP_NAME:-dod_anzio}"
PLAY_SECONDS="${PLAY_SECONDS:-180}"
BOT="${BOT:-marinebot}"

mkdir -p "$OUT"

in_image() {
    local extra=()
    [ -d "$BOT_KIT" ] && extra+=(-v "$BOT_KIT:/opt/bot-kit:ro")
    "$DOCKER" run --rm \
        -v "$REPOS:/repos:ro" \
        -v "$REPO/tests:/work/tests:ro" \
        -v "$REPO/scripts:/work/scripts:ro" \
        -v "$OUT:/work/build" \
        "${extra[@]}" \
        -w /work "$IMAGE" bash -c "$1"
}

case "${1:-}" in

build-image)
    "$DOCKER" build --build-arg "BASE_IMAGE=$BASE_IMAGE" \
        -t "$IMAGE" -f "$REPO/build/lane-b/Dockerfile" "$REPO/build/lane-b"
    ;;

build-artifacts)
    in_image "
        python3 scripts/build_stats_lane_artifacts.py \
            --amxx-repo   /repos/KTPAMXX      --amxx-ref   '$AMXX_REF' \
            --daemon-repo /repos/KTPHLStatsX  --daemon-ref '$DAEMON_REF' \
            --amxxpc   /opt/hlds/dod/addons/ktpamx/scripting/amxxpc \
            --includes /opt/hlds/dod/addons/ktpamx/scripting/include \
            --out /work/build/artifacts
    "
    ;;

spike-db)
    # $OUT/base-schema.sql is a `mysqldump --no-data` of production. It is
    # required: sql/ktp_schema.sql is an ALTER-only overlay and cannot create a
    # database on its own.
    #
    # ktp_schema.sql is deliberately NOT applied by default. Two reasons, and
    # the second is the interesting one:
    #   1. Redundant — a production-derived base already has match_id, half and
    #      pos_x/y/z on the event tables.
    #   2. It does not run on MySQL at all. It uses `ADD COLUMN IF NOT EXISTS`
    #      (MariaDB-only); production is MySQL 8.0.46 and rejects it with
    #      ERROR 1064, aborting before every later statement. Its own header
    #      documents this. Set LANE_B_APPLY_KTP_SCHEMA=1 to reproduce the
    #      failure on purpose.
    if [ ! -f "$OUT/base-schema.sql" ]; then
        echo "missing $OUT/base-schema.sql — take one with:" >&2
        echo "  mysqldump --no-data --single-transaction --skip-lock-tables \\" >&2
        echo "      --no-tablespaces --set-gtid-purged=OFF hlstatsx > base-schema.sql" >&2
        exit 1
    fi
    SCHEMA="/work/build/base-schema.sql"
    [ "${LANE_B_APPLY_KTP_SCHEMA:-0}" = "1" ] && \
        SCHEMA="$SCHEMA /work/build/artifacts/sql/ktp_schema.sql"
    in_image "
        python3 scripts/spike_bot_lane.py --skip-server \
            --schema $SCHEMA \
            --seed   /work/build/artifacts/sql/migrate_003_assist_action.sql \
                     /work/build/artifacts/sql/migrate_004_cap_break_action.sql \
            --out /work/build/spike-db.json
    "
    ;;

spike-full)
    if [ ! -d "$BOT_KIT" ]; then
        echo "no bot kit at $BOT_KIT — a full spike needs one. Refusing to" >&2
        echo "silently run the db half instead; use spike-db if that is what" >&2
        echo "you meant." >&2
        exit 1
    fi
    BASE=""
    [ -f "$OUT/base-schema.sql" ] && BASE="/work/build/base-schema.sql"
    in_image "
        python3 scripts/spike_bot_lane.py \
            --serverfiles /opt/hlds --in-place \
            --bot-kit /opt/bot-kit --bot '$BOT' \
            --map '$MAP_NAME' --play-seconds '$PLAY_SECONDS' \
            --schema $BASE /work/build/artifacts/sql/ktp_schema.sql \
            --seed   /work/build/artifacts/sql/migrate_003_assist_action.sql \
                     /work/build/artifacts/sql/migrate_004_cap_break_action.sql \
            --out /work/build/spike-full.json
    "
    ;;

unit)
    in_image "python3 -m pytest tests/e2e_stats -q"
    ;;

shell)
    local_extra=()
    [ -d "$BOT_KIT" ] && local_extra+=(-v "$BOT_KIT:/opt/bot-kit:ro")
    "$DOCKER" run --rm -it \
        -v "$REPOS:/repos:ro" \
        -v "$REPO/tests:/work/tests:ro" \
        -v "$REPO/scripts:/work/scripts:ro" \
        -v "$OUT:/work/build" \
        "${local_extra[@]}" \
        -w /work "$IMAGE" bash
    ;;

*)
    sed -n '2,12p' "$0"
    exit 2
    ;;
esac
